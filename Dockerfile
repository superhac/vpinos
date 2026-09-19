FROM debian:trixie

RUN apt-get update && apt-get install -y --no-install-recommends \
    live-build \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-common \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work
