#!/usr/bin/env bash
set -euo pipefail

BACKUP_MOUNT="/srv/dev-disk-by-uuid-f8935f5d-dd4b-4c8d-9a9b-ef523e3ae613"
BACKUP_DIR="$BACKUP_MOUNT/pi-os-backup"
LOGFILE="/var/log/pi-os-backup.log"

# ---------- logging helpers ----------
log() {
  echo "$(date -Is) | $*" >> "$LOGFILE"
}

fail() {
  log "FATAL: $*"
  exit 1
}

trap 'fail "Script terminated unexpectedly on line $LINENO"' ERR

log "===== Backup START ====="
log "Backup mount: $BACKUP_MOUNT"
log "Backup dir:   $BACKUP_DIR"

# ---------- safety checks ----------
log "Checking if backup mount path exists"
[[ -d "$BACKUP_MOUNT" ]] || fail "Backup mount path does not exist"

log "Checking if backup mount is mounted"
mountpoint -q "$BACKUP_MOUNT" || fail "Backup drive not mounted"

log "Checking BACKUP_MOUNT is not root"
[[ "$BACKUP_MOUNT" != "/" ]] || fail "BACKUP_MOUNT resolved to /"

# ---------- prepare destination ----------
log "Ensuring backup directory exists"
mkdir -p "$BACKUP_DIR"
log "Backup directory ready"

# ---------- rsync ----------
log "Starting rsync filesystem backup"
log "Excluding system pseudo-filesystems and resource mounts"

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

log "rsync completed successfully"

# ---------- flush to disk ----------
log "Flushing filesystem buffers (sync)"
sync
log "sync completed"

log "===== Backup FINISHED ====="