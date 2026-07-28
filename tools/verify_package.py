"""Verify that a built Blender extension archive is installable and clean."""

from __future__ import annotations

import argparse
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

REQUIRED_FILES = {
    "__init__.py",
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
