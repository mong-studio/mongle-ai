"""Sync raw data files between local ``data/raw/`` and a private S3 bucket.

Usage:
    python -m ingestion.s3_sync push   # upload local data/raw/ to S3, rewrite manifest
    python -m ingestion.s3_sync pull   # download files listed in manifest from S3

Configuration is read from environment variables (see .env.example).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import boto3

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
CHUNK = 1024 * 1024


class ManifestEntry(TypedDict):
    path: str
    s3_key: str
    sha256: str
    size: int
    uploaded_at: str


def _config() -> tuple[str, str, str]:
    bucket = os.environ.get("AWS_S3_BUCKET")
    region = os.environ.get("AWS_REGION")
    prefix = (os.environ.get("AWS_S3_PREFIX") or "").strip("/")
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET is not set. See .env.example.")
    if not region:
        raise RuntimeError("AWS_REGION is not set. See .env.example.")
    return bucket, prefix, region


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "files": []}
    return json.loads(MANIFEST_PATH.read_text())


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )


def _client(region: str):
    return boto3.client("s3", region_name=region)


def _iter_local_files() -> list[Path]:
    return sorted(
        p for p in RAW_DIR.rglob("*")
        if p.is_file() and p.name != ".gitkeep"
    )


def push() -> None:
    bucket, prefix, region = _config()
    client = _client(region)
    files = _iter_local_files()
    if not files:
        print(f"No files in {RAW_DIR.relative_to(ROOT)}. Nothing to upload.")
        return
    entries: list[ManifestEntry] = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        s3_key = f"{prefix}/{rel}" if prefix else rel
        digest = _sha256(path)
        size = path.stat().st_size
        print(f"upload {rel} -> s3://{bucket}/{s3_key} ({size} bytes)")
        client.upload_file(str(path), bucket, s3_key)
        entries.append({
            "path": rel,
            "s3_key": s3_key,
            "sha256": digest,
            "size": size,
            "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        })
    _save_manifest({"version": 1, "files": entries})
    print(f"Wrote manifest with {len(entries)} entries.")


def pull() -> None:
    bucket, _, region = _config()
    client = _client(region)
    manifest = _load_manifest()
    entries: list[ManifestEntry] = manifest.get("files", [])
    if not entries:
        print("Manifest is empty. Nothing to download.")
        return
    for entry in entries:
        dest = ROOT / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and _sha256(dest) == entry["sha256"]:
            print(f"skip     {entry['path']} (sha256 match)")
            continue
        print(f"download s3://{bucket}/{entry['s3_key']} -> {entry['path']}")
        client.download_file(bucket, entry["s3_key"], str(dest))
        actual = _sha256(dest)
        if actual != entry["sha256"]:
            raise RuntimeError(
                f"sha256 mismatch for {entry['path']}: "
                f"expected {entry['sha256']}, got {actual}"
            )
    print(f"Pulled {len(entries)} file(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync raw data to/from S3.")
    parser.add_argument("command", choices=("push", "pull"))
    args = parser.parse_args()
    if args.command == "push":
        push()
    else:
        pull()


if __name__ == "__main__":
    main()
