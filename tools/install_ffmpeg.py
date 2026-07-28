"""Install the platform imageio-ffmpeg wheel with the active Python runtime."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REQUIREMENT = "imageio-ffmpeg==0.6.0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Persistent extension-user dependency directory",
    )
    arguments = parser.parse_args()
    arguments.target.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--target",
        str(arguments.target),
        "--only-binary=:all:",
        "--no-cache-dir",
        REQUIREMENT,
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
