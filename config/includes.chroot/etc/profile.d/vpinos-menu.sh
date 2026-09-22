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
    vpinos-menu
fi
