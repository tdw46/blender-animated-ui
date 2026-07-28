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
    DEFAULT_STATIC_FRAME_MS,
    MAX_PREVIEW_FPS,
    MAX_THUMBNAIL_EDGE,
)
from .frame_rate import (
    clamp_preview_fps,
    frame_interval_ms,
    target_sample_fps,
)
from .media_probe import MediaProbe, parse_ffmpeg_probe
from .media_selection import DEFAULT_SEQUENCE_ORDER
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


def _ffmpeg_packet_probe(executable: str, source_path: Path) -> MediaProbe:
    result = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "copy",
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


def probe_media(executable: str, source_path: str | Path) -> MediaProbe:
    """Probe one selected media file without generating a cache."""
    path = Path(source_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if not executable or not Path(executable).is_file():
        raise FileNotFoundError(f"FFmpeg executable is unavailable: {executable}")
    probe = _ffmpeg_probe(executable, _single_input_args(path))
    if (
        probe.duration_seconds <= 0.0
        and probe.source_fps > 0.0
        and probe.frame_count <= 1
    ):
        counted = _ffmpeg_packet_probe(executable, path)
        if counted.frame_count > 1:
            return MediaProbe(
                duration_seconds=counted.frame_count / counted.source_fps,
                width=counted.width,
                height=counted.height,
                source_fps=counted.source_fps,
                has_alpha=counted.has_alpha,
                frame_count=counted.frame_count,
            )
    return probe


def _trimmed_sources(
    sources: tuple[Path, ...],
    *,
    trim_media: bool,
    trim_start_frame: int,
    trim_end_frame: int,
) -> tuple[Path, ...]:
    if not trim_media:
        return sources
    start_index = min(len(sources) - 1, max(0, int(trim_start_frame) - 1))
    requested_end = int(trim_end_frame)
    end_index = len(sources) if requested_end <= 0 else min(len(sources), requested_end)
    if end_index <= start_index:
        raise ValueError("End Frame must be the same as or later than Begin Frame")
    return sources[start_index:end_index]


def _trim_filter(
    *,
    trim_media: bool,
    trim_start_frame: int,
    trim_end_frame: int,
) -> str:
    if not trim_media:
        return ""
    start_index = max(0, int(trim_start_frame) - 1)
    end_frame = max(0, int(trim_end_frame))
    trim = f"trim=start_frame={start_index}"
    if end_frame > 0:
        if end_frame <= start_index:
            raise ValueError("End Frame must be the same as or later than Begin Frame")
        trim += f":end_frame={end_frame}"
    return f"{trim},setpts=PTS-STARTPTS,"


def _cache_image_settings(has_alpha: bool) -> tuple[str, str, str, list[str]]:
    if has_alpha:
        return (
            "webp",
            "WEBP",
            "color=0x00000000",
            [
                "-c:v",
                "libwebp",
                "-quality",
                "82",
                "-compression_level",
                "4",
            ],
        )
    return (
        "jpg",
        "JPEG",
        "color=0x000000",
        ["-q:v", "3"],
    )


def ingest_media(
    executable: str,
    source_paths: Iterable[str | Path],
    *,
    display_name: str = "",
    target_fps: int = MAX_PREVIEW_FPS,
    cache_item_id: str = "",
    sequence_order: str = DEFAULT_SEQUENCE_ORDER,
    trim_media: bool = False,
    trim_start_frame: int = 1,
    trim_end_frame: int = 0,
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

    item_id = str(cache_item_id or "").strip() or stable_item_id(sources)
    name = display_name.strip() or (
        sources[0].parent.name if len(sources) > 1 else sources[0].stem
    )
    safe_name = safe_cache_name(name)
    root = cache_root()
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{safe_name}_{item_id}_", dir=root))

    try:
        is_sequence = len(sources) > 1
        sequence_sources = (
            _trimmed_sources(
                sources,
                trim_media=trim_media,
                trim_start_frame=trim_start_frame,
                trim_end_frame=trim_end_frame,
            )
            if is_sequence
            else ()
        )
        source_duration_seconds = (
            len(sources) / float(resolved_target_fps) if is_sequence else 0.0
        )
        input_args = (
            _sequence_input_args(
                sequence_sources,
                staging_dir,
                1.0 / float(resolved_target_fps),
            )
            if is_sequence
            else _single_input_args(sources[0])
        )
        probe = (
            _ffmpeg_probe(executable, input_args)
            if is_sequence
            else probe_media(executable, sources[0])
        )
        if not is_sequence:
            source_duration_seconds = probe.duration_seconds
        width = probe.width
        height = probe.height
        source_fps = 0.0 if is_sequence else probe.source_fps

        sample_fps = target_sample_fps(
            source_duration_seconds,
            resolved_target_fps,
            1,
            source_fps=source_fps,
        )
        extension, cache_format, pad_color, output_args = _cache_image_settings(
            probe.has_alpha
        )
        output_pattern = staging_dir / f"raw_%05d.{extension}"
        filter_chain = (
            (
                ""
                if is_sequence
                else _trim_filter(
                    trim_media=trim_media,
                    trim_start_frame=trim_start_frame,
                    trim_end_frame=trim_end_frame,
                )
                + f"fps={sample_fps:.8f},"
            )
            + f"scale={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
            "force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
            f"(ow-iw)/2:(oh-ih)/2:{pad_color},"
            + ("format=rgba" if probe.has_alpha else "format=yuvj420p")
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
            "-vsync",
            "0" if is_sequence else "vfr",
        ]
        if is_sequence:
            command.extend(["-frames:v", str(len(sequence_sources))])
        command.extend([*output_args, str(output_pattern)])
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

        raw_frames = sorted(staging_dir.glob(f"raw_*.{extension}"))
        if not raw_frames:
            raise RuntimeError("FFmpeg produced no thumbnail frames")
        if is_sequence and len(raw_frames) != len(sequence_sources):
            raise RuntimeError(
                "FFmpeg did not preserve the selected image-sequence frame count: "
                f"expected {len(sequence_sources)}, got {len(raw_frames)}"
            )

        if len(raw_frames) > 1:
            frame_duration_ms = frame_interval_ms(sample_fps)
        else:
            frame_duration_ms = DEFAULT_STATIC_FRAME_MS

        renamed_paths: list[Path] = []
        cursor_ms = 0
        for index, raw_path in enumerate(raw_frames):
            end_ms = cursor_ms + frame_duration_ms
            destination = staging_dir / frame_filename(
                index,
                cursor_ms,
                end_ms,
                extension,
            )
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
            source_duration_ms=(
                max(1, int(round(source_duration_seconds * 1000.0)))
                if source_duration_seconds > 0.0
                else None
            ),
            media_kind="SEQUENCE" if is_sequence else "MEDIA",
            sequence_order=sequence_order if is_sequence else "",
            cache_image_format=cache_format,
            trim_media=trim_media,
            trim_start_frame=trim_start_frame,
            trim_end_frame=trim_end_frame,
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
            "source_duration_ms": (
                max(1, int(round(source_duration_seconds * 1000.0)))
                if source_duration_seconds > 0.0
                else 0
            ),
            "width": width,
            "height": height,
            "target_fps": resolved_target_fps,
            "source_fps": source_fps,
            "sample_fps": sample_fps,
            "media_kind": "SEQUENCE" if is_sequence else "MEDIA",
            "sequence_order": sequence_order if is_sequence else "",
            "cache_image_format": cache_format,
            "trim_media": bool(trim_media),
            "trim_start_frame": max(1, int(trim_start_frame)),
            "trim_end_frame": max(0, int(trim_end_frame)),
            "effective_fps": (
                (len(records) * 1000.0) / records[-1].end_ms
                if len(records) > 1
                else 0.0
            ),
        }
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
