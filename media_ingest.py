"""FFmpeg media-to-thumbnail-cache conversion with no Blender UI dependency."""

from __future__ import annotations

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
    bounded_sample_indices,
    clamp_preview_fps,
    frame_interval_ms,
    target_sample_fps,
)
from .media_probe import MediaProbe, parse_ffmpeg_probe
from .paths import cache_root


def _ffmpeg_probe(executable: str, input_args: list[str]) -> MediaProbe:
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
    return parse_ffmpeg_probe(f"{result.stderr}\n{result.stdout}")


def _escape_concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _sequence_input_args(
    source_paths: tuple[Path, ...],
    staging_dir: Path,
    frame_duration_seconds: float,
) -> list[str]:
    concat_path = staging_dir / "sequence.ffconcat"
    lines = ["ffconcat version 1.0"]
    for path in source_paths:
        lines.append(f"file '{_escape_concat_path(path)}'")
        lines.append(f"duration {max(0.000001, frame_duration_seconds):.9f}")
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
        is_sequence = len(sources) > 1
        sequence_sources = (
            tuple(
                sources[index]
                for index in bounded_sample_indices(
                    len(sources),
                    MAX_SAMPLED_FRAMES,
                )
            )
            if is_sequence
            else ()
        )
        sequence_duration_seconds = (
            len(sources) / float(resolved_target_fps) if is_sequence else 0.0
        )
        input_args = (
            _sequence_input_args(
                sequence_sources,
                staging_dir,
                sequence_duration_seconds / len(sequence_sources),
            )
            if is_sequence
            else _single_input_args(sources[0])
        )
        probe = _ffmpeg_probe(executable, input_args)
        duration_seconds = probe.duration_seconds
        width = probe.width
        height = probe.height
        source_fps = 0.0 if is_sequence else probe.source_fps
        if is_sequence:
            duration_seconds = sequence_duration_seconds

        sample_fps = target_sample_fps(
            duration_seconds,
            resolved_target_fps,
            MAX_SAMPLED_FRAMES,
            source_fps=source_fps,
        )
        output_pattern = staging_dir / "raw_%05d.png"
        filter_chain = (
            ("" if is_sequence else f"fps={sample_fps:.8f},")
            + f"scale={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
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
            str(len(sequence_sources) if is_sequence else MAX_SAMPLED_FRAMES),
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
            frame_duration_ms = frame_interval_ms(sample_fps)
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
            source_fps=source_fps,
            sample_fps=sample_fps,
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
            "source_fps": source_fps,
            "sample_fps": sample_fps,
            "effective_fps": (
                (len(records) * 1000.0) / records[-1].end_ms
                if len(records) > 1
                else 0.0
            ),
        }
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
