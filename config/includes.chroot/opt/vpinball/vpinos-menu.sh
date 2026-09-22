#!/bin/sh
# Crude placeholder menu. launch.sh handles everything -- starting
# weston directly (exec, inheriting this shell's tty/session) and the
# chosen client as weston's client -- so this just needs to run it with
# the right command and wait for it to return.
#
# Only the installer is `sudo`'d -- it genuinely needs root for
# partitioning. vpinball/vpinfe/Chrome run directly as whichever user
# is running this menu (`vpinos`, in normal operation): seatd's default
# config already grants DRM/seat access to `video`-group members, no
# root required.

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
    # on to pick the windowed weston config instead of the fullscreen kiosk
    # one -- a config tool needs a visible, obvious way to close it, unlike
    # vpinball/vpinfe/the debug Chrome option. --app=URL (not --kiosk) opens
    # a plain app window with a title bar and close button instead of
    # suppressing all window chrome; --start-maximized fills the screen
    # anyway (a real maximize, not fullscreen -- the title bar/close button
    # stay visible), which weston's desktop-shell (windowed config) is a
    # normal xdg-shell compositor and should honor like any other.
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
# new. Option 6 (and its whole submenu) simply doesn't exist on a live
# session -- not shown, not selectable, no renumbering of 1-5 either way.
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
    echo "1) Launch VPinball (Example Table)"
    echo "2) Launch VPinFE (Frontend)"
    echo "3) Launch Chrome only (debug)"
    echo "4) Launch Installer (Calamares)"
    echo "5) Launch VPXConfig (Configuration)"
    if is_installed; then
        cur=$(cat /etc/vpinos/boot-mode 2>/dev/null)
        [ -z "$cur" ] && cur=menu
        echo "6) Boot on startup: $cur"
    fi
    echo "q) Quit to shell"
    echo "=============================="
    printf "Select an option: "
    read -r choice

    case "$choice" in
        1)
            echo "$(date -Is): menu: selected option 1 (vpinball)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh vpinball \
                /opt/vpinball/VPinballX_BGFX -play /opt/vpinball/assets/exampleTable.vpx
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        2)
            echo "$(date -Is): menu: selected option 2 (vpinfe)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh vpinfe /opt/vpinfe/vpinfe
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        3)
            echo "$(date -Is): menu: selected option 3 (chrome debug)" >>/var/log/vpinos-menu.log
            /usr/local/bin/launch.sh chrome /usr/bin/google-chrome \
                --kiosk --enable-logging=stderr --vmodule='*ozone*=1,*wayland*=1' about:blank
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        4)
            echo "$(date -Is): menu: selected option 4 (calamares installer)" >>/var/log/vpinos-menu.log
            sudo /usr/local/bin/launch.sh installer /usr/bin/calamares
            echo "$(date -Is): menu: launch.sh exited $?" >>/var/log/vpinos-menu.log
            ;;
        5)
            echo "$(date -Is): menu: selected option 5 (vpxconfig)" >>/var/log/vpinos-menu.log
            run_vpxconfig
            ;;
        6)
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
        *)
            echo "Invalid option"
            sleep 1
            ;;
    esac
done
