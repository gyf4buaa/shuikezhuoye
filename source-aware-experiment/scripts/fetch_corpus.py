#!/usr/bin/env python3
"""Download the pinned OpenTTD corpus used by the audit and experiment.

The archive is verified against a committed SHA-256, then extracted under
``.corpus/`` (gitignored).  Nothing is fetched by the test suite; this script is
an explicit, reproducible step documented in the README.

Usage:
    python3 scripts/fetch_corpus.py            # download, verify, extract
    python3 scripts/fetch_corpus.py --check    # verify an existing checkout
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "audit" / "corpus.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def corpus_dir(manifest: dict, destination: Path) -> Path:
    return destination / f"openttd-{manifest['version']}"


def check(manifest: dict, destination: Path) -> int:
    root = corpus_dir(manifest, destination)
    required = ["src/lang/english.txt", "src/table/cargo_const.h", "src/settings.cpp", "COPYING.md"]
    missing = [item for item in required if not (root / item).is_file()]
    if missing:
        print(f"missing corpus files under {root}: {', '.join(missing)}")
        return 1
    if manifest.get("archive_sha256") and not (destination / "openttd.tar.gz").is_file():
        print(f"note: archive cache not present at {destination / 'openttd.tar.gz'}")
    print(f"corpus OK: {root}")
    return 0


def fetch(manifest: dict, destination: Path, force: bool) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    target = corpus_dir(manifest, destination)
    if target.is_dir() and not force:
        print(f"already extracted: {target} (use --force to re-extract)")
        return check(manifest, destination)
    archive = destination / "openttd.tar.gz"
    expected = manifest.get("archive_sha256")
    if force and archive.exists():
        archive.unlink()
    if not archive.exists():
        print(f"downloading {manifest['archive_url']}")
        request = urllib.request.Request(
            manifest["archive_url"],
            headers={"User-Agent": "source-aware-experiment/1.0"},
        )
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    actual = sha256(archive)
    if expected and actual != expected:
        print(f"sha256 mismatch: expected {expected}, got {actual}", file=sys.stderr)
        return 2
    print(f"archive sha256 OK: {actual}")
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        with tarfile.open(archive, "r:gz") as bundle:
            members = [m for m in bundle.getmembers() if m.name.startswith(manifest["extracted_directory"] + "/")]
            if not members:
                print("archive does not contain the expected top-level directory", file=sys.stderr)
                return 3
            try:
                bundle.extractall(tmp, members=members, filter="data")
            except TypeError:  # Python < 3.12 has no extraction filter
                bundle.extractall(tmp, members=members)
        extracted = Path(tmp) / manifest["extracted_directory"]
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(extracted), str(target))
    return check(manifest, destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default=str(ROOT / ".corpus"))
    parser.add_argument("--check", action="store_true", help="only verify an existing checkout")
    parser.add_argument("--force", action="store_true", help="re-download and re-extract")
    args = parser.parse_args(argv)
    manifest = load_manifest()
    destination = Path(args.destination).expanduser().resolve()
    if args.check:
        return check(manifest, destination)
    return fetch(manifest, destination, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
