"""Blender-independent FFmpeg media-to-thumbnail-cache conversion."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .cache_format import (
    FrameRecord,
    build_uniform_records,
    frame_filename,
    read_metadata,
    safe_cache_name,
    stable_item_id,
    write_metadata,
)
from .constants import (
    DEFAULT_IMPORT_FPS,
    DEFAULT_STATIC_FRAME_MS,
    MAX_THUMBNAIL_EDGE,
)
from .frame_rate import frame_interval_ms, target_sample_fps
from .gallery_query import source_media_type
from .media_probe import MediaProbe, parse_ffmpeg_probe
from .media_selection import DEFAULT_SEQUENCE_ORDER
from .media_settings import MediaImportSettings
from .media_types import CacheImageProfile, IngestResult

CacheImageProfileResolver = Callable[[bool], CacheImageProfile]


@dataclass(frozen=True, slots=True)
class _ConversionPlan:
    input_args: tuple[str, ...]
    probe: MediaProbe
    sequence_sources: tuple[Path, ...]
    source_duration_seconds: float
    source_fps: float
    sample_fps: float
    image_profile: CacheImageProfile
    filter_chain: str

    @property
    def is_sequence(self) -> bool:
        return bool(self.sequence_sources)


def default_cache_image_profile(has_alpha: bool) -> CacheImageProfile:
    """Return the small Blender-compatible cache profile used by the demo."""
    if has_alpha:
        return CacheImageProfile(
            extension="webp",
            metadata_format="WEBP",
            pad_color="color=0x00000000",
            ffmpeg_args=(
                "-c:v",
                "libwebp",
                "-quality",
                "82",
                "-compression_level",
                "4",
            ),
        )
    return CacheImageProfile(
        extension="jpg",
        metadata_format="JPEG",
        pad_color="color=0x000000",
        ffmpeg_args=("-q:v", "3"),
    )


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
    settings: MediaImportSettings,
) -> tuple[Path, ...]:
    if not settings.trim_media:
        return sources
    start_index = min(len(sources) - 1, settings.trim_start_frame - 1)
    end_index = (
        len(sources)
        if settings.trim_end_frame <= 0
        else min(len(sources), settings.trim_end_frame)
    )
    if end_index <= start_index:
        raise ValueError("End Frame must be the same as or later than Begin Frame")
    return sources[start_index:end_index]


def _trim_filter(settings: MediaImportSettings) -> str:
    if not settings.trim_media:
        return ""
    start_index = settings.trim_start_frame - 1
    trim = f"trim=start_frame={start_index}"
    if settings.trim_end_frame > 0:
        if settings.trim_end_frame <= start_index:
            raise ValueError("End Frame must be the same as or later than Begin Frame")
        trim += f":end_frame={settings.trim_end_frame}"
    return f"{trim},setpts=PTS-STARTPTS,"


def _resolve_cache_root(cache_directory: str | Path | None) -> Path:
    if cache_directory is None:
        from .paths import cache_root

        root = cache_root()
    else:
        root = Path(cache_directory).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    return root


def _date_added_utc(root: Path, item_id: str) -> str:
    """Preserve an existing item's original added date across atomic refreshes."""
    for metadata_path in root.glob("*/metadata.json"):
        try:
            metadata = read_metadata(metadata_path.parent)
        except (OSError, ValueError, KeyError):
            continue
        if str(metadata.get("item_id", "") or "") != item_id:
            continue
        existing = str(metadata.get("date_added_utc", "") or "").strip()
        if existing:
            return existing
        try:
            modified = metadata_path.stat().st_mtime
        except OSError:
            break
        return (
            datetime.fromtimestamp(modified, UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _build_conversion_plan(
    executable: str,
    sources: tuple[Path, ...],
    settings: MediaImportSettings,
    staging_dir: Path,
    image_profile_resolver: CacheImageProfileResolver,
) -> _ConversionPlan:
    is_sequence = len(sources) > 1
    sequence_sources = _trimmed_sources(sources, settings) if is_sequence else ()
    source_duration_seconds = (
        len(sources) / float(settings.target_fps) if is_sequence else 0.0
    )
    input_args = (
        _sequence_input_args(
            sequence_sources,
            staging_dir,
            1.0 / float(settings.target_fps),
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
    source_fps = 0.0 if is_sequence else probe.source_fps
    sample_fps = target_sample_fps(
        source_duration_seconds,
        settings.target_fps,
        1,
        source_fps=source_fps,
    )
    profile = image_profile_resolver(probe.has_alpha).normalized()
    rate_filter = (
        "" if is_sequence else f"{_trim_filter(settings)}fps={sample_fps:.8f},"
    )
    filter_chain = (
        rate_filter + f"scale={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
        "force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={MAX_THUMBNAIL_EDGE}:{MAX_THUMBNAIL_EDGE}:"
        f"(ow-iw)/2:(oh-ih)/2:{profile.pad_color},"
        + ("format=rgba" if probe.has_alpha else "format=yuvj420p")
    )
    return _ConversionPlan(
        input_args=tuple(input_args),
        probe=probe,
        sequence_sources=sequence_sources,
        source_duration_seconds=source_duration_seconds,
        source_fps=source_fps,
        sample_fps=sample_fps,
        image_profile=profile,
        filter_chain=filter_chain,
    )


def _run_conversion(
    executable: str,
    plan: _ConversionPlan,
    staging_dir: Path,
) -> tuple[Path, ...]:
    output_pattern = staging_dir / f"raw_%05d.{plan.image_profile.extension}"
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *plan.input_args,
        "-an",
        "-vf",
        plan.filter_chain,
        "-vsync",
        "0" if plan.is_sequence else "vfr",
    ]
    if plan.is_sequence:
        command.extend(["-frames:v", str(len(plan.sequence_sources))])
    command.extend([*plan.image_profile.ffmpeg_args, str(output_pattern)])
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

    raw_frames = tuple(
        sorted(staging_dir.glob(f"raw_*.{plan.image_profile.extension}"))
    )
    if not raw_frames:
        raise RuntimeError("FFmpeg produced no thumbnail frames")
    if plan.is_sequence and len(raw_frames) != len(plan.sequence_sources):
        raise RuntimeError(
            "FFmpeg did not preserve the selected image-sequence frame count: "
            f"expected {len(plan.sequence_sources)}, got {len(raw_frames)}"
        )
    return raw_frames


def _finalize_frame_records(
    raw_frames: tuple[Path, ...],
    staging_dir: Path,
    *,
    extension: str,
    sample_fps: float,
) -> tuple[FrameRecord, ...]:
    frame_duration_ms = (
        frame_interval_ms(sample_fps)
        if len(raw_frames) > 1
        else DEFAULT_STATIC_FRAME_MS
    )
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
    return build_uniform_records(renamed_paths, frame_duration_ms)


def _publish_cache(staging_dir: Path, final_dir: Path) -> None:
    backup_dir = final_dir.parent / f".{final_dir.name}.previous"
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


def ingest_media(
    executable: str,
    source_paths: Iterable[str | Path],
    *,
    display_name: str = "",
    target_fps: int = DEFAULT_IMPORT_FPS,
    cache_item_id: str = "",
    sequence_order: str = DEFAULT_SEQUENCE_ORDER,
    trim_media: bool = False,
    trim_start_frame: int = 1,
    trim_end_frame: int = 0,
    cache_directory: str | Path | None = None,
    image_profile_resolver: CacheImageProfileResolver | None = None,
) -> IngestResult:
    """Convert media into an atomic timed-image cache.

    Passing ``cache_directory`` keeps this pipeline independent of Blender.
    Omitting it resolves the extension's active persistent cache preference.
    """
    settings = MediaImportSettings(
        target_fps=target_fps,
        sequence_order=sequence_order,
        trim_media=trim_media,
        trim_start_frame=trim_start_frame,
        trim_end_frame=trim_end_frame,
    ).normalized()
    sources = tuple(Path(path).expanduser().resolve() for path in source_paths)
    if not sources:
        raise ValueError("No media files were selected")
    missing = tuple(path for path in sources if not path.is_file())
    if missing:
        raise FileNotFoundError(missing[0])
    if not executable or not Path(executable).is_file():
        raise FileNotFoundError(f"FFmpeg executable is unavailable: {executable}")

    item_id = str(cache_item_id or "").strip() or stable_item_id(sources)
    name = display_name.strip() or (
        sources[0].parent.name if len(sources) > 1 else sources[0].stem
    )
    safe_name = safe_cache_name(name)
    root = _resolve_cache_root(cache_directory)
    final_dir = root / f"{safe_name}_{item_id}"
    date_added_utc = _date_added_utc(root, item_id)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{safe_name}_{item_id}_", dir=root))
    profile_resolver = image_profile_resolver or default_cache_image_profile

    try:
        plan = _build_conversion_plan(
            executable,
            sources,
            settings,
            staging_dir,
            profile_resolver,
        )
        raw_frames = _run_conversion(executable, plan, staging_dir)
        records = _finalize_frame_records(
            raw_frames,
            staging_dir,
            extension=plan.image_profile.extension,
            sample_fps=plan.sample_fps,
        )
        source_duration_ms = (
            max(1, int(round(plan.source_duration_seconds * 1000.0)))
            if plan.source_duration_seconds > 0.0
            else 0
        )
        write_metadata(
            staging_dir,
            item_id=item_id,
            name=name,
            source_paths=sources,
            records=records,
            width=plan.probe.width,
            height=plan.probe.height,
            target_fps=settings.target_fps,
            source_fps=plan.source_fps,
            sample_fps=plan.sample_fps,
            source_duration_ms=source_duration_ms or None,
            media_kind="SEQUENCE" if plan.is_sequence else "MEDIA",
            source_type=source_media_type(sources, is_sequence=plan.is_sequence),
            date_added_utc=date_added_utc,
            sequence_order=settings.sequence_order if plan.is_sequence else "",
            cache_image_format=plan.image_profile.metadata_format,
            trim_media=settings.trim_media,
            trim_start_frame=settings.trim_start_frame,
            trim_end_frame=settings.trim_end_frame,
        )

        _publish_cache(staging_dir, final_dir)
        duration_ms = records[-1].end_ms
        return IngestResult(
            item_id=item_id,
            name=name,
            cache_dir=str(final_dir),
            frame_count=len(records),
            duration_ms=duration_ms,
            source_duration_ms=source_duration_ms,
            width=plan.probe.width,
            height=plan.probe.height,
            target_fps=settings.target_fps,
            source_fps=plan.source_fps,
            sample_fps=plan.sample_fps,
            media_kind="SEQUENCE" if plan.is_sequence else "MEDIA",
            source_type=source_media_type(sources, is_sequence=plan.is_sequence),
            date_added_utc=date_added_utc,
            sequence_order=settings.sequence_order if plan.is_sequence else "",
            cache_image_format=plan.image_profile.metadata_format,
            trim_media=settings.trim_media,
            trim_start_frame=settings.trim_start_frame,
            trim_end_frame=settings.trim_end_frame,
            effective_fps=(
                (len(records) * 1000.0) / duration_ms if len(records) > 1 else 0.0
            ),
        )
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
