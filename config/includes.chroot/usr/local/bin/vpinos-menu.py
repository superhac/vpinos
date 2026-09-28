#!/usr/bin/env python3
# VPinOS console menu -- Textual-based TUI, replaces the old
# vpinos-menu.sh (deleted; this is the same tool, not an addition).
# Still just a front-end: every action still shells out to the exact
# same /usr/local/bin/launch.sh invocations (or sudo systemctl
# poweroff) the shell version used -- this only replaces the
# menu/selection UI, not the underlying launch mechanism, privilege
# model, or sudoers scoping, none of which changed.
#
# Run non-interactively from /etc/profile.d/vpinos-menu.sh via the
# `vpinos-menu` symlink (repointed at this file by
# 0200-enable-kiosk.hook.chroot) -- NOT exec'd, so exiting (Quit to
# shell) falls through to a normal interactive shell exactly like the
# old script did.
#
# Every real launch.sh invocation execs Hyprland, which takes over the
# whole tty for the compositor session -- App.suspend() (a real,
# confirmed Textual API, checked directly against the installed
# python3-textual package's own source before writing this, not
# assumed) hands the terminal back fully for that, then restores
# Textual's own screen when the client exits and launch.sh returns.
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Label, OptionList, Static
from textual.widgets.option_list import Option

LOG_FILE = Path("/var/log/vpinos-menu.log")
BOOT_MODE_FILE = Path("/etc/vpinos/boot-mode")
LAUNCH = "/usr/local/bin/launch.sh"

VPXCONFIG_PORT = 1111
VPXCONFIG_LOG = Path("/var/log/vpinos-vpxconfig.log")
VPXCONFIG_STARTUP_TIMEOUT = 30


def log(msg: str) -> None:
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"{ts}: menu: {msg}\n")
    except OSError:
        pass


def is_installed() -> bool:
    # Same mechanism live-config itself already uses to tell live and
    # installed apart (see notes/vpinos.md step 5) -- a live session
    # never persists boot-mode across a reboot, so the "Boot on
    # startup" option is simply absent there, not shown/selectable.
    try:
        return "boot=live" not in Path("/proc/cmdline").read_text()
    except OSError:
        return True


def read_boot_mode() -> str:
    try:
        mode = BOOT_MODE_FILE.read_text().strip()
    except OSError:
        mode = ""
    return mode or "menu"


def curl_ok(port: int) -> bool:
    return (
        subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "--max-time", "1", f"http://127.0.0.1:{port}/"],
            capture_output=True,
        ).returncode
        == 0
    )


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No confirmation -- used for Shutdown, the one genuinely
    disruptive, hard-to-reverse action in this menu (everything else
    just launches something and returns)."""

    BINDINGS = [("y", "confirm", "Yes"), ("n", "cancel", "No"), ("escape", "cancel", "Cancel")]

    CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #dialog {
        width: 50;
        border: heavy $error;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question)
            yield Label("[y] Yes    [n] No", classes="hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class BootModeScreen(ModalScreen[None]):
    """Boot-on-startup submenu -- installed systems only. The list of
    available programs lives here as plain Option()s, matching the old
    script's own plain-case-statement style -- see the
    `manage-boot-programs` skill in notes/skills/ before adding one."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    BootModeScreen {
        align: center middle;
    }
    #panel {
        width: 60;
        border: heavy $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        current = read_boot_mode()
        with Vertical(id="panel"):
            yield Label(f"Boot on startup (currently: {current})", classes="title")
            yield OptionList(
                Option("VPinOS menu (default)", id="menu"),
                Option("VPinFE", id="vpinfe"),
                id="boot_mode_list",
            )

    def on_mount(self) -> None:
        self.query_one("#boot_mode_list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        mode = event.option_id
        BOOT_MODE_FILE.write_text(f"{mode}\n")
        log(f"boot-mode set to {mode}")
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


class VPinOSMenu(App[None]):
    TITLE = "VPinOS"

    CSS = """
    Screen {
        align: center middle;
    }
    #menu_panel {
        width: 74;
        border: heavy $accent;
        padding: 1 2;
    }
    #menu_status {
        color: $text-muted;
        height: auto;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("q", "quit_to_shell", "Quit to shell"),
        ("s", "select_shutdown", "Shutdown"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._vpxconfig_proc: subprocess.Popen | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="menu_panel"):
            yield Static("", id="menu_status")
            yield OptionList(id="main_menu")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_menu()

    def refresh_menu(self, *_args) -> None:
        # *_args: push_screen's callback is always invoked with exactly
        # one argument (the dismissed screen's result) -- this is also
        # used directly as that callback, and doesn't care what the
        # result was, just that it's time to redraw (e.g. boot-mode may
        # have changed).
        menu = self.query_one("#main_menu", OptionList)
        menu.clear_options()
        options = [
            Option("Configuration", id="configuration"),
            Option("Launch VPinball (Example Table)", id="vpinball"),
            Option("Launch VPinFE (Frontend)", id="vpinfe"),
            # "Launch Chrome only (debug)" hidden for now -- the
            # action_select_chrome_debug handler below still works,
            # just uncomment this line to bring the menu entry back.
            # Option("Launch Chrome only (debug)", id="chrome_debug"),
            Option("Launch Installer (Calamares)", id="installer"),
            Option("Launch VPXConfig (Configuration)", id="vpxconfig"),
        ]
        if is_installed():
            options.append(Option(f"Boot on startup: {read_boot_mode()}", id="boot_mode"))
        options.append(Option("Quit to shell", id="quit"))
        # Shutdown last, deliberately -- the most disruptive option,
        # placed furthest from where the cursor starts.
        options.append(Option("Shutdown", id="shutdown"))
        menu.add_options(options)
        menu.focus()

    def set_status(self, text: str) -> None:
        self.query_one("#menu_status", Static).update(text)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "main_menu":
            return
        handler = getattr(self, f"action_select_{event.option_id}", None)
        if handler is not None:
            handler()

    def run_suspended(self, *cmd: str) -> int:
        # Falls back to an un-suspended run rather than refusing to
        # launch at all if the environment doesn't support suspending
        # (SuspendNotSupported, a real exception in textual.app,
        # confirmed directly against the installed package) -- Textual
        # would otherwise fight Hyprland for the tty, but a broken
        # client launch is worse than a broken transition back to it.
        try:
            with self.suspend():
                return subprocess.run(list(cmd)).returncode
        except Exception:
            log(f"suspend failed ({cmd[0]}), running without it")
            return subprocess.run(list(cmd)).returncode

    def run_client(self, name: str, *cmd: str) -> None:
        log(f"selected {name}")
        self.set_status(f"Running {name}...")
        rc = self.run_suspended(*cmd)
        log(f"launch.sh exited {rc}")
        self.set_status("")
        self.refresh_menu()

    def action_select_configuration(self) -> None:
        self.run_client(
            "configuration", LAUNCH, "shell", "/usr/local/bin/vpinos-config.py"
        )

    def action_select_vpinball(self) -> None:
        self.run_client(
            "vpinball",
            LAUNCH,
            "vpinball",
            "/opt/vpinball/VPinballX_BGFX",
            "-play",
            "/opt/vpinball/assets/exampleTable.vpx",
        )

    def action_select_vpinfe(self) -> None:
        self.run_client("vpinfe", LAUNCH, "vpinfe", "/opt/vpinfe/vpinfe")

    def action_select_chrome_debug(self) -> None:
        # Not reachable from the menu right now (see refresh_menu) --
        # kept working so re-enabling is just uncommenting one line.
        self.run_client(
            "chrome debug",
            LAUNCH,
            "chrome",
            "/usr/bin/google-chrome",
            "--kiosk",
            "--enable-logging=stderr",
            "--vmodule=*ozone*=1,*wayland*=1",
            "about:blank",
        )

    def action_select_installer(self) -> None:
        self.run_client("calamares installer", "sudo", LAUNCH, "installer", "/usr/bin/calamares")

    def action_select_vpxconfig(self) -> None:
        self.run_vpxconfig()

    def action_select_boot_mode(self) -> None:
        if is_installed():
            self.push_screen(BootModeScreen(), callback=self.refresh_menu)

    def action_select_quit(self) -> None:
        self.action_quit_to_shell()

    def action_quit_to_shell(self) -> None:
        self.exit()

    def action_select_shutdown(self) -> None:
        def handle(confirmed: bool | None) -> None:
            if confirmed:
                log("selected shutdown, confirmed")
                subprocess.run(["sudo", "/usr/bin/systemctl", "poweroff"])
            else:
                log("selected shutdown, cancelled")

        self.push_screen(ConfirmScreen("Shut down now?"), callback=handle)

    # --- VPXConfig: local web server + browser, same lifecycle as the
    # old run_vpxconfig()/stop_vpxconfig() in vpinos-menu.sh ---
    def run_vpxconfig(self) -> None:
        port = VPXCONFIG_PORT
        if curl_ok(port):
            self.set_status(
                f"Something is already listening on 127.0.0.1:{port}. "
                "Stop it first (e.g. 'pkill vpxconfig') and try again."
            )
            log("vpxconfig: port already in use")
            return

        log(f"starting vpxconfig on 127.0.0.1:{port}")
        self.set_status("Starting VPXConfig...")
        with VPXCONFIG_LOG.open("a") as logf:
            proc = subprocess.Popen(
                ["/usr/bin/vpxconfig", "--host", "127.0.0.1", "--port", str(port)],
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
        self._vpxconfig_proc = proc

        # Up to ~30s: a bundled executable unpacks itself on first run.
        ready = False
        for _ in range(VPXCONFIG_STARTUP_TIMEOUT):
            if curl_ok(port):
                ready = True
                break
            if proc.poll() is not None:
                break
            time.sleep(1)

        if not ready:
            if proc.poll() is not None:
                self.set_status(f"VPXConfig exited during startup -- see {VPXCONFIG_LOG}")
                log("vpxconfig died during startup")
                self._vpxconfig_proc = None
            else:
                self.set_status(f"VPXConfig did not start listening within 30s -- see {VPXCONFIG_LOG}")
                log("vpxconfig did not start listening within 30s")
                self.stop_vpxconfig()
            return

        try:
            rc = self.run_suspended(
                LAUNCH,
                "vpxconfig",
                "/usr/bin/google-chrome",
                f"--app=http://127.0.0.1:{port}",
                "--start-maximized",
                "--no-first-run",
                "--disable-session-crashed-bubble",
                "--noerrdialogs",
            )
            log(f"launch.sh (vpxconfig browser) exited {rc}")
        finally:
            # finally, not just after: a suspended subprocess.run can
            # still raise (e.g. KeyboardInterrupt reaching this
            # process) -- the old shell version relied on an INT/TERM/
            # HUP trap for the same guarantee, this is that guarantee's
            # Python equivalent.
            self.stop_vpxconfig()
        self.set_status("")
        self.refresh_menu()

    def stop_vpxconfig(self) -> None:
        proc = self._vpxconfig_proc
        self._vpxconfig_proc = None
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        # vpxconfig is a single-file bundled executable that can leave
        # a child process behind; make sure nothing of ours is left
        # listening.
        subprocess.run(["pkill", "-u", str(os.getuid()), "-x", "vpxconfig"], check=False)
        log("vpxconfig stopped")


if __name__ == "__main__":
    VPinOSMenu().run()
