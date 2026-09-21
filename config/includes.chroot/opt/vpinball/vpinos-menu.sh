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
# start it, wait until it answers, run Chrome in kiosk mode on it as
# launch.sh's client, and stop the server as soon as the browser closes
# (launch.sh returns when its client exits). Bound to loopback only --
# it can change system configuration, so it must never listen externally.
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

    # Returns when the browser is closed; the server is stopped right
    # after, whatever the browser's exit status was.
    /usr/local/bin/launch.sh chrome /usr/bin/google-chrome \
        --kiosk --no-first-run --disable-session-crashed-bubble --noerrdialogs \
        "http://127.0.0.1:$vpxconfig_port"
    echo "$(date -Is): menu: launch.sh (vpxconfig browser) exited $?" >>/var/log/vpinos-menu.log
    stop_vpxconfig
    trap - INT TERM HUP
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
        q|Q)
            break
            ;;
        *)
            echo "Invalid option"
            sleep 1
            ;;
    esac
done
