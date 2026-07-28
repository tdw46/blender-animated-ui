"""Memory-only, incrementally loaded Blender preview collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from bpy.utils import previews

from .cache_format import FrameRecord, read_metadata
from .constants import (
    PREVIEW_LOAD_BATCH_INTERVAL_SECONDS,
    PREVIEW_LOAD_BATCH_SIZE,
    PREVIEW_LOOKAHEAD_FRAMES,
    PREVIEW_OFFSCREEN_GRACE_SECONDS,
)
from .frame_rate import (
    active_display_fps,
    effective_fps,
    frame_interval_ms,
    sampled_clock_ms,
)


@dataclass(slots=True)
class CachedPreview:
    item_id: str
    cache_dir: Path
    records: tuple[FrameRecord, ...]
    duration_ms: int
    source_fps: float
    effective_fps: float
    cache_revision: tuple[int, ...]
    poster_index: int
    loaded_indices: set[int]
    reachable_indices_by_fps: dict[float | None, tuple[int, ...]]

    @property
    def icon_keys(self) -> tuple[str, ...]:
        return tuple(
            _icon_key(self.item_id, record.index)
            for record in self.records
            if record.index in self.loaded_indices
        )


_COLLECTION = None
_ITEMS: dict[str, CachedPreview] = {}
_LAST_VISIBLE_MONOTONIC: dict[str, float] = {}
_LAST_PRELOAD_MONOTONIC = 0.0


def _icon_key(item_id: str, frame_index: int) -> str:
    return f"animthumb_{item_id}_{max(0, int(frame_index)):03d}"


def register_runtime() -> None:
    global _COLLECTION
    if _COLLECTION is None:
        _COLLECTION = previews.new()


def unregister_runtime() -> None:
    global _COLLECTION
    global _LAST_PRELOAD_MONOTONIC
    _ITEMS.clear()
    _LAST_VISIBLE_MONOTONIC.clear()
    _LAST_PRELOAD_MONOTONIC = 0.0
    if _COLLECTION is not None:
        try:
            previews.remove(_COLLECTION)
        except Exception:
            pass
    _COLLECTION = None


def clear() -> None:
    global _LAST_PRELOAD_MONOTONIC
    _ITEMS.clear()
    _LAST_VISIBLE_MONOTONIC.clear()
    _LAST_PRELOAD_MONOTONIC = 0.0
    if _COLLECTION is not None:
        try:
            _COLLECTION.clear()
        except Exception:
            pass


def unload_item(item_id: str) -> None:
    resolved_item_id = str(item_id)
    cached = _ITEMS.pop(resolved_item_id, None)
    _LAST_VISIBLE_MONOTONIC.pop(resolved_item_id, None)
    if cached is None or _COLLECTION is None:
        return
    for key in cached.icon_keys:
        try:
            if key in _COLLECTION:
                del _COLLECTION[key]
        except Exception:
            pass


def _cache_revision(cache_dir: Path) -> tuple[int, ...]:
    """Identify an atomically published cache without tracking metadata-only edits."""
    stat = cache_dir.stat()
    revision = [int(getattr(stat, "st_dev", 0)), int(getattr(stat, "st_ino", 0))]
    first_frame = next(cache_dir.glob("frame_000__*"), None)
    if first_frame is not None:
        frame_stat = first_frame.stat()
        revision.extend(
            (
                int(getattr(frame_stat, "st_mtime_ns", 0)),
                int(getattr(frame_stat, "st_size", 0)),
            )
        )
    return tuple(revision)


def _record_for_index(cached: CachedPreview, frame_index: int) -> FrameRecord | None:
    for record in cached.records:
        if record.index == frame_index:
            return record
    return None


def _load_frame(cached: CachedPreview, frame_index: int) -> bool:
    if frame_index in cached.loaded_indices:
        return True
    record = _record_for_index(cached, frame_index)
    if record is None:
        return False
    if _COLLECTION is None:
        register_runtime()
    key = _icon_key(cached.item_id, record.index)
    try:
        if key in _COLLECTION:
            del _COLLECTION[key]
        _COLLECTION.load(key, str(record.path), "IMAGE")
    except Exception as error:
        print(
            "Animated thumbnails: could not load preview frame",
            {
                "item": cached.item_id,
                "frame": record.index,
                "error": str(error),
            },
        )
        return False
    cached.loaded_indices.add(record.index)
    return True


def _unload_frame(cached: CachedPreview, frame_index: int) -> None:
    if frame_index not in cached.loaded_indices:
        return
    cached.loaded_indices.discard(frame_index)
    if _COLLECTION is None:
        return
    key = _icon_key(cached.item_id, frame_index)
    try:
        if key in _COLLECTION:
            del _COLLECTION[key]
    except Exception:
        pass


def _frame_index_for_cached(
    cached: CachedPreview,
    now_ms: int,
    fps_limit: int | float | None,
) -> int:
    if not cached.records:
        return 0
    loop_ms = max(0, int(now_ms)) % cached.duration_ms
    item_fps_limit = _item_fps_limit(cached, fps_limit)
    if item_fps_limit is not None:
        loop_ms = sampled_clock_ms(loop_ms, item_fps_limit)
    for record in cached.records:
        if record.start_ms <= loop_ms < record.end_ms:
            return record.index
    return cached.records[-1].index


def _reachable_indices(
    cached: CachedPreview,
    fps_limit: int | float | None,
) -> tuple[int, ...]:
    item_fps_limit = _item_fps_limit(cached, fps_limit)
    cache_key = None if item_fps_limit is None else round(float(item_fps_limit), 6)
    existing = cached.reachable_indices_by_fps.get(cache_key)
    if existing is not None:
        return existing
    if len(cached.records) <= 1:
        resolved = tuple(record.index for record in cached.records)
    elif item_fps_limit is None:
        resolved = tuple(record.index for record in cached.records)
    else:
        interval_ms = frame_interval_ms(item_fps_limit)
        indices: list[int] = []
        seen: set[int] = set()
        for loop_ms in range(0, cached.duration_ms, interval_ms):
            index = _frame_index_for_cached(cached, loop_ms, fps_limit)
            if index not in seen:
                indices.append(index)
                seen.add(index)
        resolved = tuple(indices)
    cached.reachable_indices_by_fps[cache_key] = resolved
    return resolved


def load_item(
    item,
    *,
    force: bool = False,
    now_ms: int = 0,
    fps_limit: int | float | None = None,
) -> CachedPreview | None:
    item_id = str(getattr(item, "item_id", "") or "")
    cache_dir = Path(str(getattr(item, "cache_dir", "") or ""))
    if not item_id or not cache_dir:
        return None
    try:
        revision = _cache_revision(cache_dir)
    except OSError:
        return None
    existing = _ITEMS.get(item_id)
    if (
        existing is not None
        and not force
        and existing.cache_dir == cache_dir
        and existing.cache_revision == revision
    ):
        return existing
    if existing is not None:
        unload_item(item_id)
    if _COLLECTION is None:
        register_runtime()

    metadata = read_metadata(cache_dir)
    records = tuple(metadata["records"])
    if not records:
        return None
    cached = CachedPreview(
        item_id=item_id,
        cache_dir=cache_dir,
        records=records,
        duration_ms=max(1, int(records[-1].end_ms)),
        source_fps=max(0.0, float(metadata.get("source_fps", 0.0) or 0.0)),
        effective_fps=max(
            0.0,
            float(metadata.get("effective_fps", 0.0) or 0.0)
            or effective_fps(len(records), int(records[-1].end_ms)),
        ),
        cache_revision=revision,
        poster_index=records[0].index,
        loaded_indices=set(),
        reachable_indices_by_fps={},
    )
    _ITEMS[item_id] = cached
    poster_index = _frame_index_for_cached(cached, now_ms, fps_limit)
    cached.poster_index = poster_index
    if not _load_frame(cached, poster_index):
        _ITEMS.pop(item_id, None)
        return None
    return cached


def reconcile_items(
    items,
    *,
    now_ms: int,
    fps_limit: int | float | None,
) -> tuple[CachedPreview, ...]:
    """Retain unchanged previews and load one current poster for new caches."""
    loaded: list[CachedPreview] = []
    valid_ids: set[str] = set()
    for item in items:
        item_id = str(getattr(item, "item_id", "") or "")
        if not item_id:
            continue
        valid_ids.add(item_id)
        cached = load_item(item, now_ms=now_ms, fps_limit=fps_limit)
        if cached is not None:
            loaded.append(cached)
    for item_id in tuple(_ITEMS):
        if item_id not in valid_ids:
            unload_item(item_id)
    return tuple(loaded)


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


def display_frame_rate(
    item_id: str,
    *,
    fps_limit: int | float | None = None,
) -> float:
    """Return the rate this cache can visibly display under the live ceiling."""
    cached = _ITEMS.get(str(item_id))
    if cached is None or len(cached.records) <= 1:
        return 0.0
    return active_display_fps(
        cached.effective_fps,
        source_fps=cached.source_fps,
        requested_fps=fps_limit,
    )


def frame_index(
    item_id: str,
    now_ms: int,
    *,
    fps_limit: int | float | None = None,
) -> int:
    cached = _ITEMS.get(str(item_id))
    if cached is None or not cached.records:
        return 0
    return _frame_index_for_cached(cached, now_ms, fps_limit)


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
    loop_ms = max(0, int(now_ms)) % cached.duration_ms
    if item_fps_limit is None:
        current_index = _frame_index_for_cached(cached, now_ms, None)
        record = _record_for_index(cached, current_index)
        return max(1, int(record.end_ms - loop_ms)) if record is not None else 500
    interval_ms = frame_interval_ms(item_fps_limit)
    current_index = _frame_index_for_cached(cached, now_ms, item_fps_limit)
    next_boundary_ms = ((loop_ms // interval_ms) + 1) * interval_ms
    for candidate_ms in range(next_boundary_ms, cached.duration_ms, interval_ms):
        if (
            _frame_index_for_cached(cached, candidate_ms, item_fps_limit)
            != current_index
        ):
            return max(1, candidate_ms - loop_ms)
    first_index = _frame_index_for_cached(cached, 0, item_fps_limit)
    if first_index != current_index:
        return max(1, cached.duration_ms - loop_ms)
    for candidate_ms in range(interval_ms, cached.duration_ms, interval_ms):
        if (
            _frame_index_for_cached(cached, candidate_ms, item_fps_limit)
            != current_index
        ):
            return max(1, cached.duration_ms - loop_ms + candidate_ms)
    return 500


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
    _load_frame(cached, index)
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


def _rotated_reachable_indices(
    cached: CachedPreview,
    current_index: int,
    fps_limit: int | float | None,
) -> tuple[int, ...]:
    reachable = list(_reachable_indices(cached, fps_limit))
    if not reachable:
        return ()
    try:
        start = reachable.index(current_index)
    except ValueError:
        start = 0
    return tuple(reachable[start:] + reachable[:start])


def _trim_to_indices(cached: CachedPreview, retained: set[int]) -> None:
    for index in tuple(cached.loaded_indices):
        if index not in retained:
            _unload_frame(cached, index)


def service_visible_items(
    item_ids: tuple[str, ...],
    now_ms: int,
    *,
    fps_limit: int | float | None,
    now_monotonic: float | None = None,
) -> int:
    """Queue current/look-ahead frames, then gradually fill reachable frames."""
    global _LAST_PRELOAD_MONOTONIC
    current_monotonic = monotonic() if now_monotonic is None else now_monotonic
    visible: list[tuple[CachedPreview, int, tuple[int, ...]]] = []
    for item_id in dict.fromkeys(item_ids):
        cached = _ITEMS.get(str(item_id))
        if cached is None:
            continue
        _LAST_VISIBLE_MONOTONIC[cached.item_id] = current_monotonic
        current_index = _frame_index_for_cached(cached, now_ms, fps_limit)
        _load_frame(cached, current_index)
        ordered = _rotated_reachable_indices(cached, current_index, fps_limit)
        retained = set(ordered)
        retained.add(cached.poster_index)
        retained.add(current_index)
        _trim_to_indices(cached, retained)
        visible.append((cached, current_index, ordered))

    if (
        current_monotonic - _LAST_PRELOAD_MONOTONIC
        < PREVIEW_LOAD_BATCH_INTERVAL_SECONDS
    ):
        return 0
    _LAST_PRELOAD_MONOTONIC = current_monotonic
    candidates: list[tuple[CachedPreview, int]] = []
    seen_candidates: set[tuple[str, int]] = set()
    max_depth = max((len(ordered) for _cached, _current, ordered in visible), default=0)
    for depth in range(1, max_depth):
        for cached, _current_index, ordered in visible:
            if depth >= len(ordered):
                continue
            index = ordered[depth]
            key = (cached.item_id, index)
            if index in cached.loaded_indices or key in seen_candidates:
                continue
            candidates.append((cached, index))
            seen_candidates.add(key)
        if (
            depth >= PREVIEW_LOOKAHEAD_FRAMES
            and len(candidates) >= PREVIEW_LOAD_BATCH_SIZE
        ):
            break

    loaded_count = 0
    for cached, index in candidates[:PREVIEW_LOAD_BATCH_SIZE]:
        if _load_frame(cached, index):
            loaded_count += 1
    return loaded_count


def trim_offscreen_items(
    visible_item_ids: tuple[str, ...],
    *,
    now_monotonic: float | None = None,
) -> int:
    """Keep one poster for off-page items and release animation frames after grace."""
    current_monotonic = monotonic() if now_monotonic is None else now_monotonic
    visible_ids = set(visible_item_ids)
    trimmed_count = 0
    for item_id, cached in tuple(_ITEMS.items()):
        if item_id in visible_ids:
            _LAST_VISIBLE_MONOTONIC[item_id] = current_monotonic
            continue
        last_visible = _LAST_VISIBLE_MONOTONIC.get(item_id, 0.0)
        if (
            last_visible > 0.0
            and current_monotonic - last_visible < PREVIEW_OFFSCREEN_GRACE_SECONDS
        ):
            continue
        before = len(cached.loaded_indices)
        _trim_to_indices(cached, {cached.poster_index})
        trimmed_count += max(0, before - len(cached.loaded_indices))
    return trimmed_count


def loaded_frame_count(item_id: str) -> int:
    cached = _ITEMS.get(str(item_id))
    return len(cached.loaded_indices) if cached is not None else 0


def reachable_frame_count(
    item_id: str,
    *,
    fps_limit: int | float | None = None,
) -> int:
    cached = _ITEMS.get(str(item_id))
    return len(_reachable_indices(cached, fps_limit)) if cached is not None else 0


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
