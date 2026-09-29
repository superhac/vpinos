#!/bin/sh
# Crude placeholder menu. launch.sh handles everything -- starting
# Hyprland directly (exec, inheriting this shell's tty/session) and the
# chosen client as its client -- so this just needs to run it with
# the right command and wait for it to return.
#
# Only the installer is `sudo`'d -- it genuinely needs root for
# partitioning. vpinball/vpinfe/Chrome run directly as whichever user
# is running this menu (`vpinos`, in normal operation): seatd's default
# config already grants DRM/seat access to `video`-group members, no
# root required.
#
# A Textual (python3-textual) rewrite of this menu was tried and
# reverted -- it never rendered correctly on the real Linux virtual
# console (TERM=linux/fbcon): a confirmed, still-open upstream bug
# (https://github.com/Textualize/rich/issues/3231) means Rich/Textual's
# Unicode box-drawing borders don't render reliably there, even with a
# Unicode-capable console font and the right locale/encoding -- plain
# ASCII borders were tried too and still didn't come out right on a
# real boot. Back to plain POSIX sh/echo, which has no such dependency.

# VPXConfig is a local web server (127.0.0.1:1111) driven from a browser:
# start it, wait until it answers, run Chrome as launch.sh's client on it,
# and stop the server as soon as the browser closes (launch.sh returns when
# its client exits). Bound to loopback only -- it can change system
# configuration, so it must never listen externally.
vpxconfig_port=1111
vpxconfig_log=/var/log/vpinos-vpxconfig.log
vpxconfig_pid=""

stop_vpxconfig() {
    [ -n "$vpxconfig_pid" ] || return 0
    kill "$vpxconfig_pid" 2>/dev/null
    # vpxconfig is a single-file bundled executable that can leave a
    # child process behind; make sure nothing of ours is left listening.
    pkill -u "$(id -u)" -x vpxconfig 2>/dev/null
    wait "$vpxconfig_pid" 2>/dev/null
    vpxconfig_pid=""
    echo "$(date -Is): menu: vpxconfig stopped" >>/var/log/vpinos-menu.log
}

run_vpxconfig() {
    # Something (e.g. a leftover instance) already holds the port:
    # starting a second server would fail and Chrome would open the
    # stale one instead.
    if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$vpxconfig_port/"; then
        echo "Something is already listening on 127.0.0.1:$vpxconfig_port."
        echo "Stop it first (e.g. 'pkill vpxconfig') and try again."
        sleep 3
        return 1
    fi

    echo "$(date -Is): menu: starting vpxconfig on 127.0.0.1:$vpxconfig_port" >>/var/log/vpinos-menu.log
    /usr/bin/vpxconfig --host 127.0.0.1 --port "$vpxconfig_port" >>"$vpxconfig_log" 2>&1 &
    vpxconfig_pid=$!
    trap 'stop_vpxconfig; exit 1' INT TERM HUP

    # Wait (up to ~30s: a bundled executable unpacks itself on first
    # run) for the server to answer, bailing out if it already died.
    echo "Starting VPXConfig..."
    i=0
    until curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$vpxconfig_port/"; do
        if ! kill -0 "$vpxconfig_pid" 2>/dev/null; then
            echo "VPXConfig exited during startup -- see $vpxconfig_log"
            echo "$(date -Is): menu: vpxconfig died during startup" >>/var/log/vpinos-menu.log
            vpxconfig_pid=""
            trap - INT TERM HUP
            sleep 3
            return 1
        fi
        i=$((i + 1))
        if [ "$i" -ge 30 ]; then
            echo "VPXConfig did not start listening within 30s -- see $vpxconfig_log"
            stop_vpxconfig
            trap - INT TERM HUP
            sleep 3
            return 1
        fi
        sleep 1
    done

    # client_name "vpxconfig" (not "chrome"): that's what launch.sh matches
    # on to pick the windowed Hyprland config instead of the fullscreen
    # kiosk one -- a config tool needs a visible, obvious way to close it,
    # unlike vpinball/vpinfe/the debug Chrome option. --app=URL (not
    # --kiosk) opens a plain app window with a title bar and close button
    # instead of suppressing all window chrome; --start-maximized fills
    # the screen anyway (a real maximize, not fullscreen -- the title
    # bar/close button stay visible).
    #
    # Returns when the browser is closed; the server is stopped right
    # after, whatever the browser's exit status was.
    /usr/local/bin/launch.sh vpxconfig /usr/bin/google-chrome \
        "--app=http://127.0.0.1:$vpxconfig_port" --start-maximized \
        --no-first-run --disable-session-crashed-bubble --noerrdialogs
    echo "$(date -Is): menu: launch.sh (vpxconfig browser) exited $?" >>/var/log/vpinos-menu.log
    stop_vpxconfig
    trap - INT TERM HUP
}

# /etc/vpinos/boot-mode is what /etc/profile.d/vpinos-menu.sh reads at
# login to decide what to auto-launch before falling through to here.
# Changing it only makes sense on an INSTALLED system -- a live session
# never persists it across a reboot, and boot=live on the kernel cmdline
# is the same mechanism live-config itself already uses to tell the two
# apart (see notes/vpinos.md step 5), so it's precedented, not something
# new. Option 7 (and its whole submenu) simply doesn't exist on a live
# session -- not shown, not selectable, no renumbering of 1-6 either way.
is_installed() {
    ! grep -q 'boot=live' /proc/cmdline 2>/dev/null
}

# The list of available boot-on-startup programs lives here as a plain
# case statement, not a data structure -- POSIX sh (this file's shebang)
# has no arrays/associative arrays, and every other piece of this menu is
# already a plain case statement, so this matches. To add a program here,
# see the `manage-boot-programs` skill in notes/skills/ -- it walks
# through this function, the matching case arm in
# /etc/profile.d/vpinos-menu.sh, the audit check, and the docs together.
boot_mode_submenu() {
    while true; do
        clear
        cur=$(cat /etc/vpinos/boot-mode 2>/dev/null)
        [ -z "$cur" ] && cur=menu
        echo "=============================="
        echo "      Boot on startup"
        echo "=============================="
        echo "Currently: $cur"
        echo
        echo "1) VPinOS menu (default)"
        echo "2) VPinFE"
        echo "q) Cancel, no change"
        echo "=============================="
        printf "Select an option: "
        read -r bchoice
        case "$bchoice" in
            1)
                echo "menu" > /etc/vpinos/boot-mode
                echo "$(date -Is): menu: boot-mode set to menu" >>/var/log/vpinos-menu.log
                echo "Will boot to the VPinOS menu on next startup."
                sleep 2
                return
                ;;
            2)
                echo "vpinfe" > /etc/vpinos/boot-mode
                echo "$(date -Is): menu: boot-mode set to vpinfe" >>/var/log/vpinos-menu.log
                echo "Will boot straight to VPinFE on next startup."
                sleep 2
                return
                ;;
            q|Q)
                return
                ;;
            *)
                echo "Invalid option"
                sleep 1
                ;;
        esac
    done
}

while true; do
    clear
    echo "=============================="
    echo "            VPinOS"
    echo "=============================="
    echo "1) Configuration"
    echo "2) Network Settings"
    echo "3) Launch VPinball Example Table"
    echo "4) VPinFE"
    echo "5) VPinFE Map Controls"
    # 6) Launch Chrome only (debug) -- hidden from the menu for now, but
    # the case arm below is kept working; run it directly if needed:
    # /usr/local/bin/launch.sh chrome /usr/bin/google-chrome --kiosk ...
    echo "7) Install VPinOS"
    echo "8) VPXConfig (Advanced VPinball Configuration)"
    if is_installed; then
        cur=$(cat /etc/vpinos/boot-mode 2>/dev/null)
        [ -z "$cur" ] && cur=menu
        echo "9) Boot on startup: $cur"
    fi
    echo "q) Quit to shell"
    echo "s) Shutdown"
    echo "=============================="
    printf "Select an option: "
    read -r choice

    case "$choice" in
        1)
            echo "$(date -Is): menu: selected option 1 (configuration)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh shell /usr/local/bin/vpinos-config.py
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        2)
            # nmtui is a plain ncurses TUI (NetworkManager's own) -- no
            # display server needed, unlike every other option here, so
            # it runs directly in this tty rather than through
            # launch.sh/Hyprland. Covers both Ethernet and Wi-Fi
            # connections (edit/activate), plus the system hostname --
            # not Wi-Fi-specific despite the common association. `sudo`
            # (scoped in /etc/sudoers.d/vpinos) because editing
            # connections needs polkit auth_admin_keep even for the
            # active local session, and there's no polkit agent here to
            # satisfy that prompt -- root bypasses it entirely.
            echo "$(date -Is): menu: selected option 2 (network settings)" >>/var/log/vpinos-menu.log
            sudo nmtui
            echo "$(date -Is): menu: nmtui exited $?" >>/var/log/vpinos-menu.log
            ;;
        3)
            echo "$(date -Is): menu: selected option 3 (vpinball)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh vpinball \
                /opt/vpinball/VPinballX_BGFX -play /opt/vpinball/assets/exampleTable.vpx
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        4)
            echo "$(date -Is): menu: selected option 4 (vpinfe)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh vpinfe /opt/vpinfe/vpinfe
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        5)
            # --gamepadtest: vpinfe's own controller-mapping mode. Routed
            # through launch.sh the same as plain vpinfe (option 4) --
            # still a real Wayland client needing Hyprland up, just given
            # an extra flag (launch.sh's own usage comment already
            # documents `<name> <command> [args...]`, so this is nothing
            # new). Distinct client_name for its own clearly-labeled log
            # lines; doesn't affect hypr_config selection (only
            # "installer"/"vpxconfig" get the windowed config, everything
            # else -- this included -- gets the normal fullscreen kiosk
            # one, matching plain vpinfe's own treatment).
            echo "$(date -Is): menu: selected option 5 (vpinfe map controls)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh vpinfe-gamepadtest /opt/vpinfe/vpinfe --gamepadtest
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        6)
            echo "$(date -Is): menu: selected option 6 (chrome debug)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh chrome /usr/bin/google-chrome \
                --kiosk --enable-logging=stderr --vmodule='*ozone*=1,*wayland*=1' about:blank
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        7)
            echo "$(date -Is): menu: selected option 7 (calamares installer)" >>/var/log/vpinos-menu.log
            sudo /usr/local/bin/launch.sh installer /usr/bin/calamares
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        8)
            echo "$(date -Is): menu: selected option 8 (vpxconfig)" >>/var/log/vpinos-menu.log
            run_vpxconfig
            ;;
        9)
            if is_installed; then
                boot_mode_submenu
            else
                echo "Invalid option"
                sleep 1
            fi
            ;;
        q|Q)
            break
            ;;
        s|S)
            printf "Shut down now? [y/N]: "
            read -r confirm
            case "$confirm" in
                y|Y)
                    echo "$(date -Is): menu: selected shutdown, confirmed" >>/var/log/vpinos-menu.log
                    sudo /usr/bin/systemctl poweroff
                    ;;
                *)
                    echo "$(date -Is): menu: selected shutdown, cancelled" >>/var/log/vpinos-menu.log
                    ;;
            esac
            ;;
        *)
            echo "Invalid option"
            sleep 1
            ;;
    esac
done
