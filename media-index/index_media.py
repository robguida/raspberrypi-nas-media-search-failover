#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import reverse_geocoder as rg
import pycountry

# ---- CONFIG ----
MEDIA_ROOT = Path("/srv/mergerfs/MergedDrives")  # CHANGE THIS
DB_PATH = Path("/srv/dev-disk-by-uuid-c8f195fd-35e1-449f-90cb-0633bf99bde2/appdata/media-index/media_index.sqlite")  # CHANGE THIS
BATCH_SIZE = 2000

MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".webp",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp"
}

# ---- DB SETUP ----
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  ext TEXT,
  size_bytes INTEGER,
  mtime INTEGER,
  created_utc TEXT,
  taken_utc TEXT,
  lat REAL,
  lon REAL,
  country_code TEXT,
  country_name TEXT,
  camera_make TEXT,
  camera_model TEXT
);

-- Full-text index for filename and path
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
  path,
  filename,
  content='files',
  content_rowid='rowid'
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
  INSERT INTO files_fts(rowid, path, filename) VALUES (new.rowid, new.path, new.filename);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, path, filename) VALUES ('delete', old.rowid, old.path, old.filename);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, path, filename) VALUES ('delete', old.rowid, old.path, old.filename);
  INSERT INTO files_fts(rowid, path, filename) VALUES (new.rowid, new.path, new.filename);
END;
"""

UPSERT_SQL = """
INSERT INTO files (
  path, filename, ext, size_bytes, mtime, created_utc, taken_utc,
  lat, lon, country_code, country_name, camera_make, camera_model
) VALUES (
  :path, :filename, :ext, :size_bytes, :mtime, :created_utc, :taken_utc,
  :lat, :lon, :country_code, :country_name, :camera_make, :camera_model
)
ON CONFLICT(path) DO UPDATE SET
  filename=excluded.filename,
  ext=excluded.ext,
  size_bytes=excluded.size_bytes,
  mtime=excluded.mtime,
  created_utc=excluded.created_utc,
  taken_utc=excluded.taken_utc,
  lat=excluded.lat,
  lon=excluded.lon,
  country_code=excluded.country_code,
  country_name=excluded.country_name,
  camera_make=excluded.camera_make,
  camera_model=excluded.camera_model;
"""

def country_name_from_code(code: str | None) -> str | None:
    if not code:
        return None
    try:
        c = pycountry.countries.get(alpha_2=code.upper())
        return c.name if c else code.upper()
    except Exception:
        return code.upper()

def reverse_country(lat: float | None, lon: float | None) -> tuple[str | None, str | None]:
    if lat is None or lon is None:
        return (None, None)
    try:
        res = rg.search((lat, lon), mode=1)  # single result
        cc = res[0].get("cc")
        return (cc, country_name_from_code(cc))
    except Exception:
        return (None, None)

def exiftool_json(paths: list[str]) -> list[dict]:
    # -n = numeric output (lat/lon as floats)
    cmd = ["exiftool", "-json", "-n",
           "-FileName", "-FileTypeExtension", "-FileSize#",
           "-CreateDate", "-DateTimeOriginal",
           "-GPSLatitude", "-GPSLongitude",
           "-Make", "-Model"] + paths
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        # exiftool sometimes returns nonzero on some files; still may output JSON
        if not p.stdout.strip():
            raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout or "[]")

def iter_media_files(root: Path):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in MEDIA_EXTS:
                yield p

def main():
    if not MEDIA_ROOT.exists():
        print(f"MEDIA_ROOT does not exist: {MEDIA_ROOT}", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA_SQL)

    cur = conn.cursor()

    # Build a set of existing rows with (size, mtime) to support incremental updates
    cur.execute("SELECT path, size_bytes, mtime FROM files")
    existing = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    batch = []
    to_process = []

    for p in iter_media_files(MEDIA_ROOT):
        st = p.stat()
        sp = str(p)
        sig = (st.st_size, int(st.st_mtime))
        if existing.get(sp) == sig:
            continue
        to_process.append(sp)
        if len(to_process) >= BATCH_SIZE:
            batch.append(to_process)
            to_process = []

    if to_process:
        batch.append(to_process)

    total = sum(len(b) for b in batch)
    print(f"Files to index/update: {total}")

    indexed = 0
    for group in batch:
        meta = exiftool_json(group)
        rows = []
        for m in meta:
            path = m.get("SourceFile")
            if not path:
                continue
            p = Path(path)
            st = p.stat()

            lat = m.get("GPSLatitude")
            lon = m.get("GPSLongitude")
            cc, cn = reverse_country(lat, lon)

            # Use EXIF taken date if available; otherwise CreateDate; otherwise None
            taken = m.get("DateTimeOriginal") or m.get("CreateDate")
            # Normalize: keep as ISO-ish string when possible
            taken_utc = None
            if taken:
                # ExifTool returns "YYYY:MM:DD HH:MM:SS" typically
                try:
                    dt = datetime.strptime(taken, "%Y:%m:%d %H:%M:%S")
                    taken_utc = dt.isoformat()
                except Exception:
                    taken_utc = str(taken)

            rows.append({
                "path": path,
                "filename": p.name,
                "ext": (m.get("FileTypeExtension") or p.suffix.lstrip(".")).lower() if (m.get("FileTypeExtension") or p.suffix) else None,
                "size_bytes": int(m.get("FileSize#") or st.st_size),
                "mtime": int(st.st_mtime),
                "created_utc": datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                "taken_utc": taken_utc,
                "lat": lat,
                "lon": lon,
                "country_code": cc,
                "country_name": cn,
                "camera_make": m.get("Make"),
                "camera_model": m.get("Model"),
            })

        conn.executemany(UPSERT_SQL, rows)
        conn.commit()
        indexed += len(rows)
        print(f"Indexed: {indexed}/{total}")

    # Optional: remove rows for files that no longer exist
    cur.execute("SELECT path FROM files")
    all_paths = [r[0] for r in cur.fetchall()]
    missing = [p for p in all_paths if not os.path.exists(p)]
    if missing:
        print(f"Removing missing files from index: {len(missing)}")
        conn.executemany("DELETE FROM files WHERE path=?", [(p,) for p in missing])
        conn.commit()

    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()
