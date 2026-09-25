#!/usr/bin/env python3
# Monitor-mapping tool: enumerate connected outputs via hyprctl, let the
# cabinet builder click SHOW next to a monitor to display its info
# fullscreen on the physical screen it actually is (so the output name
# can be matched to a real screen), pick a role (Table/Backglass/DMD)
# for each from a dropdown, and Save to write the
# `workspace = N, monitor:NAME, default:true` lines into hyprland.conf's
# vpinos-workspace-monitors block -- those lines, combined with the
# per-title windowrules already in hyprland.conf (which route
# vpinball's/vpinfe's own windows to workspace 1/2/3 by title), are what
# actually puts Table/Backglass/DMD on the right physical screen.
#
# Run as a launch.sh "shell" client, same pattern as the debug terminal
# (`launch.sh shell /usr/bin/foot`) -- Hyprland needs to already be up
# with WAYLAND_DISPLAY set, which launch.sh's own launch_client() handles;
# this script doesn't start Hyprland itself:
#   /usr/local/bin/launch.sh shell /usr/local/bin/vpinos-detect-monitors.py
#
# The menu itself is a real GUI (tkinter, via python3-tk) rather than a
# terminal menu -- runs over Xwayland (`xwayland { enabled = true }` is
# already on in hyprland.conf), so DISPLAY has to be discovered and set
# before any tkinter import touches a display, same idea as launch.sh's
# own installer-specific DISPLAY handling, just done here instead since
# launch.sh's generic "shell" client path only sets up Wayland.
import glob
import json
import os
import re
import subprocess
import sys
import time

IDENT_SECONDS = 8
MENU_WORKSPACE = 890
HYPRLAND_CONF = "/etc/vpinos/hyprland.conf"
BEGIN_MARKER = "# BEGIN vpinos-workspace-monitors"
END_MARKER = "# END vpinos-workspace-monitors"
# Fixed mapping, matches the per-title windowrules already in
# hyprland.conf (VPinFE Table/vpinball Player -> workspace 1, etc.) --
# not user-configurable, just which role goes on which workspace.
ROLE_WORKSPACE = {"Table": 1, "Backglass": 2, "DMD": 3}


def ensure_instance_signature():
    # hyprctl needs HYPRLAND_INSTANCE_SIGNATURE to find Hyprland's IPC
    # socket -- Hyprland sets this on its own process and on anything IT
    # execs (e.g. via `hyprctl dispatch exec`), but launch.sh's
    # launch_client() only knows generic Wayland (WAYLAND_DISPLAY), not
    # Hyprland specifically, and this script is a sibling of the `exec
    # Hyprland` line, not its child, so it never inherits it. Confirmed
    # directly: without this, hyprctl just fails with no monitors data.
    # Only one Hyprland instance ever runs at a time in this project's
    # architecture, so the single entry under .../hypr/ is always the
    # right one.
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    matches = glob.glob(os.path.join(runtime_dir, "hypr", "*", ".socket.sock"))
    if not matches:
        return
    signature = os.path.basename(os.path.dirname(matches[0]))
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = signature


def ensure_display(timeout=15):
    # tkinter (Tcl/Tk) has no native Wayland backend in trixie's version
    # -- it always needs an X11 DISPLAY, served here by Hyprland's own
    # Xwayland. Same socket-glob-and-wait pattern as launch.sh's
    # wait_for_glob for the installer's DISPLAY, reimplemented here since
    # launch.sh's "shell" client path never sets DISPLAY at all (only
    # WAYLAND_DISPLAY -- it's meant to be Wayland-client-generic).
    if os.environ.get("DISPLAY"):
        return
    deadline = time.time() + timeout
    sock = None
    while time.time() < deadline:
        matches = glob.glob("/tmp/.X11-unix/X*")
        if matches:
            sock = matches[0]
            break
        time.sleep(0.2)
    if not sock:
        raise RuntimeError("timed out waiting for Xwayland's X11 socket")
    os.environ["DISPLAY"] = ":" + os.path.basename(sock)[1:]


def hyprctl_json(*args):
    proc = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "hyprctl failed"
        raise RuntimeError(detail)
    return json.loads(proc.stdout)


def hyprctl(*args):
    subprocess.run(["hyprctl", *args], capture_output=True, text=True, check=False)


def get_monitors():
    return hyprctl_json("monitors")


def geometry_of(mon):
    return f"{mon['width']}x{mon['height']}@{mon['refreshRate']:.2f} at {mon['x']},{mon['y']}"


def switch_to(monitor_name, workspace_id):
    hyprctl("dispatch", "focusmonitor", monitor_name)
    hyprctl("dispatch", "workspace", str(workspace_id))


def show_monitor(mon, seconds, on_done):
    # Switches the target monitor to its own scratch workspace (hiding
    # whatever's on it -- for the menu's own monitor, that's the menu
    # itself, which is what makes it disappear while the identifier is
    # up) and execs a fullscreen `foot` there for `seconds`, then calls
    # `on_done` -- the caller is responsible for switching back
    # afterward, since only it knows where the menu itself lives.
    name = mon["name"]
    ws_id = 900 + mon["id"]
    switch_to(name, ws_id)
    body = (
        "clear; printf '\\n\\n"
        f"   MONITOR: {name}\\n"
        f"   {mon.get('description', '')}\\n"
        f"   {geometry_of(mon)}\\n\\n"
        f"   Closing in {seconds} seconds...\\n"
        "'; "
        f"sleep {seconds}"
    )
    subprocess.Popen(
        [
            "hyprctl",
            "dispatch",
            "exec",
            f'foot -T vpinos-ident-{name} -e sh -c "{body}"',
        ]
    )
    on_done(seconds)


def build_workspace_lines(role_to_monitor):
    # `default:true` marks which workspace a monitor starts on --
    # only workspace 1 (Table) should carry it, per request; workspaces
    # 2/3 (Backglass/DMD) are only ever reached via the per-title
    # windowrules' own `workspace = N silent`, never a fresh startup
    # default.
    lines = []
    for role, ws in sorted(ROLE_WORKSPACE.items(), key=lambda kv: kv[1]):
        name = role_to_monitor.get(role)
        if name:
            suffix = ", default:true" if ws == 1 else ""
            lines.append(f"workspace = {ws}, monitor:{name}{suffix}")
    return lines


def parse_existing_roles():
    # Pre-fills each monitor's dropdown from whatever's already saved in
    # hyprland.conf, so reopening this tool doesn't lose a prior choice.
    try:
        with open(HYPRLAND_CONF) as f:
            content = f.read()
    except OSError:
        return {}
    start = content.find(BEGIN_MARKER)
    end = content.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        return {}
    body = content[start + len(BEGIN_MARKER) : end]
    ws_to_role = {ws: role for role, ws in ROLE_WORKSPACE.items()}
    result = {}
    for line in body.splitlines():
        m = re.match(r"\s*workspace\s*=\s*(\d+)\s*,\s*monitor:([^\s,]+)", line)
        if not m:
            continue
        role = ws_to_role.get(int(m.group(1)))
        if role:
            result[m.group(2)] = role
    return result


def save_workspace_lines(lines):
    with open(HYPRLAND_CONF) as f:
        content = f.read()
    start = content.find(BEGIN_MARKER)
    end = content.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise RuntimeError(
            f"couldn't find the {BEGIN_MARKER} / {END_MARKER} markers in {HYPRLAND_CONF}"
        )
    start_of_body = start + len(BEGIN_MARKER)
    body = "\n" + ("\n".join(lines) + "\n" if lines else "")
    new_content = content[:start_of_body] + body + content[end:]
    with open(HYPRLAND_CONF, "w") as f:
        f.write(new_content)


def run_gui(monitors):
    import tkinter as tk
    from tkinter import ttk

    ordered = sorted(monitors, key=lambda m: m["id"])
    menu_monitor = ordered[0]["name"]
    switch_to(menu_monitor, MENU_WORKSPACE)
    existing_roles = parse_existing_roles()

    root = tk.Tk()
    root.title("VPinOS -- Monitor Detection")
    root.configure(bg="black")
    root.attributes("-fullscreen", True)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TLabel", background="black", foreground="white", font=("sans", 16))
    style.configure("Header.TLabel", background="black", foreground="white", font=("sans", 20, "bold"))
    style.configure("TButton", font=("sans", 16, "bold"), padding=10)
    style.configure("TRadiobutton", background="black", foreground="white", font=("sans", 14))
    style.map("TRadiobutton", background=[("active", "black")])

    header = ttk.Label(
        root,
        text="Detected monitors -- SHOW to identify, then select a role for each",
        style="Header.TLabel",
    )
    header.pack(pady=30)

    table = tk.Frame(root, bg="black")
    table.pack(pady=20)

    show_buttons = []
    role_vars = []

    def on_show(mon):
        for b in show_buttons:
            b.configure(state="disabled")
        show_monitor(
            mon,
            IDENT_SECONDS,
            lambda seconds: root.after(seconds * 1000, on_return),
        )

    def on_return():
        switch_to(menu_monitor, MENU_WORKSPACE)
        for b in show_buttons:
            b.configure(state="normal")

    for row, mon in enumerate(ordered):
        text = f"{mon['name']}   {mon.get('description', '')}   {geometry_of(mon)}"
        ttk.Label(table, text=text, style="TLabel").grid(row=row, column=0, sticky="w", pady=8, padx=(0, 30))

        btn = ttk.Button(table, text="SHOW")
        btn.grid(row=row, column=1, pady=8, padx=(0, 30))
        btn.configure(command=lambda m=mon: on_show(m))
        show_buttons.append(btn)

        # Radio buttons, not a dropdown: a ttk.Combobox's dropdown list
        # is its own separate top-level (popup) window -- confirmed
        # directly on a real boot that hyprland.conf's kiosk catch-all
        # windowrule (`match:class = .*`, `fullscreen = 1`) forces that
        # popup fullscreen too, same as any other window, making it
        # flash white/fullscreen instead of dropping down normally.
        # Radio buttons are just widgets drawn inside this same window,
        # never a separate one, so there's nothing extra for the
        # catch-all to catch.
        role_var = tk.StringVar(value=existing_roles.get(mon["name"], ""))
        radios = tk.Frame(table, bg="black")
        radios.grid(row=row, column=2, pady=8, sticky="w")
        for col, role in enumerate(ROLE_WORKSPACE.keys()):
            ttk.Radiobutton(
                radios, text=role, value=role, variable=role_var, style="TRadiobutton"
            ).grid(row=0, column=col, padx=6)
        role_vars.append((mon, role_var))

    status = ttk.Label(root, text="", style="TLabel")
    status.pack(pady=(10, 0))

    def on_save():
        role_to_monitor = {}
        conflicts = set()
        for mon, role_var in role_vars:
            role = role_var.get()
            if not role:
                continue
            if role in role_to_monitor:
                conflicts.add(role)
            role_to_monitor[role] = mon["name"]

        if conflicts:
            status.configure(
                text=f"ERROR: {', '.join(sorted(conflicts))} assigned to more than one monitor.",
                foreground="red",
            )
            return

        lines = build_workspace_lines(role_to_monitor)
        try:
            save_workspace_lines(lines)
        except OSError as exc:
            status.configure(text=f"ERROR saving hyprland.conf: {exc}", foreground="red")
            return
        except RuntimeError as exc:
            status.configure(text=f"ERROR: {exc}", foreground="red")
            return

        hyprctl("reload")
        status.configure(text="Saved to hyprland.conf and applied.", foreground="#7CFC00")

    button_row = tk.Frame(root, bg="black")
    button_row.pack(pady=20)
    ttk.Button(button_row, text="Save", command=on_save).grid(row=0, column=0, padx=10)
    ttk.Button(button_row, text="Quit", command=root.destroy).grid(row=0, column=1, padx=10)
    root.bind("<Escape>", lambda e: root.destroy())

    root.mainloop()


def main():
    ensure_instance_signature()
    try:
        monitors = get_monitors()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "Is Hyprland running? Run this via:\n"
            "  /usr/local/bin/launch.sh shell /usr/local/bin/vpinos-detect-monitors.py",
            file=sys.stderr,
        )
        sys.exit(1)

    if not monitors:
        print("hyprctl reported zero monitors.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(monitors)} monitor(s):\n")
    for mon in sorted(monitors, key=lambda m: m["id"]):
        print(f"  {mon['name']} (ID {mon['id']}): {mon.get('description', '?')}")
        print(f"      {geometry_of(mon)}")

    try:
        ensure_display()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nOpening the monitor menu...")
    run_gui(monitors)
    print("Done.")


if __name__ == "__main__":
    main()
