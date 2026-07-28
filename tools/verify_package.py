"""Verify that a built Blender extension archive is installable and clean."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

REQUIRED_FILES = {
    "__init__.py",
    "animated_webp.py",
    "auto_load.py",
    "blender_manifest.toml",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
}
REJECTED_PARTS = {
    ".git",
    ".github",
    ".venv",
    "__pycache__",
    "tests",
    "tools",
}
REJECTED_SUFFIXES = {
    ".bat",
    ".blend1",
    ".blend2",
    ".blend3",
    ".log",
    ".pyc",
    ".pyo",
    ".sh",
    ".zip",
}
WHEEL_HASHES_PATH = Path(__file__).with_name("wheel_hashes.json")


def _wheel_hashes() -> dict[str, str]:
    return json.loads(WHEEL_HASHES_PATH.read_text(encoding="utf-8"))


def verify_package(path: Path) -> tuple[str, str, int]:
    """Return extension ID, version, and file count after validating an archive."""
    with zipfile.ZipFile(path) as archive:
        names = {
            str(PurePosixPath(name))
            for name in archive.namelist()
            if name and not name.endswith("/")
        }
        missing = sorted(REQUIRED_FILES - names)
        if missing:
            raise ValueError(f"Archive is missing required files: {', '.join(missing)}")
        rejected = sorted(
            name
            for name in names
            if REJECTED_PARTS.intersection(PurePosixPath(name).parts)
            or PurePosixPath(name).suffix.lower() in REJECTED_SUFFIXES
        )
        if rejected:
            raise ValueError(
                "Archive contains development/generated files: " + ", ".join(rejected)
            )
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        declared_wheels = {
            str(PurePosixPath(value).name) for value in manifest.get("wheels", ())
        }
        archived_wheels = {
            PurePosixPath(name).name
            for name in names
            if PurePosixPath(name).suffix.lower() == ".whl"
        }
        undeclared_wheels = sorted(archived_wheels - declared_wheels)
        if undeclared_wheels:
            raise ValueError(
                "Archive contains undeclared wheels: " + ", ".join(undeclared_wheels)
            )
        hashes = _wheel_hashes()
        unknown_wheels = sorted(archived_wheels - hashes.keys())
        if unknown_wheels:
            raise ValueError(
                "Archive contains unlocked wheels: " + ", ".join(unknown_wheels)
            )
        for name in sorted(archived_wheels):
            digest = hashlib.sha256(archive.read(f"wheels/{name}")).hexdigest()
            if digest != hashes[name]:
                raise ValueError(f"Archive wheel hash mismatch: {name}")
    return str(manifest["id"]), str(manifest["version"]), len(names)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    arguments = parser.parse_args()
    extension_id, version, file_count = verify_package(arguments.archive)
    print(f"Verified {extension_id} {version}: {file_count} clean installable files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
