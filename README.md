<p align="center">
  <img src="config/includes.chroot/etc/calamares/branding/vpinos/logo.png" alt="VPinOS" width="260">
</p>

<h1 align="center">VPinOS</h1>

<p align="center">
  A minimal, appliance-style Linux for virtual pinball cabinets.<br>
  Boots fast, brings up a GPU-accelerated display, and launches
  <a href="https://github.com/vpinball/vpinball">Visual Pinball</a> and the
  <strong>vpinfe</strong> frontend &mdash; and nothing else.
</p>

<p align="center">
  <a href="../../actions/workflows/build-iso.yml"><img src="../../actions/workflows/build-iso.yml/badge.svg" alt="Build VPinOS ISO"></a>
  <a href="../../releases"><img src="https://img.shields.io/badge/download-latest%20release-4aa8ff" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
</p>

<p align="center">
  <a href="https://youtu.be/APbAikFzutk"><strong>Watch the video on YouTube</strong></a>
</p>

> [!WARNING]
> **VPinOS is in beta.** It works end to end (boot, launch, install), but it
> is under active development: expect rough edges, breaking changes between
> releases, and features that are still placeholders (the console menu, for
> one). Don't rely on it for anything you can't reinstall, keep backups of
> your tables and settings, and please
> [report problems](../../issues).

---

## What it is

VPinOS is a custom Debian 13 (trixie) image, built with
[live-build](https://live-team.pages.debian.net/live-manual/), that ships as
a single hybrid ISO. It is **not** a general-purpose desktop. The whole point
is a cabinet that goes from power-on to pinball with as little OS in the way
as possible:

- **Display:** [weston](https://wayland.freedesktop.org/) as the compositor,
  with the launched program as its only Wayland client.
- **Graphics:** Mesa Vulkan drivers (AMD / Intel), so VPinball's BGFX
  renderer runs with a real GPU.
- **Apps:** `vpinball` and `vpinfe` (a cabinet frontend/launcher), plus
  Google Chrome for vpinfe's local UI.
- **Installer:** the [Calamares](https://calamares.io/) installer, branded
  for VPinOS, to put it on a cabinet's disk.
- **Account:** one hardcoded appliance user, `vpinos` (password `vpinos`),
  in the `video`, `input`, `audio`, `render` and `sudo` groups. The apps run
  as this user, not as root.

## Live vs. installed

The same image runs two ways. Everything is identical except where it lives
and whether changes survive a reboot.

|                       | **Live** (boot the USB stick)                    | **Installed** (on the cabinet's disk)              |
|-----------------------|--------------------------------------------------|----------------------------------------------------|
| How you get it        | Write the ISO to a USB stick and boot it         | Run the installer from the live session (menu option 4) |
| Storage               | Read-only image, changes held in RAM             | Normal read-write install                          |
| Changes persist?      | **No** &mdash; everything resets on reboot       | Yes                                                |
| Login                 | Console autologin as `vpinos` on tty1            | Console autologin as `vpinos` on tty1              |
| Start the menu        | run `vpinos-menu`                                | run `vpinos-menu`                                  |
| `sudo`                | Passwordless (live session default)              | Asks for the `vpinos` password, except the launcher the menu uses |
| Updating vpinball / vpinfe | Not useful (lost at reboot) &mdash; use a newer ISO | `sudo apt update && sudo apt upgrade`          |
| Good for              | Trying it, hardware checks, running the installer | Daily use on the cabinet                          |

The **live** session is the way to try VPinOS on a machine without touching
its disks. To make it permanent, pick **Launch Installer (Calamares)** from
the menu and follow the prompts (language, keyboard, partitioning, summary).

### The menu

After login you land on a plain console. Run `vpinos-menu`:

```
1) Launch VPinball (Example Table)
2) Launch VPinFE (Frontend)
3) Launch Chrome only (debug)
4) Launch Installer (Calamares)
q) Quit to shell
```

The menu is a deliberate placeholder to prove out the launch path; booting
straight into the frontend is still to come.

## Releases

Prebuilt ISOs are published on the
[**Releases**](../../releases) page.

- A release is created **only when a version tag** (`v1.2.3`, matching the
  version stamped into the image) is pushed. The `Build VPinOS ISO` GitHub
  Actions workflow builds the image from a clean checkout and attaches it.
- Each release contains:
  - `live-image-amd64.hybrid.iso` &mdash; the image (roughly 1.8&nbsp;GB)
  - `live-image-amd64.packages` &mdash; every package and version in the image
  - `live-image-amd64.contents` / `.files` &mdash; the full file listing
- Pushes to `main` and manual runs build the image and upload it as a
  short-lived workflow artifact for verification, but do not create a release.
- The version shown on the boot splash, in the installer, on the login
  banner and in `/etc/os-release` all come from that one file:
  [`config/includes.chroot/etc/os-release`](config/includes.chroot/etc/os-release).

### Using an ISO

1. Download `live-image-amd64.hybrid.iso` from the latest release.
2. Write it to a USB stick (this **erases** the stick), for example:
   ```bash
   sudo dd if=live-image-amd64.hybrid.iso of=/dev/sdX bs=4M status=progress conv=fsync
   ```
   or use a tool such as balenaEtcher. Double-check `/dev/sdX` first.
3. Boot the target machine from the stick. The image carries both BIOS
   (syslinux) and UEFI (GRUB) boot files.
4. Run `vpinos-menu`. To install, choose option 4.

### Requirements

- x86-64 PC with a GPU supported by Mesa's Vulkan drivers (**AMD or Intel**).
  NVIDIA needs its proprietary driver, which is not included yet.
- The installer sets up a **UEFI** boot (GRUB EFI). Installing onto a
  BIOS-only machine has not been tested.
- A network connection is needed to update, but not to run.

## Updates: vpinball and vpinfe

`vpinball` and `vpinfe` are not compiled into the image. They come from a
signed apt repository, [`superhac/vpinos-repo`](https://github.com/superhac/vpinos-repo),
whose packages are built in
[`superhac/vpinos-deb-repo`](https://github.com/superhac/vpinos-deb-repo).
The repository's source and public key are part of the image, so on an
**installed** system:

```bash
sudo apt update && sudo apt upgrade
```

picks up new vpinball / vpinfe releases (and Debian security updates). A newly
built ISO always contains whatever is currently published there.

## Security notes

VPinOS is a single-purpose cabinet image and ships with a **known default
password** (`vpinos` / `vpinos`) and an **SSH server** installed for remote
maintenance. On any cabinet that is reachable from a network, change the
password after installing (`passwd`), and don't expose it to the internet.

## Building from source

You need Docker; everything else happens inside the `vpinos-builder`
container defined by the [`Dockerfile`](Dockerfile).

```bash
docker build -t vpinos-builder .

docker run --rm --privileged --ulimit nofile=65536:65536 -v "$PWD:/work" -w /work vpinos-builder lb clean
docker run --rm --ulimit nofile=65536:65536 -v "$PWD:/work" -w /work vpinos-builder \
  lb config \
    --distribution trixie \
    --architectures amd64 \
    --binary-images iso-hybrid \
    --archive-areas "main contrib non-free non-free-firmware" \
    --bootappend-live "boot=live components quiet splash username=vpinos"

# Fix ownership of the generated config only -- never `chown -R` the whole
# project: it corrupts cache/bootstrap and the built image ends up with its
# base system owned by the wrong user.
docker run --rm -v "$PWD:/work" -w /work vpinos-builder sh -c \
  'for d in config auto local .build; do [ -e "$d" ] && chown -R '"$(id -u):$(id -g)"' "$d"; done; true'

docker run --rm --privileged --ulimit nofile=65536:65536 -v "$PWD:/work" -w /work vpinos-builder lb build
```

The ISO lands in the project root as `live-image-amd64.hybrid.iso`. Always
run the full `lb clean` &rarr; `lb config` &rarr; `lb build` cycle after
editing anything under `config/`; a bare `lb build` silently reuses stale
stages. The [GitHub Actions workflow](.github/workflows/build-iso.yml) runs
this same sequence.

## Repository layout

| Path | What it is |
|------|------------|
| `config/package-lists/` | Debian packages installed into the image |
| `config/hooks/live/` | Scripts run inside the image at build time (user creation, branding, installing vpinball/vpinfe, enabling services) |
| `config/includes.chroot/` | Files copied verbatim into the image: the launcher and menu under `/opt/vpinball/`, weston and systemd config, apt source and key, Calamares branding, `os-release` |
| `config/bootloaders/` | Boot splash and GRUB background artwork |
| `Dockerfile` | The reproducible build environment |
| `.github/workflows/build-iso.yml` | CI build and tag-triggered release |

`chroot/`, `binary/`, `cache/`, `.build/` and `dist/` are build output and
are not committed.

## Status

**Beta.** Early and actively developed. The build, live boot, launch path
(weston &rarr; vpinball / vpinfe) and installer are working end to end.
Still ahead: booting straight into the frontend instead of a console menu,
persistence for the live medium, and narrowing GPU/firmware support once the
target hardware is settled.
