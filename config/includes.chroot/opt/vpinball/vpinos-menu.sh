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

while true; do
    clear
    echo "=============================="
    echo "            VPinOS"
    echo "=============================="
    echo "1) Launch VPinball (Example Table)"
    echo "2) Launch VPinFE (Frontend)"
    echo "3) Launch Chrome only (debug)"
    echo "4) Launch Installer (Calamares)"
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
        q|Q)
            break
            ;;
        *)
            echo "Invalid option"
            sleep 1
            ;;
    esac
done
