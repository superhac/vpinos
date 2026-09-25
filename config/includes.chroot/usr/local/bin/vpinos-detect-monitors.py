#!/usr/bin/env python3
# Phase one of monitor-mapping: enumerate connected outputs via hyprctl,
# print the hyprland.conf `workspace = N, monitor:NAME, default:true`
# lines that would pin one workspace to each, and show an on-screen
# identifier on each physical screen in turn so the cabinet builder can
# tell which output name is which monitor. Nothing here writes to
# hyprland.conf itself yet -- this only prints what those lines *would*
# be; wiring the result into the real config is a later phase.
#
# Run as a launch.sh "shell" client, same pattern as the debug terminal
# (`launch.sh shell /usr/bin/foot`) -- Hyprland needs to already be up
# with WAYLAND_DISPLAY set, which launch.sh's own launch_client() handles;
# this script doesn't start Hyprland itself:
#   /usr/local/bin/launch.sh shell /usr/local/bin/vpinos-detect-monitors.py
import glob
import json
import os
import subprocess
import sys
import time

IDENT_SECONDS = 8


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


def hyprctl_json(*args):
    proc = subprocess.run(
        ["hyprctl", "-j", *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "hyprctl failed"
        raise RuntimeError(detail)
    return json.loads(proc.stdout)


def get_monitors():
    return hyprctl_json("monitors")


def build_workspace_lines(monitors):
    # Ordered by Hyprland's own monitor ID (its connection/enumeration
    # order), not by screen position -- with only two or three outputs
    # there's no reliable geometric ordering (a portrait/landscape mix,
    # or displays not laid out left-to-right, would make x-position
    # ordering arbitrary anyway).
    ordered = sorted(monitors, key=lambda m: m["id"])
    return [
        f"workspace = {i}, monitor:{mon['name']}, default:true"
        for i, mon in enumerate(ordered, start=1)
    ]


def show_identifiers(monitors, seconds=IDENT_SECONDS):
    # First attempt used `moveworkspacetomonitor` + `[workspace N
    # silent]` on exec -- both wrong. `moveworkspacetomonitor` failed
    # outright ("Workspace not found") since the workspace doesn't exist
    # until something opens on it, and `silent` specifically means
    # *don't* switch the visible workspace -- confirmed directly: the
    # terminal opened, just never became visible, since silent is for
    # background auto-starts that shouldn't steal the screen, the
    # opposite of what an identifier needs. Fixed by focusing the
    # monitor and switching its active workspace directly instead, then
    # exec'ing onto the now-current workspace with no prefix at all.
    # hyprland.conf's own kiosk windowrule (`match:class = .*`,
    # `fullscreen = 1`) still forces it fullscreen on that output.
    for mon in monitors:
        name = mon["name"]
        ws_id = 900 + mon["id"]
        subprocess.run(["hyprctl", "dispatch", "focusmonitor", name], check=False)
        subprocess.run(["hyprctl", "dispatch", "workspace", str(ws_id)], check=False)
        label = mon.get("description", "")
        geometry = (
            f"{mon['width']}x{mon['height']}@{mon['refreshRate']:.2f}"
            f" at {mon['x']},{mon['y']}"
        )
        body = (
            "clear; printf '\\n\\n"
            f"   MONITOR: {name}\\n"
            f"   {label}\\n"
            f"   {geometry}\\n"
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
        time.sleep(seconds)


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
        print(
            f"      {mon['width']}x{mon['height']}"
            f"@{mon['refreshRate']:.2f} at {mon['x']},{mon['y']}"
        )

    print("\nProposed hyprland.conf workspace lines:\n")
    for line in build_workspace_lines(monitors):
        print(f"  {line}")

    print(f"\nShowing a {IDENT_SECONDS}s identifier on each monitor now, one at a time...")
    show_identifiers(monitors)
    print("Done.")


if __name__ == "__main__":
    main()
