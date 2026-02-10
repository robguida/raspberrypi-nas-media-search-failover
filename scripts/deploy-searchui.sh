#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/robguida/raspberrypi-nas-media-search-failover.git"
BRANCH="${BRANCH:-main}"
SRC_ROOT="/tmp/raspberrypi-nas-media-search-failover"
DEPLOY_TO="/var/www/search-ui"
UI_DIR_IN_REPO="search_ui"

log() { echo "[$(date '+%F %T')] $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing command: $1"; exit 1; }
}

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "ERROR: run as root: sudo $0"
  exit 1
fi

need_cmd git
need_cmd rsync

log "Deploy config:"
log "  REPO_URL=$REPO_URL"
log "  BRANCH=$BRANCH"
log "  SRC_ROOT=$SRC_ROOT"
log "  UI_DIR_IN_REPO=$UI_DIR_IN_REPO"
log "  DEPLOY_TO=$DEPLOY_TO"

mkdir -p "$(dirname "$SRC_ROOT")"

if [ ! -d "$SRC_ROOT/.git" ]; then
  log "Cloning repo -> $SRC_ROOT"
  rm -rf "$SRC_ROOT"
  git clone "$REPO_URL" "$SRC_ROOT"
else
  log "Repo already exists at $SRC_ROOT"
fi

cd "$SRC_ROOT"

log "git fetch --all"
git fetch --all

log "git reset --hard origin/$BRANCH"
git reset --hard "origin/$BRANCH"

if [ ! -d "$SRC_ROOT/$UI_DIR_IN_REPO" ]; then
  echo "ERROR: UI folder not found: $SRC_ROOT/$UI_DIR_IN_REPO"
  exit 1
fi

mkdir -p "$DEPLOY_TO"

log "rsync (verbose) -> $DEPLOY_TO"
rsync -av --delete --stats \
  "$SRC_ROOT/$UI_DIR_IN_REPO/" \
  "$DEPLOY_TO/"

log "Permissions: www-data:www-data + 755 dirs + 644 files"
chown -R www-data:www-data "$DEPLOY_TO"
find "$DEPLOY_TO" -type d -exec chmod 755 {} \;
find "$DEPLOY_TO" -type f -exec chmod 644 {} \;

log "Cleaning up source checkout: $SRC_ROOT"
if [[ "$SRC_ROOT" == /tmp/* ]]; then
  rm -rf "$SRC_ROOT"
fi

log "OK: deployed $UI_DIR_IN_REPO -> $DEPLOY_TO"