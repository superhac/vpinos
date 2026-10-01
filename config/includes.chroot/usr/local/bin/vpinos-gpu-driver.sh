#!/bin/sh
# Switches which GPU kernel module is bound to the card, based on
# /etc/vpinos/gpu-driver -- called via `sudo` from launch.sh, on every
# single invocation (cheap/idempotent if nothing needs to change), right
# before it execs Hyprland. That's the one point every client type
# (vpinball/vpinfe/Chrome/installer/vpxconfig/gamepadtest) already goes
# through, live or installed, and nothing graphical has started yet at
# that point in any of them -- so nothing holds either driver's DRM
# device open, and this never needs a reboot to take effect, unlike the
# "Boot on startup" mode switch (see vpinos-menu.sh's "GPU Driver"
# option and notes/vpinos.md step 5 for the full reasoning).
#
# root-only: modprobe needs CAP_SYS_MODULE, which `vpinos` doesn't have
# and shouldn't -- see /etc/sudoers.d/vpinos, scoped to this one script
# specifically, same narrow-scope reasoning as every other rule there.
set -e

mode=$(cat /etc/vpinos/gpu-driver 2>/dev/null || true)

case "$mode" in
    nvidia)
        # nouveau (the open-source driver) is almost certainly already
        # bound -- the kernel auto-loads it via udev/module aliases as
        # soon as it sees NVIDIA hardware, same as amdgpu for AMD cards,
        # well before this script ever runs. It has to be unloaded
        # before nvidia.ko can claim the device.
        modprobe -r nouveau 2>/dev/null || true
        modprobe nvidia 2>/dev/null \
            || echo "$(date -Is): vpinos-gpu-driver: modprobe nvidia failed -- no NVIDIA hardware, or the precompiled module doesn't match this kernel?" >>/var/log/vpinos-menu.log
        ;;
    *)
        # Default/anything unrecognized: plain open-source Mesa (NVK on
        # NVIDIA hardware, RADV on AMD, Intel's own driver) -- make sure
        # nvidia isn't still bound from a previous launch this session.
        #
        # The explicit `modprobe nouveau` here isn't just defensive --
        # it's required. nvidia-driver ships
        # /etc/modprobe.d/nvidia-blacklists-nouveau.conf (confirmed via
        # Debian's own packaging source), so once it's installed (which
        # 0120-install-nvidia-driver.hook.chroot does unconditionally,
        # regardless of which mode ends up selected), nouveau stops
        # auto-loading entirely, on every boot. `blacklist` only blocks
        # *automatic* alias-based loading (udev/hotplug resolving
        # hardware IDs to a driver) -- it does not block an explicit
        # `modprobe nouveau` by exact name, which is exactly what this
        # does.
        modprobe -r nvidia 2>/dev/null || true
        modprobe nouveau 2>/dev/null || true
        ;;
esac
