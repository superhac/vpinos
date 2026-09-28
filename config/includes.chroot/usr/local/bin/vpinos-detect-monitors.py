#!/usr/bin/env python3
# Monitor-mapping tool: enumerate connected outputs via hyprctl, let the
# cabinet builder click SHOW next to a monitor to display its info
# fullscreen on the physical screen it actually is (so the output name
# can be matched to a real screen), pick a role (Table/Backglass/DMD)
# for each, and Save to write the
# `workspace = N, monitor:NAME, default:true` lines into hyprland.conf's
# vpinos-workspace-monitors block -- those lines, combined with the
# per-title windowrules already in hyprland.conf (which route
# vpinball's/vpinfe's own windows to workspace 1/2/3 by title), are what
# actually puts Table/Backglass/DMD on the right physical screen. Also
# has a last "VPinball Mode" option (Desktop/Cabinet) that Save writes
# straight into vpinball's own VPinballX.ini (BGSet, plus
# BackglassOutput/ScoreViewOutput based on which roles got assigned).
# With more than one monitor, Save also writes vpinfe's own
# tablescreenid/bgscreenid/dmdscreenid in vpinfe.ini to each role's
# monitor ID. Selecting Cabinet mode reveals three more sections
# (CabinetAutofitMode; a Full DMD on/off checkbox for
# ScoreViewDMDOverlay/ScoreViewDMDAutoPos/B2SHideGrill; and
# ScreenWidth/ScreenHeight/ScreenInclination), all written to
# VPinballX.ini -- hidden entirely in Desktop mode, since VPinballX.ini's
# own comments say they only matter in Cabinet mode. Save also always
# sets Priority.ScoreView/PUP/B2SLegacyDMD to fixed values, regardless
# of mode or role assignment.
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

VPX_BINARY = "/opt/vpinball/VPinballX_BGFX"
VPX_INI_PATH = os.path.expanduser("~/.local/share/VPinballX/10.8/VPinballX.ini")

# Cabinet-only extras (only meaningful once VPinball Mode = Cabinet --
# see VPinballX.ini's own comments): value, display name, description.
CABINET_AUTOFIT_OPTIONS = [
    (
        "0",
        "Manual",
        "No automatic fitting -- the table keeps its default view/camera position.",
    ),
    (
        "1",
        "Fit Table",
        "Sizes the table to fill the width of your screen while keeping its true "
        "proportions. Parts of the apron or the top of the playfield may be cut "
        'off, and the flippers are placed at the height set by "Autofit Pos".',
    ),
    (
        "2",
        "Fit Screen",
        "Stretches the table lengthwise so the whole thing fills your screen with "
        "nothing cut off. The stretching makes round objects like the ball and "
        "bumpers look slightly oval.",
    ),
]

# key, display name, description -- Autofit needs these; VPinball itself
# logs an error and does nothing if ScreenWidth/ScreenHeight are <= 1,
# rather than something this tool needs to re-validate.
SCREEN_DIMENSION_FIELDS = [
    (
        "ScreenWidth",
        "Screen Width (cm)",
        "The physical width, in cm, of the visible picture on your playfield "
        "screen. Always measure the long side, even if the monitor lies sideways "
        "in your cabinet. VPX uses it with Screen Height to size the table "
        "correctly on your screen.",
    ),
    (
        "ScreenHeight",
        "Screen Height (cm)",
        "The physical height, in cm, of the visible picture on your playfield "
        "screen. Always measure the short side. Measure only the lit display "
        "area, not the bezel.",
    ),
    (
        "ScreenInclination",
        "Screen Inclination (degrees)",
        "How far, in degrees, your playfield screen is tilted from flat. 0 means "
        "perfectly level, and positive values mean the back end, toward the "
        "backbox, is raised. VPX uses it to correct the 3D perspective so the "
        "table looks right from where you stand.",
    ),
]

# Single on/off toggle (Cabinet mode only) -- checked writes all three
# keys as 1, unchecked writes all three as 0 (both states explicit, same
# as BGSet/BackglassOutput/ScoreViewOutput above, so unchecking it after
# a previous save actually takes effect instead of leaving stale 1s).
# Description inferred from the key names, not supplied -- overlays the
# DMD content onto the backglass with automatic positioning, and hides
# the backglass image's own printed DMD grill graphic (for a real
# physical DMD/no separate DMD window, rather than a 3-screen setup).
FULLDMD_KEYS = ["ScoreViewDMDOverlay", "ScoreViewDMDAutoPos", "B2SHideGrill"]
FULLDMD_DESCRIPTION = (
    "Overlays the DMD content directly onto the backglass image with automatic "
    "positioning, and hides the backglass image's own printed DMD grill graphic "
    "-- for a real physical DMD device, not a separate DMD monitor/window."
)

VPINFE_INI_PATH = os.path.expanduser("~/.config/vpinfe/vpinfe.ini")
VPINFE_INI_KEY = {"Table": "tablescreenid", "Backglass": "bgscreenid", "DMD": "dmdscreenid"}


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


def ensure_vpinballx_ini():
    # First run (or a freshly-installed cabinet) has no ini yet --
    # vpinball only writes its defaults out on its own, so there's
    # nothing to edit until it's been run at least once. `-h` (just
    # prints help and exits) is enough to trigger that write without
    # actually opening a table or a window.
    if os.path.exists(VPX_INI_PATH):
        return
    os.makedirs(os.path.dirname(VPX_INI_PATH), exist_ok=True)
    subprocess.run([VPX_BINARY, "-h"], capture_output=True, text=True, check=False)
    if not os.path.exists(VPX_INI_PATH):
        raise RuntimeError(f"{VPX_INI_PATH} still missing after running {VPX_BINARY} -h")


def set_ini_value(content, key, value):
    # Plain text substitution, not configparser -- vpinball's own ini
    # has many sections and configparser would need to know which one
    # each key lives in (and risks reshuffling/dropping comments on a
    # rewrite). vpinball generates the file itself via `-h` first (see
    # ensure_vpinballx_ini), so these keys already exist with their
    # defaults by the time this runs -- a straight in-place replace of
    # the existing line, keyed off the exact key name.
    pattern = re.compile(rf"^([ \t]*{re.escape(key)}[ \t]*=[ \t]*).*$", re.IGNORECASE | re.MULTILINE)
    new_content, count = pattern.subn(rf"\g<1>{value}", content, count=1)
    if count == 0:
        sep = "" if not content or content.endswith("\n") else "\n"
        new_content = f"{content}{sep}{key} = {value}\n"
    return new_content


def parse_existing_vpinball_mode():
    # Pre-fills the Desktop/Cabinet radio buttons from whatever's
    # already in VPinballX.ini, same idea as parse_existing_roles()
    # above -- reopening the tool shouldn't lose a prior choice.
    try:
        with open(VPX_INI_PATH) as f:
            content = f.read()
    except OSError:
        return "Desktop"
    m = re.search(r"^[ \t]*BGSet[ \t]*=[ \t]*(\d+)", content, re.IGNORECASE | re.MULTILINE)
    return "Cabinet" if m and m.group(1).strip() == "1" else "Desktop"


def parse_existing_cabinet_autofit_mode():
    try:
        with open(VPX_INI_PATH) as f:
            content = f.read()
    except OSError:
        return "0"
    m = re.search(r"^[ \t]*CabinetAutofitMode[ \t]*=[ \t]*(\d+)", content, re.IGNORECASE | re.MULTILINE)
    value = m.group(1) if m else "0"
    return value if value in ("0", "1", "2") else "0"


def parse_existing_screen_field(key):
    try:
        with open(VPX_INI_PATH) as f:
            content = f.read()
    except OSError:
        return ""
    m = re.search(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(\S*)", content, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else ""


def parse_existing_fulldmd():
    # "On" only if every key is already 1 -- a partial/mixed state (e.g.
    # hand-edited) is treated as off, not guessed at.
    try:
        with open(VPX_INI_PATH) as f:
            content = f.read()
    except OSError:
        return False
    for key in FULLDMD_KEYS:
        m = re.search(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(\d+)", content, re.IGNORECASE | re.MULTILINE)
        if not m or m.group(1).strip() != "1":
            return False
    return True


def save_vpinball_settings(
    mode, role_to_monitor, cabinet_autofit_mode=None, screen_fields=None, fulldmd=None
):
    ensure_vpinballx_ini()
    with open(VPX_INI_PATH) as f:
        content = f.read()
    content = set_ini_value(content, "BGSet", 1 if mode == "Cabinet" else 0)
    content = set_ini_value(content, "BackglassOutput", 1 if "Backglass" in role_to_monitor else 0)
    content = set_ini_value(content, "ScoreViewOutput", 1 if "DMD" in role_to_monitor else 0)
    # Fixed defaults every cabinet should have, regardless of
    # Desktop/Cabinet mode or which roles are assigned -- requested
    # directly, not derived from any other setting here.
    content = set_ini_value(content, "Priority.ScoreView", 1)
    content = set_ini_value(content, "Priority.PUP", 3)
    content = set_ini_value(content, "Priority.B2SLegacyDMD", 2)
    # Cabinet-only extras -- left untouched entirely in Desktop mode
    # rather than overwritten with blank/default values, since they
    # only matter once Cabinet mode is actually selected.
    if mode == "Cabinet":
        if cabinet_autofit_mode is not None:
            content = set_ini_value(content, "CabinetAutofitMode", cabinet_autofit_mode)
        for key, value in (screen_fields or {}).items():
            value = value.strip()
            if value:
                content = set_ini_value(content, key, value)
        if fulldmd is not None:
            for key in FULLDMD_KEYS:
                content = set_ini_value(content, key, 1 if fulldmd else 0)
    with open(VPX_INI_PATH, "w") as f:
        f.write(content)


def save_vpinfe_settings(role_to_monitor, id_by_monitor):
    # Only called with more than one monitor detected -- with a single
    # screen everything already renders there regardless of these ids,
    # so there's nothing meaningful to set. vpinfe.ini ships baked into
    # the image (home/vpinos/.config/vpinfe/), so unlike VPinballX.ini
    # there's no "generate a default first" step -- if it's missing,
    # that's a real problem worth surfacing, not something to paper
    # over by writing a fresh file with unknown other defaults missing.
    if not os.path.exists(VPINFE_INI_PATH):
        raise RuntimeError(f"{VPINFE_INI_PATH} not found")
    with open(VPINFE_INI_PATH) as f:
        content = f.read()
    for role, key in VPINFE_INI_KEY.items():
        name = role_to_monitor.get(role)
        if name:
            content = set_ini_value(content, key, id_by_monitor[name])
    with open(VPINFE_INI_PATH, "w") as f:
        f.write(content)



# Dark, card-based palette -- deliberately not the default ttk "clam"
# look (flat gray buttons/labels on plain black), which is what made
# the first version of this screen look bare. Plain colors/fonts only
# (no images, no rounded corners) since ttk's "clam" theme is what's
# actually available here, no extra theme package installed.
BG = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#2f81f7"
ACCENT_HOVER = "#4c94ff"
SUCCESS = "#238636"
SUCCESS_HOVER = "#2ea043"
NEUTRAL = "#30363d"
NEUTRAL_HOVER = "#3d444d"


def run_gui(monitors):
    import tkinter as tk
    from tkinter import ttk

    ordered = sorted(monitors, key=lambda m: m["id"])
    menu_monitor = ordered[0]["name"]
    switch_to(menu_monitor, MENU_WORKSPACE)
    existing_roles = parse_existing_roles()

    root = tk.Tk()
    root.title("VPinOS -- Monitor Detection")
    root.configure(bg=BG)
    root.attributes("-fullscreen", True)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TLabel", background=BG, foreground=TEXT, font=("sans", 14))
    style.configure("Header.TLabel", background=BG, foreground=TEXT, font=("sans", 24, "bold"))
    style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("sans", 12))
    style.configure("Section.TLabel", background=BG, foreground=TEXT, font=("sans", 15, "bold"))
    style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT, font=("sans", 14))

    style.configure("TButton", font=("sans", 14, "bold"), padding=(16, 10), relief="flat", borderwidth=0)
    style.configure("Show.TButton", background=ACCENT, foreground="white")
    style.map(
        "Show.TButton",
        background=[("disabled", BORDER), ("active", ACCENT_HOVER)],
        foreground=[("disabled", MUTED)],
    )
    style.configure("Save.TButton", background=SUCCESS, foreground="white", padding=(24, 12))
    style.map("Save.TButton", background=[("active", SUCCESS_HOVER)])
    style.configure("Quit.TButton", background=NEUTRAL, foreground=TEXT, padding=(24, 12))
    style.map("Quit.TButton", background=[("active", NEUTRAL_HOVER)])

    style.configure("TRadiobutton", background=CARD_BG, foreground=TEXT, font=("sans", 13))
    style.map(
        "TRadiobutton",
        background=[("active", CARD_BG)],
        indicatorcolor=[("selected", ACCENT), ("!selected", BORDER)],
    )
    style.configure("Mode.TRadiobutton", background=BG, foreground=TEXT, font=("sans", 13))
    style.map(
        "Mode.TRadiobutton",
        background=[("active", BG)],
        indicatorcolor=[("selected", ACCENT), ("!selected", BORDER)],
    )
    style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT, font=("sans", 13))
    style.map(
        "TCheckbutton",
        background=[("active", CARD_BG)],
        indicatorcolor=[("selected", ACCENT), ("!selected", BORDER)],
    )

    # Scrollable body: Cabinet mode's extra sections can push the total
    # content taller than the screen, and this is a fixed-size fullscreen
    # window with no window chrome to resize -- confirmed directly, the
    # bottom (Screen Dimensions, Save/Quit) just ran off the bottom of a
    # real 1280x800 screen with no way to reach it at all. A Canvas +
    # Scrollbar is the standard Tk way to make an arbitrarily-tall body
    # scrollable; everything below is parented to `scroll_frame` (inside
    # the canvas), not `root`, directly.
    outer = tk.Frame(root, bg=BG)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    scroll_frame = tk.Frame(canvas, bg=BG)
    scroll_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

    def _on_scroll_frame_configure(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event):
        # Keeps scroll_frame's contents centered and as wide as the
        # canvas itself, rather than a fixed/guessed width.
        canvas.itemconfig(scroll_window, width=event.width)

    scroll_frame.bind("<Configure>", _on_scroll_frame_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event):
        if event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(-1, "units")

    # Button-4/-5 (X11/Xwayland scroll-wheel events) and MouseWheel
    # (harmless if never fired here) both bound -- whichever a real
    # mouse or trackball sends, plus the scrollbar itself works for a
    # touchscreen with no wheel at all.
    canvas.bind_all("<Button-4>", _on_mousewheel)
    canvas.bind_all("<Button-5>", _on_mousewheel)
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    root_ = scroll_frame

    ttk.Label(root_, text="VPinOS Monitor Setup", style="Header.TLabel").pack(pady=(36, 4))
    ttk.Label(
        root_,
        text="Press SHOW to identify a screen, then select its role.",
        style="Sub.TLabel",
    ).pack(pady=(0, 28))

    # One grid for the header row AND every monitor row, not a separate
    # header Frame with guessed padx offsets -- confirmed directly that
    # guessed offsets don't track each row's actual (content-dependent)
    # widths, so the header drifted out of alignment with the cards
    # below it. A single shared grid with fixed column minsizes is what
    # actually keeps them lined up regardless of content width.
    content = tk.Frame(root_, bg=BG)
    content.pack(padx=60)
    content.grid_columnconfigure(0, minsize=460, weight=1)
    content.grid_columnconfigure(1, minsize=190)
    content.grid_columnconfigure(2, minsize=300)

    ttk.Label(content, text="MONITOR", style="Sub.TLabel").grid(
        row=0, column=0, sticky="w", padx=(18, 0), pady=(0, 8)
    )
    ttk.Label(content, text="IDENTIFY", style="Sub.TLabel").grid(
        row=0, column=1, sticky="w", padx=(18, 0), pady=(0, 8)
    )
    ttk.Label(content, text="ROLE", style="Sub.TLabel").grid(
        row=0, column=2, sticky="w", padx=(18, 0), pady=(0, 8)
    )

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

    for i, mon in enumerate(ordered):
        r = i + 1
        cell_kwargs = {"bg": CARD_BG, "highlightbackground": BORDER, "highlightthickness": 1}

        info_cell = tk.Frame(content, **cell_kwargs)
        info_cell.grid(row=r, column=0, sticky="nsew", pady=4)
        info = tk.Frame(info_cell, bg=CARD_BG)
        info.pack(anchor="w", padx=18, pady=16)
        name_row = tk.Frame(info, bg=CARD_BG)
        name_row.pack(anchor="w")
        tk.Label(name_row, text=mon["name"], bg=CARD_BG, fg=TEXT, font=("sans", 17, "bold")).pack(side="left")
        tk.Label(
            name_row, text=f"  (ID {mon['id']})", bg=CARD_BG, fg=MUTED, font=("sans", 12)
        ).pack(side="left")
        sub = f"{mon.get('description', '')}   |   {geometry_of(mon)}"
        tk.Label(info, text=sub, bg=CARD_BG, fg=MUTED, font=("sans", 11)).pack(anchor="w", pady=(2, 0))

        show_cell = tk.Frame(content, **cell_kwargs)
        show_cell.grid(row=r, column=1, sticky="nsew", pady=4)
        btn = ttk.Button(show_cell, text="SHOW", style="Show.TButton")
        btn.pack(padx=18, pady=16, anchor="w")
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
        role_cell = tk.Frame(content, **cell_kwargs)
        role_cell.grid(row=r, column=2, sticky="nsew", pady=4)
        role_var = tk.StringVar(value=existing_roles.get(mon["name"], ""))
        radios = tk.Frame(role_cell, bg=CARD_BG)
        radios.pack(padx=12, pady=16, anchor="w")
        for col, role in enumerate(ROLE_WORKSPACE.keys()):
            ttk.Radiobutton(
                radios, text=role, value=role, variable=role_var, style="TRadiobutton"
            ).grid(row=0, column=col, padx=8)
        role_vars.append((mon, role_var))

    # Last option, below the displays -- Desktop/Cabinet mode
    # (VPinballX.ini's `BGSet`), plus which of the assigned roles above
    # actually get their own separate vpinball window
    # (`BackglassOutput`/`ScoreViewOutput` -- only meaningful once
    # there's a Backglass/DMD monitor to put them on).
    # Parented to `root`, not `content` -- `content` is a pure grid
    # container now (see the row-alignment fix above), and Tk refuses
    # to mix `pack` and `grid` on children of the same parent
    # ("cannot use geometry manager pack inside ... which already has
    # slaves managed by grid"), confirmed directly by a real crash.
    mode_card = tk.Frame(root_, bg=BG)
    mode_card.pack(pady=(24, 0))
    ttk.Label(mode_card, text="VPinball Mode", style="Section.TLabel").pack(anchor="center")
    mode_frame = tk.Frame(mode_card, bg=BG)
    mode_frame.pack(anchor="center", pady=(8, 0))
    vpinball_mode_var = tk.StringVar(value=parse_existing_vpinball_mode())
    for col, mode in enumerate(("Desktop", "Cabinet")):
        ttk.Radiobutton(
            mode_frame, text=mode, value=mode, variable=vpinball_mode_var, style="Mode.TRadiobutton"
        ).grid(row=0, column=col, padx=(0, 24))

    # Cabinet-only extras -- only meaningful once VPinball Mode =
    # Cabinet (see VPinballX.ini's own comments), so hidden entirely
    # otherwise rather than shown but grayed out. Toggled via a trace on
    # vpinball_mode_var; `before=status` on every re-show since
    # pack_forget() followed by a bare pack() would otherwise just
    # append it after whatever's currently last (status/button_row),
    # losing its position between the mode picker and the status line.
    DESC_WRAP = 760
    cabinet_extra = tk.Frame(root_, bg=BG)

    ttk.Label(cabinet_extra, text="Cabinet Autofit Mode", style="Section.TLabel").pack(
        anchor="w", padx=18, pady=(0, 8)
    )
    cabinet_autofit_var = tk.StringVar(value=parse_existing_cabinet_autofit_mode())
    for value, name, desc in CABINET_AUTOFIT_OPTIONS:
        row = tk.Frame(cabinet_extra, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", pady=4)
        ttk.Radiobutton(
            row, value=value, variable=cabinet_autofit_var, style="TRadiobutton"
        ).pack(side="left", padx=(18, 12), pady=16, anchor="n")
        text_col = tk.Frame(row, bg=CARD_BG)
        text_col.pack(side="left", padx=(0, 18), pady=16, fill="x", expand=True)
        tk.Label(text_col, text=name, bg=CARD_BG, fg=TEXT, font=("sans", 15, "bold")).pack(anchor="w")
        tk.Label(
            text_col, text=desc, bg=CARD_BG, fg=MUTED, font=("sans", 11),
            wraplength=DESC_WRAP, justify="left",
        ).pack(anchor="w", pady=(2, 0))

    ttk.Label(cabinet_extra, text="Full DMD", style="Section.TLabel").pack(
        anchor="w", padx=18, pady=(20, 8)
    )
    fulldmd_row = tk.Frame(cabinet_extra, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
    fulldmd_row.pack(fill="x", pady=4)
    fulldmd_var = tk.BooleanVar(value=parse_existing_fulldmd())
    ttk.Checkbutton(
        fulldmd_row, variable=fulldmd_var, style="TCheckbutton"
    ).pack(side="left", padx=(18, 12), pady=16, anchor="n")
    fulldmd_text_col = tk.Frame(fulldmd_row, bg=CARD_BG)
    fulldmd_text_col.pack(side="left", padx=(0, 18), pady=16, fill="x", expand=True)
    tk.Label(fulldmd_text_col, text="Full DMD", bg=CARD_BG, fg=TEXT, font=("sans", 15, "bold")).pack(
        anchor="w"
    )
    tk.Label(
        fulldmd_text_col, text=FULLDMD_DESCRIPTION, bg=CARD_BG, fg=MUTED, font=("sans", 11),
        wraplength=DESC_WRAP, justify="left",
    ).pack(anchor="w", pady=(2, 0))

    ttk.Label(cabinet_extra, text="Screen Dimensions", style="Section.TLabel").pack(
        anchor="w", padx=18, pady=(20, 2)
    )
    ttk.Label(
        cabinet_extra,
        text='Needed for Autofit ("Fit Table"/"Fit Screen") -- Manual mode ignores these.',
        style="Sub.TLabel",
    ).pack(anchor="w", padx=18, pady=(0, 8))
    screen_field_vars = {}
    for key, name, desc in SCREEN_DIMENSION_FIELDS:
        row = tk.Frame(cabinet_extra, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", pady=4)
        text_col = tk.Frame(row, bg=CARD_BG)
        text_col.pack(side="left", padx=18, pady=16, fill="x", expand=True)
        tk.Label(text_col, text=name, bg=CARD_BG, fg=TEXT, font=("sans", 15, "bold")).pack(anchor="w")
        tk.Label(
            text_col, text=desc, bg=CARD_BG, fg=MUTED, font=("sans", 11),
            wraplength=DESC_WRAP, justify="left",
        ).pack(anchor="w", pady=(2, 0))
        field_var = tk.StringVar(value=parse_existing_screen_field(key))
        entry = tk.Entry(
            row, textvariable=field_var, width=8, bg=BG, fg=TEXT,
            insertbackground=TEXT, relief="flat", highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT, font=("sans", 14),
        )
        entry.pack(side="left", padx=(0, 18))
        screen_field_vars[key] = field_var

    status = ttk.Label(root_, text="", style="TLabel")
    status.pack(pady=(24, 0))

    def on_mode_change(*_args):
        if vpinball_mode_var.get() == "Cabinet":
            cabinet_extra.pack(fill="x", padx=60, pady=(20, 0), before=status)
        else:
            cabinet_extra.pack_forget()

    vpinball_mode_var.trace_add("write", on_mode_change)
    on_mode_change()

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
                foreground="#f85149",
            )
            return

        lines = build_workspace_lines(role_to_monitor)
        try:
            save_workspace_lines(lines)
        except OSError as exc:
            status.configure(text=f"ERROR saving hyprland.conf: {exc}", foreground="#f85149")
            return
        except RuntimeError as exc:
            status.configure(text=f"ERROR: {exc}", foreground="#f85149")
            return

        try:
            save_vpinball_settings(
                vpinball_mode_var.get(),
                role_to_monitor,
                cabinet_autofit_mode=cabinet_autofit_var.get(),
                screen_fields={key: var.get() for key, var in screen_field_vars.items()},
                fulldmd=fulldmd_var.get(),
            )
        except (OSError, RuntimeError) as exc:
            status.configure(
                text=f"Saved hyprland.conf, but ERROR saving VPinballX.ini: {exc}",
                foreground="#f85149",
            )
            return

        saved = "hyprland.conf and VPinballX.ini"
        if len(ordered) > 1:
            id_by_monitor = {mon["name"]: mon["id"] for mon in ordered}
            try:
                save_vpinfe_settings(role_to_monitor, id_by_monitor)
                saved += " and vpinfe.ini"
            except (OSError, RuntimeError) as exc:
                status.configure(
                    text=f"Saved {saved}, but ERROR saving vpinfe.ini: {exc}",
                    foreground="#f85149",
                )
                return

        hyprctl("reload")
        status.configure(text=f"Saved to {saved}, applied.", foreground=SUCCESS_HOVER)

    button_row = tk.Frame(root_, bg=BG)
    button_row.pack(pady=(8, 30))
    ttk.Button(button_row, text="Save", style="Save.TButton", command=on_save).grid(row=0, column=0, padx=10)
    ttk.Button(button_row, text="Quit", style="Quit.TButton", command=root.destroy).grid(row=0, column=1, padx=10)
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
