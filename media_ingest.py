"""FFmpeg media-to-thumbnail-cache conversion with no Blender UI dependency."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .cache_format import (
    build_uniform_records,
    frame_filename,
    safe_cache_name,
    stable_item_id,
    write_metadata,
)
from .constants import (
    DEFAULT_PREVIEW_FPS,
    DEFAULT_STATIC_FRAME_MS,
    MAX_SAMPLED_FRAMES,
    MAX_THUMBNAIL_EDGE,
)
from .frame_rate import (
    clamp_preview_fps,
    frame_interval_ms,
    target_sample_fps,
)
from .paths import cache_root

_DURATION_PATTERN = re.compile(
    r"Duration:\s*(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+(?:\.\d+)?)"
)
_DIMENSION_PATTERN = re.compile(r"(?<!\d)(?P<width>\d{2,6})x(?P<height>\d{2,6})(?!\d)")


def _ffmpeg_probe(executable: str, input_args: list[str]) -> tuple[float, int, int]:
    result = subprocess.run(
        [
            executable,
            "-hide_banner",
            *input_args,
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = f"{result.stderr}\n{result.stdout}"
    duration_seconds = 0.0
    duration_match = _DURATION_PATTERN.search(output)
    if duration_match is not None:
        duration_seconds = (
            int(duration_match.group("hours")) * 3600
            + int(duration_match.group("minutes")) * 60
            + float(duration_match.group("seconds"))
        )
    width = 0
    height = 0
    for match in _DIMENSION_PATTERN.finditer(output):
        candidate_width = int(match.group("width"))
        candidate_height = int(match.group("height"))
        if candidate_width > 0 and candidate_height > 0:
            width, height = candidate_width, candidate_height
            break
    return max(0.0, duration_seconds), width, height


def _escape_concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _sequence_input_args(
    source_paths: tuple[Path, ...],
    staging_dir: Path,
    target_fps: int,
) -> list[str]:
    concat_path = staging_dir / "sequence.ffconcat"
    lines = ["ffconcat version 1.0"]
    for path in source_paths:
        lines.append(f"file '{_escape_concat_path(path)}'")
        lines.append(f"duration {1.0 / float(target_fps):.9f}")
    lines.append(f"file '{_escape_concat_path(source_paths[-1])}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ["-f", "concat", "-safe", "0", "-i", str(concat_path)]


def _single_input_args(source_path: Path) -> list[str]:
    return ["-i", str(source_path)]


def ingest_media(
    executable: str,
    source_paths: Iterable[str | Path],
    *,
    display_name: str = "",
    target_fps: int = DEFAULT_PREVIEW_FPS,
) -> dict[str, object]:
    resolved_target_fps = clamp_preview_fps(target_fps)
    sources = tuple(Path(path).expanduser().resolve() for path in source_paths)
    if not sources:
        raise ValueError("No media files were selected")
    missing = [path for path in sources if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    if not executable or not Path(executable).is_file():
        raise FileNotFoundError(f"FFmpeg executable is unavailable: {executable}")

    item_id = stable_item_id(sources)
    name = display_name.strip() or (
        sources[0].parent.name if len(sources) > 1 else sources[0].stem
    )
    safe_name = safe_cache_name(name)
    root = cache_root()
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{safe_name}_{item_id}_", dir=root))

    try:
        input_args = (
            _sequence_input_args(sources, staging_dir, resolved_target_fps)
            if len(sources) > 1
            else _single_input_args(sources[0])
        )
        duration_seconds, width, height = _ffmpeg_probe(executable, input_args)
        if len(sources) > 1:
            duration_seconds = max(
                duration_seconds,
                len(sources) / float(resolved_target_fps),
            )

        sample_fps = target_sample_fps(
            duration_seconds,
            resolved_target_fps,
            MAX_SAMPLED_FRAMES,
        )
        output_pattern = staging_dir / "raw_%05d.png"
        filter_chain = (
            f"fps={sample_fps:.8f},"
            f"scale={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
            "force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
            "(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            "format=rgba"
        )
        command = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *input_args,
            "-an",
            "-vf",
            filter_chain,
            "-frames:v",
            str(MAX_SAMPLED_FRAMES),
            "-vsync",
            "vfr",
            str(output_pattern),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr or result.stdout or "FFmpeg failed"
            raise RuntimeError(detail.strip())

        raw_frames = sorted(staging_dir.glob("raw_*.png"))
        if not raw_frames:
            raise RuntimeError("FFmpeg produced no thumbnail frames")

        if duration_seconds > 0.0:
            total_ms = max(1, int(round(duration_seconds * 1000.0)))
            frame_duration_ms = max(1, int(round(total_ms / len(raw_frames))))
        elif len(raw_frames) > 1:
            frame_duration_ms = frame_interval_ms(resolved_target_fps)
        else:
            frame_duration_ms = DEFAULT_STATIC_FRAME_MS

        renamed_paths: list[Path] = []
        cursor_ms = 0
        for index, raw_path in enumerate(raw_frames):
            end_ms = cursor_ms + frame_duration_ms
            destination = staging_dir / frame_filename(index, cursor_ms, end_ms)
            raw_path.replace(destination)
            renamed_paths.append(destination)
            cursor_ms = end_ms
        records = build_uniform_records(renamed_paths, frame_duration_ms)
        write_metadata(
            staging_dir,
            item_id=item_id,
            name=name,
            source_paths=sources,
            records=records,
            width=width,
            height=height,
            target_fps=resolved_target_fps,
        )

        final_dir = root / f"{safe_name}_{item_id}"
        backup_dir = root / f".{final_dir.name}.previous"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if final_dir.exists():
            final_dir.replace(backup_dir)
        try:
            staging_dir.replace(final_dir)
        except Exception:
            if backup_dir.exists() and not final_dir.exists():
                backup_dir.replace(final_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        return {
            "item_id": item_id,
            "name": name,
            "cache_dir": str(final_dir),
            "frame_count": len(records),
            "duration_ms": records[-1].end_ms,
            "width": width,
            "height": height,
            "target_fps": resolved_target_fps,
            "effective_fps": (
                (len(records) * 1000.0) / records[-1].end_ms
                if len(records) > 1
                else 0.0
            ),
        }
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
