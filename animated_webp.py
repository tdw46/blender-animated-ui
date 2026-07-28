"""Animated WebP inspection and isolated Pillow frame extraction."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PILLOW_EXTRACT_CODE = r"""
import json
import sys
from pathlib import Path

dependency_directory = sys.argv[1]
source_path = Path(sys.argv[2])
output_directory = Path(sys.argv[3])
if dependency_directory:
    sys.path.insert(0, dependency_directory)

from PIL import Image

output_directory.mkdir(parents=True, exist_ok=True)
paths = []
with Image.open(source_path) as image:
    frame_count = int(getattr(image, "n_frames", 1) or 1)
    if not bool(getattr(image, "is_animated", False)) or frame_count <= 1:
        raise RuntimeError("The selected WebP is not animated")
    for index in range(frame_count):
        image.seek(index)
        frame = image.convert("RGBA")
        path = output_directory / f"webp_{index:06d}.png"
        frame.save(path, format="PNG", compress_level=1)
        paths.append(str(path))

print(json.dumps({"frame_count": frame_count, "paths": paths}))
"""


@dataclass(frozen=True, slots=True)
class AnimatedWebPInfo:
    """Container metadata needed before Pillow decodes the animation."""

    width: int
    height: int
    durations_ms: tuple[int, ...]
    has_alpha: bool

    @property
    def frame_count(self) -> int:
        return len(self.durations_ms)

    @property
    def duration_ms(self) -> int:
        return sum(self.durations_ms)

    @property
    def source_fps(self) -> float:
        if self.duration_ms <= 0:
            return 0.0
        return (self.frame_count * 1000.0) / self.duration_ms


def _uint24(value: bytes) -> int:
    return int.from_bytes(value, byteorder="little", signed=False)


def inspect_animated_webp(source_path: str | Path) -> AnimatedWebPInfo | None:
    """Return fast RIFF metadata when a source is an animated WebP."""
    path = Path(source_path).expanduser().resolve()
    if path.suffix.casefold() != ".webp" or not path.is_file():
        return None

    width = 0
    height = 0
    has_alpha = False
    has_animation_flag = False
    has_animation_chunk = False
    durations: list[int] = []

    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            return None

        while True:
            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                break
            fourcc = chunk_header[:4]
            chunk_size = int.from_bytes(
                chunk_header[4:8],
                byteorder="little",
                signed=False,
            )
            payload_start = handle.tell()

            if fourcc == b"VP8X" and chunk_size >= 10:
                payload = handle.read(10)
                flags = payload[0]
                has_alpha = bool(flags & 0x10)
                has_animation_flag = bool(flags & 0x02)
                width = 1 + _uint24(payload[4:7])
                height = 1 + _uint24(payload[7:10])
            elif fourcc == b"ANIM" and chunk_size >= 6:
                payload = handle.read(6)
                has_animation_chunk = True
                has_alpha = has_alpha or payload[3] < 255
            elif fourcc == b"ANMF" and chunk_size >= 16:
                payload = handle.read(16)
                duration_ms = _uint24(payload[12:15])
                # The WebP specification leaves tiny durations implementation
                # defined. Browsers commonly normalize 0-10 ms to about 100 ms.
                durations.append(100 if duration_ms <= 10 else duration_ms)

            handle.seek(payload_start + chunk_size + (chunk_size & 1))

    if (
        not has_animation_flag
        or not has_animation_chunk
        or not durations
        or width <= 0
        or height <= 0
    ):
        return None
    return AnimatedWebPInfo(
        width=width,
        height=height,
        durations_ms=tuple(durations),
        has_alpha=has_alpha,
    )


def extract_animated_webp(
    source_path: str | Path,
    output_directory: str | Path,
    *,
    dependency_directory: str | Path | None = None,
    python_executable: str = sys.executable,
) -> tuple[Path, ...]:
    """Decode composited RGBA frames with Pillow in an isolated process."""
    source = Path(source_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    dependency = (
        str(Path(dependency_directory).expanduser().resolve())
        if dependency_directory
        else ""
    )
    result = subprocess.run(
        [
            python_executable,
            "-I",
            "-c",
            _PILLOW_EXTRACT_CODE,
            dependency,
            str(source),
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Pillow failed").strip()
        raise RuntimeError(
            "Animated WebP decoding requires the Pillow media wheel: " + detail[-4000:]
        )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        frame_count = int(payload["frame_count"])
        paths = tuple(Path(path) for path in payload["paths"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Pillow returned invalid animated WebP metadata") from error
    if (
        frame_count <= 1
        or len(paths) != frame_count
        or not all(path.is_file() for path in paths)
    ):
        raise RuntimeError("Pillow did not extract every animated WebP frame")
    return paths
