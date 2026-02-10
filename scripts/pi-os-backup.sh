#!/usr/bin/env bash
set -euo pipefail

# OMV mounted thumb drive (from your df -h)
BACKUP_MOUNT="/srv/dev-disk-by-uuid-f8935f5d-dd4b-4c8d-9a9b-ef523e3ae613"
BACKUP_DIR="$BACKUP_MOUNT/pi-os-backup"
LOGFILE="/var/log/pi-os-backup.log"

echo "===== $(date -Is) Backup started =====" >> "$LOGFILE"

# Safety check 1: ensure mountpoint exists and is mounted
if [[ ! -d "$BACKUP_MOUNT" ]]; then
  echo "ERROR: Backup mount path does not exist: $BACKUP_MOUNT" >> "$LOGFILE"
  exit 1
fi

if ! mountpoint -q "$BACKUP_MOUNT"; then
  echo "ERROR: Backup drive not mounted at $BACKUP_MOUNT. Aborting." >> "$LOGFILE"
  exit 1
fi

# Safety check 2: refuse to run if BACKUP_MOUNT is root (paranoia)
if [[ "$BACKUP_MOUNT" == "/" ]]; then
  echo "ERROR: BACKUP_MOUNT resolved to /. Aborting." >> "$LOGFILE"
  exit 1
fi

mkdir -p "$BACKUP_DIR"

# Optional: keep one “current” snapshot and also dated snapshots
# Uncomment if you want dated snapshots:
# SNAPSHOT_DIR="$BACKUP_MOUNT/pi-os-backup-$(date +%F)"
# mkdir -p "$SNAPSHOT_DIR"
# BACKUP_DIR="$SNAPSHOT_DIR"

# rsync root filesystem to USB, preserving ACLs/xattrs
# Key changes vs your version:
# - excludes the destination itself (prevents recursion)
# - excludes OMV/mergerfs mounts by path
rsync -aAXHv --numeric-ids --delete --delete-excluded \
  --exclude="/dev/*" \
  --exclude="/proc/*" \
  --exclude="/sys/*" \
  --exclude="/tmp/*" \
  --exclude="/run/*" \
  --exclude="/mnt/*" \
  --exclude="/media/*" \
  --exclude="/lost+found" \
  --exclude="/srv/dev-disk-by-uuid-*/**" \
  --exclude="/srv/mergerfs/**" \
  --exclude="$BACKUP_DIR/**" \
  / "$BACKUP_DIR" >> "$LOGFILE" 2>&1

sync

echo "===== $(date -Is) Backup finished =====" >> "$LOGFILE"