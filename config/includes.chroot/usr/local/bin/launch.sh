#!/bin/sh
# Starts weston directly in the foreground of the calling shell (via
# `exec`, at the bottom -- inherits its tty/session properly, the way
# systemd's ExecStart did) and launches a given client as weston's
# client once the Wayland socket is up. Run directly from an
# interactive shell (the `vpinos` user for vpinball/vpinfe/Chrome --
# seatd's default config already grants `video`-group members DRM/seat
# access, no root needed; still `sudo`'d for the installer specifically,
# which genuinely needs root for partitioning -- see vpinos-menu.sh);
# not a systemd service.
#
# Usage: launch.sh <name-for-logging> <command> [args...]
#   e.g. launch.sh vpinball /opt/vpinball/VPinballX_BGFX -play /opt/vpinball/assets/exampleTable.vpx
#        launch.sh vpinfe /opt/vpinfe/vpinfe

set -e

client_name="${1:?usage: launch.sh <name> <command> [args...]}"
shift

# /run/user/<uid> rather than a custom root-owned path: for the normal
# (non-installer) case this runs as `vpinos`, a real PAM-logged-in
# user, whose /run/user/1000 already exists (pam_systemd) with correct
# ownership -- mkdir/chmod here are then harmless no-ops. For the
# installer, still run via `sudo` (root, uid 0): /run/user/0 typically
# doesn't exist yet since root has no active login session, so this
# creates it fresh. Same two lines handle both cases correctly since
# they key off the actual effective uid rather than assuming which one
# it is.
runtime_dir="/run/user/$(id -u)"
mkdir -p "$runtime_dir"
chmod 0700 "$runtime_dir"
export XDG_RUNTIME_DIR="$runtime_dir"

log_file="/var/log/vpinos-launch.log"

# Captured before `exec` replaces this process with weston -- `exec`
# keeps the same PID, so this is weston's PID too, letting
# launch_client (below) stop weston once its client exits.
weston_pid=$$

wait_for_glob() {
    # Polls for a glob pattern to match a real file, up to ~10s.
    # Prints the first match and returns 0, or prints nothing and
    # returns 1 on timeout.
    pattern="$1"
    i=0
    while [ "$i" -lt 100 ]; do
        match=$(ls $pattern 2>/dev/null | head -n1)
        if [ -n "$match" ]; then
            echo "$match"
            return 0
        fi
        sleep 0.1
        i=$((i + 1))
    done
    return 1
}

launch_client() {
    # $@ here comes from the explicit args passed at the call site
    # below (`launch_client "$@" &`) -- a shell function called with no
    # arguments of its own does NOT inherit the script's positional
    # parameters (confirmed directly: $@ comes back empty inside an
    # argument-less call, in both dash and bash), so this isn't
    # decoration.

    if [ "$client_name" = "installer" ]; then
        # calamares's Wayland support is unreliable -- confirmed
        # directly, not a guess: even with QT_QPA_PLATFORM=wayland
        # forced and qt6-wayland installed, its main window rendered
        # fine under weston but its "Cancel Installation?" popup
        # showed readable text with zero button/panel chrome (tried
        # forcing QT_QUICK_CONTROLS_STYLE=Basic -- no change, tried
        # QT_QUICK_BACKEND=software -- see vpinos.md for the full
        # history), and a separate run crashed outright with a raw
        # Xlib "Cannot open display" error -- something inside
        # calamares calls XOpenDisplay() directly regardless of
        # QT_QPA_PLATFORM. Two independent community workarounds for
        # calamares-under-VM issues both target XCB specifically, not
        # Wayland, which lines up. Giving it a real X11 display via
        # Xwayland (weston's --xwayland flag, see below) instead of
        # continuing to chase Wayland-side fixes.
        display_sock=$(wait_for_glob "/tmp/.X11-unix/X*") || {
            echo "$(date -Is): launch.sh: timed out waiting for Xwayland's X11 socket" >>"$log_file"
            return 1
        }
        export DISPLAY=":$(basename "$display_sock" | sed 's/^X//')"
        export QT_QPA_PLATFORM=xcb
        export QT_XCB_GLYPH_CACHE_WORKAROUND=1
        display_label="DISPLAY=$DISPLAY"
    else
        sock=$(wait_for_glob "$runtime_dir/wayland-*.lock") || {
            echo "$(date -Is): launch.sh: timed out waiting for weston's Wayland socket" >>"$log_file"
            return 1
        }
        export WAYLAND_DISPLAY
        WAYLAND_DISPLAY=$(basename "$sock" .lock)
        export SDL_VIDEODRIVER=wayland
        export GDK_BACKEND=wayland
        display_label="WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
    fi

    echo "$(date -Is): launch.sh: launching $client_name -- $display_label -- $*" >>"$log_file"
    # stdbuf -oL -eL: output redirected to a file (not a terminal)
    # normally switches C stdio from line-buffered to fully-buffered,
    # so a long-running client's output just sits in memory until the
    # buffer fills or the process exits -- confirmed directly: with a
    # client that never exits and never says much, the log stayed
    # empty (just the launch line above) even with WAYLAND_DEBUG=1 set,
    # because nothing had triggered a flush yet. Forces line buffering
    # instead so output actually lands in the log as it happens.
    #
    # set +e/-e around this call specifically: `set -e` is active for
    # the whole script, and if the client returns ANY non-zero exit
    # code, `set -e` aborts this entire function immediately and
    # silently -- skipping both the "exited" log line below AND the
    # kill "$weston_pid" call after it. That was the actual root cause
    # of every single "Chrome only" test showing nothing but the launch
    # line, forever, no matter which Chrome flags were tried -- none of
    # those changes could ever have mattered if the script was dying
    # before it could log anything about them. vpinball never hit this
    # because it happens to exit 0.
    set +e
    stdbuf -oL -eL "$@" >>"$log_file" 2>&1
    rc=$?
    set -e
    echo "$(date -Is): launch.sh: $client_name exited $rc, stopping weston" >>"$log_file"

    # weston doesn't quit on its own just because its only client
    # closed -- without this, exiting the client leaves a black screen
    # (weston still running, nothing to show) instead of returning to
    # the menu.
    kill "$weston_pid" 2>/dev/null || true
}

launch_client "$@" &

# weston's xwayland module binds its X11 socket directly under
# /tmp/.X11-unix -- confirmed directly (via a real crash) that it does
# NOT create that directory itself, and on this weston version, failing
# to bind there is FATAL to the whole compositor, not just a
# gracefully-skipped X11 support ("failed to bind to /tmp/.X11-unix/X0:
# No such file or directory" was the last line weston ever logged
# before exiting -- taking down the Wayland socket every client,
# X11-using or not, depends on). This directory is normally created by
# systemd-tmpfiles at boot, but isn't reliably present by the time this
# runs -- ensuring it directly instead of depending on that ordering.
#
# Tolerate failure on both: vpinball/vpinfe/Chrome now run as `vpinos`
# (non-root), but the installer still runs as root via `sudo` -- if the
# installer runs first in a boot session and creates this directory as
# root, a later non-root chmod attempt here would fail (chmod requires
# ownership or root) and abort the whole script under `set -e`. Safe to
# ignore: the directory already being 1777 from that earlier root run
# is exactly the state this line exists to guarantee anyway.
mkdir -p /tmp/.X11-unix 2>/dev/null || true
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# weston's own output has never been captured anywhere -- it inherits
# whatever tty ran this script, invisible once weston itself paints
# over that tty's console, the exact same problem solved for the
# client's output above. Capturing it separately since weston's own
# diagnostics (e.g. about how it's handling a client's surface) are a
# distinct signal from the client's.
#
# The installer gets its own config (windowed desktop-shell) because
# kiosk-shell would stretch Calamares to the full output -- see
# /etc/vpinos/weston-installer.ini.
weston_config=/etc/vpinos/weston.ini
[ "$client_name" = "installer" ] && weston_config=/etc/vpinos/weston-installer.ini
exec /usr/bin/weston --xwayland --config="$weston_config" >>/var/log/vpinos-weston.log 2>&1
