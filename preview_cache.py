"""Memory-only playback cache backed by one Blender preview collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bpy.utils import previews

from .cache_format import FrameRecord, read_metadata
from .frame_rate import sample_wait_ms, sampled_clock_ms


@dataclass(frozen=True, slots=True)
class CachedPreview:
    item_id: str
    cache_dir: Path
    records: tuple[FrameRecord, ...]
    icon_keys: tuple[str, ...]
    duration_ms: int
    source_fps: float
    effective_fps: float


_COLLECTION = None
_ITEMS: dict[str, CachedPreview] = {}


def _icon_key(item_id: str, frame_index: int) -> str:
    return f"animthumb_{item_id}_{max(0, int(frame_index)):03d}"


def register_runtime() -> None:
    global _COLLECTION
    if _COLLECTION is None:
        _COLLECTION = previews.new()


def unregister_runtime() -> None:
    global _COLLECTION
    _ITEMS.clear()
    if _COLLECTION is not None:
        try:
            previews.remove(_COLLECTION)
        except Exception:
            pass
    _COLLECTION = None


def clear() -> None:
    _ITEMS.clear()
    if _COLLECTION is not None:
        try:
            _COLLECTION.clear()
        except Exception:
            pass


def unload_item(item_id: str) -> None:
    cached = _ITEMS.pop(str(item_id), None)
    if cached is None or _COLLECTION is None:
        return
    for key in cached.icon_keys:
        try:
            if key in _COLLECTION:
                del _COLLECTION[key]
        except Exception:
            pass


def load_item(item, *, force: bool = False) -> CachedPreview | None:
    item_id = str(getattr(item, "item_id", "") or "")
    cache_dir = Path(str(getattr(item, "cache_dir", "") or ""))
    if not item_id or not cache_dir:
        return None
    existing = _ITEMS.get(item_id)
    if existing is not None and not force and existing.cache_dir == cache_dir:
        return existing
    if existing is not None:
        unload_item(item_id)
    if _COLLECTION is None:
        register_runtime()

    metadata = read_metadata(cache_dir)
    records = tuple(metadata["records"])
    icon_keys: list[str] = []
    for record in records:
        key = _icon_key(item_id, record.index)
        try:
            if key in _COLLECTION:
                del _COLLECTION[key]
            _COLLECTION.load(key, str(record.path), "IMAGE")
        except Exception as error:
            print(
                "Animated thumbnails: could not load preview frame",
                {"item": item_id, "frame": record.index, "error": str(error)},
            )
            continue
        icon_keys.append(key)
    if not icon_keys:
        return None
    cached = CachedPreview(
        item_id=item_id,
        cache_dir=cache_dir,
        records=records,
        icon_keys=tuple(icon_keys),
        duration_ms=max(1, int(records[-1].end_ms)),
        source_fps=max(0.0, float(metadata.get("source_fps", 0.0) or 0.0)),
        effective_fps=max(
            0.0,
            float(metadata.get("effective_fps", 0.0) or 0.0),
        ),
    )
    _ITEMS[item_id] = cached
    return cached


def is_loaded(item_id: str) -> bool:
    return str(item_id) in _ITEMS


def _item_fps_limit(
    cached: CachedPreview,
    requested_limit: int | float | None,
) -> int | float | None:
    limits: list[float] = []
    if requested_limit is not None:
        limits.append(max(0.01, float(requested_limit)))
    if cached.source_fps > 0.0:
        limits.append(cached.source_fps)
    return min(limits) if limits else None


def frame_index(
    item_id: str,
    now_ms: int,
    *,
    fps_limit: int | float | None = None,
) -> int:
    cached = _ITEMS.get(str(item_id))
    if cached is None or not cached.records:
        return 0
    item_fps_limit = _item_fps_limit(cached, fps_limit)
    loop_ms = sampled_clock_ms(now_ms, item_fps_limit) % cached.duration_ms
    for record in cached.records:
        if record.start_ms <= loop_ms < record.end_ms:
            return record.index
    return cached.records[-1].index


def milliseconds_until_next_frame(
    item_id: str,
    now_ms: int,
    *,
    fps_limit: int | float | None = None,
) -> int:
    cached = _ITEMS.get(str(item_id))
    if cached is None or len(cached.records) <= 1:
        return 500
    item_fps_limit = _item_fps_limit(cached, fps_limit)
    sampled_now_ms = sampled_clock_ms(now_ms, item_fps_limit)
    loop_ms = sampled_now_ms % cached.duration_ms
    for record in cached.records:
        if record.start_ms <= loop_ms < record.end_ms:
            return sample_wait_ms(
                now_ms,
                sampled_now_ms,
                record.end_ms - loop_ms,
                item_fps_limit,
            )
    return sample_wait_ms(
        now_ms,
        sampled_now_ms,
        cached.duration_ms - loop_ms + cached.records[0].end_ms,
        item_fps_limit,
    )


def icon_id(
    item_id: str,
    now_ms: int,
    *,
    fps_limit: int | float | None = None,
) -> int:
    cached = _ITEMS.get(str(item_id))
    if cached is None or _COLLECTION is None:
        return 0
    index = frame_index(item_id, now_ms, fps_limit=fps_limit)
    key = _icon_key(item_id, index)
    try:
        if key in _COLLECTION:
            return max(0, int(getattr(_COLLECTION[key], "icon_id", 0) or 0))
    except Exception:
        pass
    try:
        first_key = cached.icon_keys[0]
        return max(0, int(getattr(_COLLECTION[first_key], "icon_id", 0) or 0))
    except Exception:
        return 0


def frame_signature(
    item_ids: tuple[str, ...],
    now_ms: int,
    *,
    fps_limit: int | float | None = None,
) -> tuple[tuple[str, int], ...]:
    return tuple(
        (item_id, frame_index(item_id, now_ms, fps_limit=fps_limit))
        for item_id in item_ids
        if item_id in _ITEMS and len(_ITEMS[item_id].records) > 1
    )


def next_interval_seconds(
    item_ids: tuple[str, ...],
    now_ms: int,
    *,
    fps_limit: int | float | None = None,
) -> float:
    waits = [
        milliseconds_until_next_frame(
            item_id,
            now_ms,
            fps_limit=fps_limit,
        )
        for item_id in item_ids
        if item_id in _ITEMS and len(_ITEMS[item_id].records) > 1
    ]
    if not waits:
        return 0.5
    from .constants import PREVIEW_MIN_REDRAW_INTERVAL_SECONDS

    return max(
        PREVIEW_MIN_REDRAW_INTERVAL_SECONDS,
        min(min(waits) / 1000.0, 2.0),
    )
