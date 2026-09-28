# Auto-launch the console menu on a fresh interactive console login,
# instead of dropping straight to a bare shell prompt -- both the live
# session and an installed system autolog in as `vpinos` on tty1 (see
# notes/vpinos.md step 5), and /etc/profile sources every *.sh file here
# for every login shell, so one file covers both.
#
# Deliberately NOT exec'd: vpinos-menu's own "q" (Quit to shell) option
# just returns here, and this script then falls through to a normal
# interactive shell rather than relooping -- console shell access (used
# constantly for debugging: journalctl, apt, editing config by hand) is
# never actually lost, just one keypress away, not permanently replaced.
#
# Guards: SSH sessions (SSH_CONNECTION is set by sshd) must stay a plain
# shell -- remote admin access auto-launching a blocking menu would be
# actively unhelpful. `$-` / `[ -t 0 ]` skip non-interactive or non-tty
# invocations (e.g. anything that happens to source /etc/profile as part
# of a script, rather than a real console login).
case $- in
    *i*) ;;
    *) return 2>/dev/null || exit 0 ;;
esac
if [ -z "$SSH_CONNECTION" ] && [ -t 0 ]; then
    # /etc/vpinos/boot-mode ("menu" by default, baked into the image, or
    # the name of a program below) picks what launches automatically
    # before falling through to vpinos-menu -- same non-exec philosophy
    # as this whole file: whatever runs here, control still falls through
    # to the menu (and from there, "q", to a real shell) afterward, never
    # a dead end. Set from vpinos-menu's own "Boot on startup" submenu
    # (installed systems only -- see that script's is_installed check).
    #
    # To add a new boot-on-startup program: see the
    # `manage-boot-programs` skill in notes/skills/ -- it walks through
    # this case arm, the matching submenu entry in vpinos-menu.sh, the
    # audit check, and the docs together, so they can't drift out of
    # sync with each other.
    case "$(cat /etc/vpinos/boot-mode 2>/dev/null)" in
        vpinfe)
            /usr/local/bin/launch.sh vpinfe /opt/vpinfe/vpinfe
            ;;
        menu | "")
            ;;
        *)
            # Unrecognized value (corrupted file, or a mode a newer
            # vpinos-menu wrote that this older profile script doesn't
            # know yet) -- fail safe to just the menu, don't guess.
            echo "$(date -Is): profile: unknown boot-mode '$(cat /etc/vpinos/boot-mode 2>/dev/null)', falling back to menu" >>/var/log/vpinos-menu.log
            ;;
    esac
    vpinos-menu
fi
