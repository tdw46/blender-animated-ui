"""Typed public data returned by the media-ingest pipeline."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class CacheImageProfile:
    """FFmpeg output settings for one Blender-compatible cache image format."""

    extension: str
    metadata_format: str
    pad_color: str
    ffmpeg_args: tuple[str, ...]

    def normalized(self) -> CacheImageProfile:
        extension = str(self.extension or "").lower().lstrip(".")
        if extension not in {"png", "jpg", "jpeg", "webp"}:
            raise ValueError(f"Unsupported Blender preview cache format: {extension}")
        return CacheImageProfile(
            extension=extension,
            metadata_format=str(self.metadata_format or extension).upper(),
            pad_color=str(self.pad_color or "color=0x000000"),
            ffmpeg_args=tuple(str(value) for value in self.ffmpeg_args),
        )


@dataclass(frozen=True, slots=True)
class IngestResult(Mapping[str, object]):
    """Immutable conversion result with attribute and legacy mapping access."""

    item_id: str
    name: str
    cache_dir: str
    frame_count: int
    duration_ms: int
    source_duration_ms: int
    width: int
    height: int
    target_fps: int
    source_fps: float
    sample_fps: float
    media_kind: str
    sequence_order: str
    cache_image_format: str
    trim_media: bool
    trim_start_frame: int
    trim_end_frame: int
    effective_fps: float

    _KEYS: ClassVar[tuple[str, ...]] = (
        "item_id",
        "name",
        "cache_dir",
        "frame_count",
        "duration_ms",
        "source_duration_ms",
        "width",
        "height",
        "target_fps",
        "source_fps",
        "sample_fps",
        "media_kind",
        "sequence_order",
        "cache_image_format",
        "trim_media",
        "trim_start_frame",
        "trim_end_frame",
        "effective_fps",
    )

    def __getitem__(self, key: str) -> object:
        if key not in self._KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._KEYS)

    def __len__(self) -> int:
        return len(self._KEYS)

    def as_dict(self) -> dict[str, object]:
        """Return a detached dictionary for JSON or legacy consumers."""
        return asdict(self)
