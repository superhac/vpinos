#!/bin/sh
# Populates ~/tables from a GitHub repo of sample tables
# (https://github.com/superhac/vpinos-test-tables), on first boot only --
# this image no longer bundles sample tables directly (removed once they
# pushed the ISO over GitHub's 2 GiB release-asset limit, see
# notes/vpinos.md step 2). Run as a systemd service (see
# vpinos-fetch-tables.service), as the `vpinos` user directly -- not
# root, not sudo'd -- so whatever it creates is already correctly
# owned, no chown-after-the-fact needed.
#
# Works identically live or installed, no is_installed()-style gate
# needed: a live session never persists ~/tables across a reboot, so it
# genuinely re-downloads every boot (same content, same URL, idempotent
# in effect even though not in mechanism); an installed system only
# ever downloads once, since every boot after the first finds ~/tables
# already populated and skips straight past.
set -e

tables_dir="/home/vpinos/tables"
repo_url="https://github.com/superhac/vpinos-test-tables/archive/refs/heads/master.tar.gz"
log="/var/log/vpinos-tables.log"

log_msg() {
    echo "$(date -Is): vpinos-fetch-tables: $1" >>"$log"
}

# Already populated (or deliberately emptied by someone who doesn't
# want the sample tables) -- nothing to do. `ls -A` rather than just
# `-d $tables_dir` so a stray empty directory (e.g. left over from a
# previous failed download, or created by hand) still triggers a retry
# rather than being treated as "already done".
if [ -d "$tables_dir" ] && [ -n "$(ls -A "$tables_dir" 2>/dev/null)" ]; then
    exit 0
fi

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

log_msg "downloading $repo_url"
if ! curl -fsSL "$repo_url" -o "$tmp_dir/tables.tar.gz"; then
    log_msg "download failed -- no network yet, or GitHub unreachable; will retry next boot"
    exit 1
fi

mkdir -p "$tmp_dir/extracted"
# --strip-components=1: GitHub's own archive endpoint wraps everything
# in one top-level "<repo>-<branch>/" directory that isn't part of the
# real table layout.
if ! tar xzf "$tmp_dir/tables.tar.gz" -C "$tmp_dir/extracted" --strip-components=1; then
    log_msg "extraction failed -- corrupt/incomplete download; will retry next boot"
    exit 1
fi

# Extract-then-move rather than extracting directly into $tables_dir:
# if anything above fails partway, $tables_dir is never created at
# all, so the next boot's "already populated?" check above correctly
# sees it as still missing and retries, instead of finding a half-
# extracted mess it mistakes for success.
mkdir -p "$(dirname "$tables_dir")"
mv "$tmp_dir/extracted" "$tables_dir"
log_msg "done -- $(ls "$tables_dir" | wc -l) tables installed"
