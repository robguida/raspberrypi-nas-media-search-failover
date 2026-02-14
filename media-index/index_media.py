#!/usr/bin/env python3

import os
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime
import reverse_geocoder as rg

# ==============================
# CONFIG
# ==============================
MEDIA_ROOT = Path("/srv/mergerfs/MergedDrives")
DB_PATH = Path("/srv/dev-disk-by-uuid-c8f195fd-35e1-449f-90cb-0633bf99bde2/appdata/media-index/media_index.sqlite")
BATCH_SIZE = 2000

ALLOWED_EXTS = {"jpg", "jpeg", "png", "heic", "mp4", "mov"}

# ==============================
# DB INIT
# ==============================
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media (
            path TEXT PRIMARY KEY,
            filename TEXT,
            ext TEXT,
            size_bytes INTEGER,
            mtime INTEGER,

            created_utc TEXT,
            taken_utc TEXT,
            year INTEGER,

            lat REAL,
            lon REAL,

            country_code TEXT,
            country_name TEXT,
            city TEXT,
            admin1 TEXT,
            admin2 TEXT
        );
        """
    )

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
            path, filename, country_name, city
        );
        """
    )

    # Indexes for performance
    conn.execute("CREATE INDEX IF NOT EXISTS idx_taken_utc ON media(taken_utc);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_country_code ON media(country_code);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_year ON media(year);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_latlon ON media(lat, lon);")

    # View expected by search_ui (DO NOT change the UI)
    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS v_search AS
        SELECT
            path,
            filename,
            ext,
            size_bytes,
            mtime,
            created_utc,
            taken_utc,
            country_name AS country,
            city,
            admin1,
            admin2,
            country_code,
            lat,
            lon,
            year
        FROM media;
        """
    )

    conn.commit()

# ==============================
# FILE SCAN
# ==============================
def scan_files():
    for root, _, files in os.walk(MEDIA_ROOT):
        for name in files:
            parts = name.rsplit(".", 1)
            if len(parts) != 2:
                continue
            ext = parts[1].lower()
            if ext not in ALLOWED_EXTS:
                continue

            full_path = Path(root) / name
            try:
                stat = full_path.stat()
            except FileNotFoundError:
                continue

            yield {
                "path": str(full_path),
                "filename": name,
                "ext": ext,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }

# ==============================
# EXIF EXTRACTION
# ==============================
def get_exif_batch(paths):
    if not paths:
        return []

    cmd = [
        "exiftool",
        "-json",
        "-n",  # numeric lat/lon
        "-DateTimeOriginal",
        "-CreateDate",
        "-GPSLatitude",
        "-GPSLongitude",
    ] + paths

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except Exception:
        return []

def parse_datetime(dt_string):
    if not dt_string:
        return None, None
    try:
        dt = datetime.strptime(dt_string, "%Y:%m:%d %H:%M:%S")
        # NOTE: this is often camera-local time; search_ui expects ISO strings in "taken_utc"
        return dt.isoformat(), dt.year
    except Exception:
        return None, None

# ==============================
# UPSERT LOGIC
# ==============================
def upsert_media(conn, file_info, exif_data):
    taken_utc = None
    year = None

    lat = None
    lon = None
    country_code = None
    country_name = None
    city = None
    admin1 = None
    admin2 = None

    if exif_data:
        dt_raw = exif_data.get("DateTimeOriginal") or exif_data.get("CreateDate")
        taken_utc, year = parse_datetime(dt_raw)

        lat = exif_data.get("GPSLatitude")
        lon = exif_data.get("GPSLongitude")

        if lat is not None and lon is not None:
            try:
                geo = rg.search((lat, lon))[0]
                country_code = geo.get("cc")
                city = geo.get("name")
                admin1 = geo.get("admin1")
                admin2 = geo.get("admin2")
                # reverse_geocoder doesn't give full country name; keep CC for now
                country_name = country_code
            except Exception:
                pass

    # Fallback year from mtime if missing
    if not year:
        year = datetime.utcfromtimestamp(file_info["mtime"]).year

    created_utc = datetime.utcfromtimestamp(file_info["mtime"]).isoformat()

    conn.execute(
        """
        INSERT INTO media (
            path, filename, ext, size_bytes, mtime,
            created_utc, taken_utc, year,
            lat, lon,
            country_code, country_name,
            city, admin1, admin2
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            mtime=excluded.mtime,
            created_utc=excluded.created_utc,
            taken_utc=excluded.taken_utc,
            year=excluded.year,
            lat=excluded.lat,
            lon=excluded.lon,
            country_code=excluded.country_code,
            country_name=excluded.country_name,
            city=excluded.city,
            admin1=excluded.admin1,
            admin2=excluded.admin2;
        """,
        (
            file_info["path"],
            file_info["filename"],
            file_info["ext"],
            file_info["size"],
            file_info["mtime"],
            created_utc,
            taken_utc,
            year,
            lat,
            lon,
            country_code,
            country_name,
            city,
            admin1,
            admin2,
        ),
    )

    conn.execute(
        """
        INSERT OR REPLACE INTO media_fts(rowid, path, filename, country_name, city)
        VALUES (
            (SELECT rowid FROM media WHERE path=?),
            ?, ?, ?, ?
        );
        """,
        (
            file_info["path"],
            file_info["path"],
            file_info["filename"],
            country_name,
            city,
        ),
    )

# ==============================
# BATCH PROCESS
# ==============================
def process_batch(conn, batch):
    paths = [f["path"] for f in batch]
    exif_results = get_exif_batch(paths)
    exif_map = {item.get("SourceFile"): item for item in exif_results if item.get("SourceFile")}

    for file_info in batch:
        exif_data = exif_map.get(file_info["path"])
        upsert_media(conn, file_info, exif_data)

    conn.commit()

# ==============================
# MAIN
# ==============================
def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    print(f"Scanning files under: {MEDIA_ROOT}")
    batch = []
    for file_info in scan_files():
        batch.append(file_info)
        if len(batch) >= BATCH_SIZE:
            process_batch(conn, batch)
            batch = []

    if batch:
        process_batch(conn, batch)

    conn.close()
    print("Indexing complete.")

if __name__ == "__main__":
    main()