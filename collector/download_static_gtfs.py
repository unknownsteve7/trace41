"""
collector/download_static_gtfs.py
──────────────────────────────────
Downloads Delhi DTC static GTFS (mdb-3139) from Mobility Database
and saves the raw zip to data/static_gtfs/.
Also extracts all files.

Run once on Day 1.

Usage:
    python collector/download_static_gtfs.py
"""

import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

# Mobility Database direct download link for mdb-3139
# Source: https://mobilitydatabase.org/feeds/mdb-3139
MDB_FEED_ID  = "mdb-3139"
MDB_API_URL  = "https://api.mobilitydatabase.org/v1/gtfs_feeds"
# Direct archive URL (static snapshot):
GTFS_ZIP_URL = "https://storage.googleapis.com/storage/v1/b/mdb-latest/o/in-delhi_and_ncr-delhi_transport_corporation-gtfs-1048.zip?alt=media"

OUT_DIR  = Path("data/static_gtfs")
ZIP_PATH = OUT_DIR / "delhi_dtc_mdb3139.zip"
MANIFEST = OUT_DIR / "download_manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path):
    print(f"Downloading {url}")
    print(f"  → {dest}")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = 100 * downloaded / total
                print(f"\r  {downloaded/1_048_576:.1f} / {total/1_048_576:.1f} MB  ({pct:.0f}%)", end="")
    print(f"\n  Download complete: {downloaded/1_048_576:.1f} MB")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Download zip ──────────────────────────────────────────────────────────
    if ZIP_PATH.exists():
        print(f"Zip already exists: {ZIP_PATH} — delete to re-download.")
    else:
        try:
            download(GTFS_ZIP_URL, ZIP_PATH)
        except Exception as e:
            print(f"\nERROR: Could not download from primary URL: {e}")
            print("Try manually downloading from:")
            print("  https://mobilitydatabase.org/feeds/mdb-3139")
            print(f"  and saving to {ZIP_PATH}")
            sys.exit(1)

    # ── SHA-256 ───────────────────────────────────────────────────────────────
    print("Computing SHA-256...")
    sha = sha256_file(ZIP_PATH)
    print(f"  SHA-256: {sha}")

    # ── Extract ───────────────────────────────────────────────────────────────
    print("Extracting...")
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        members = zf.namelist()
        print(f"  Files in zip: {len(members)}")
        for m in members:
            print(f"    {m}  ({zf.getinfo(m).file_size/1_048_576:.1f} MB)")
        zf.extractall(OUT_DIR)
    print(f"  Extracted to {OUT_DIR}")

    # ── Manifest ──────────────────────────────────────────────────────────────
    manifest = {
        "feed_id":         MDB_FEED_ID,
        "source_url":      GTFS_ZIP_URL,
        "downloaded_at":   datetime.now(timezone.utc).isoformat(),
        "zip_path":        str(ZIP_PATH),
        "zip_size_mb":     ZIP_PATH.stat().st_size / 1_048_576,
        "sha256":          sha,
        "extracted_files": members,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"  Manifest saved → {MANIFEST}")

    print("\n✅ Done. Next step: python collector/inspect_static_gtfs.py")


if __name__ == "__main__":
    main()
