"""Download or verify the exact manifest-managed media wheel set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = Path(__file__).with_name("wheel_hashes.json")
WHEEL_DIRECTORY = ROOT / "wheels"
PYPI_RELEASES = (
    ("Pillow", "12.3.0"),
    ("imageio-ffmpeg", "0.6.0"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _locked_hashes() -> dict[str, str]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _release_urls() -> dict[str, tuple[str, str]]:
    results: dict[str, tuple[str, str]] = {}
    for package, version in PYPI_RELEASES:
        url = f"https://pypi.org/pypi/{package}/{version}/json"
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = json.load(response)
        for item in payload["urls"]:
            filename = str(item["filename"])
            if filename.endswith(".whl"):
                results[filename] = (
                    str(item["url"]),
                    str(item["digests"]["sha256"]),
                )
    return results


def verify() -> None:
    locked = _locked_hashes()
    present = {path.name for path in WHEEL_DIRECTORY.glob("*.whl")}
    if present != locked.keys():
        missing = sorted(locked.keys() - present)
        extra = sorted(present - locked.keys())
        raise RuntimeError(f"Wheel set mismatch; missing={missing}, extra={extra}")
    for filename, expected in sorted(locked.items()):
        actual = _sha256(WHEEL_DIRECTORY / filename)
        if actual != expected:
            raise RuntimeError(f"Wheel hash mismatch: {filename}")


def sync() -> None:
    locked = _locked_hashes()
    releases = _release_urls()
    WHEEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for filename, expected in sorted(locked.items()):
        if filename not in releases:
            raise RuntimeError(f"Locked wheel is absent from PyPI: {filename}")
        url, published_hash = releases[filename]
        if published_hash != expected:
            raise RuntimeError(f"Published wheel hash changed: {filename}")
        destination = WHEEL_DIRECTORY / filename
        if destination.is_file() and _sha256(destination) == expected:
            continue
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                with temporary.open("wb") as handle:
                    while block := response.read(1024 * 1024):
                        handle.write(block)
            if _sha256(temporary) != expected:
                raise RuntimeError(f"Downloaded wheel hash mismatch: {filename}")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    verify()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the local wheel set without network access",
    )
    arguments = parser.parse_args()
    verify() if arguments.check else sync()
    print(f"Verified {len(_locked_hashes())} media wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
