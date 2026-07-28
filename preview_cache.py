"""Memory-only, incrementally loaded Blender preview collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from bpy.utils import previews

from .cache_format import FrameRecord, read_metadata
from .constants import (
    MAX_THUMBNAIL_EDGE,
    PREVIEW_DECODED_BYTES_PER_PIXEL,
    PREVIEW_FRAME_SETTLE_SECONDS,
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
    frame_bytes: dict[int, int]
    last_access_monotonic_by_index: dict[int, float]
    loaded_at_monotonic_by_index: dict[int, float]
    ever_loaded_indices: set[int]
    last_displayed_index: int | None

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
_FRAME_LOAD_COUNT = 0
_FRAME_RELOAD_COUNT = 0
_BUDGET_EVICTION_COUNT = 0
_CURRENT_FRAME_RELOAD_COUNT = 0
_DRAW_FRAME_RELOAD_COUNT = 0
_DISPLAY_FALLBACK_COUNT = 0
_LAST_REQUESTED_BUDGET_BYTES = 0
_LAST_EFFECTIVE_BUDGET_BYTES = 0


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
    _reset_statistics()


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
    _reset_statistics()


def _reset_statistics() -> None:
    global _FRAME_LOAD_COUNT
    global _FRAME_RELOAD_COUNT
    global _BUDGET_EVICTION_COUNT
    global _CURRENT_FRAME_RELOAD_COUNT
    global _DRAW_FRAME_RELOAD_COUNT
    global _DISPLAY_FALLBACK_COUNT
    global _LAST_REQUESTED_BUDGET_BYTES
    global _LAST_EFFECTIVE_BUDGET_BYTES
    _FRAME_LOAD_COUNT = 0
    _FRAME_RELOAD_COUNT = 0
    _BUDGET_EVICTION_COUNT = 0
    _CURRENT_FRAME_RELOAD_COUNT = 0
    _DRAW_FRAME_RELOAD_COUNT = 0
    _DISPLAY_FALLBACK_COUNT = 0
    _LAST_REQUESTED_BUDGET_BYTES = 0
    _LAST_EFFECTIVE_BUDGET_BYTES = 0


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
    global _FRAME_LOAD_COUNT
    global _FRAME_RELOAD_COUNT
    if frame_index in cached.loaded_indices:
        cached.last_access_monotonic_by_index[frame_index] = monotonic()
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
        preview = _COLLECTION.load(key, str(record.path), "IMAGE")
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
    image_size = tuple(int(value) for value in getattr(preview, "image_size", ()))
    if len(image_size) == 2 and image_size[0] > 0 and image_size[1] > 0:
        cached.frame_bytes[record.index] = (
            image_size[0] * image_size[1] * PREVIEW_DECODED_BYTES_PER_PIXEL
        )
    else:
        cached.frame_bytes[record.index] = (
            MAX_THUMBNAIL_EDGE * MAX_THUMBNAIL_EDGE * PREVIEW_DECODED_BYTES_PER_PIXEL
        )
    if record.index in cached.ever_loaded_indices:
        _FRAME_RELOAD_COUNT += 1
    cached.ever_loaded_indices.add(record.index)
    loaded_at = monotonic()
    cached.loaded_indices.add(record.index)
    cached.last_access_monotonic_by_index[record.index] = loaded_at
    cached.loaded_at_monotonic_by_index[record.index] = loaded_at
    _FRAME_LOAD_COUNT += 1
    return True


def _unload_frame(
    cached: CachedPreview,
    frame_index: int,
    *,
    budget_eviction: bool = False,
) -> None:
    global _BUDGET_EVICTION_COUNT
    if frame_index not in cached.loaded_indices:
        return
    cached.loaded_indices.discard(frame_index)
    cached.last_access_monotonic_by_index.pop(frame_index, None)
    cached.loaded_at_monotonic_by_index.pop(frame_index, None)
    if budget_eviction:
        _BUDGET_EVICTION_COUNT += 1
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
        frame_bytes={},
        last_access_monotonic_by_index={},
        loaded_at_monotonic_by_index={},
        ever_loaded_indices=set(),
        last_displayed_index=None,
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
    global _DRAW_FRAME_RELOAD_COUNT
    global _DISPLAY_FALLBACK_COUNT
    cached = _ITEMS.get(str(item_id))
    if cached is None or _COLLECTION is None:
        return 0
    index = frame_index(item_id, now_ms, fps_limit=fps_limit)
    if index not in cached.loaded_indices and index in cached.ever_loaded_indices:
        _DRAW_FRAME_RELOAD_COUNT += 1
    _load_frame(cached, index)
    display_index = index
    loaded_at = cached.loaded_at_monotonic_by_index.get(index, 0.0)
    fallback_index = cached.last_displayed_index
    if (
        loaded_at > 0.0
        and monotonic() - loaded_at < PREVIEW_FRAME_SETTLE_SECONDS
        and fallback_index is not None
        and fallback_index != index
        and fallback_index in cached.loaded_indices
    ):
        display_index = fallback_index
        _DISPLAY_FALLBACK_COUNT += 1
    key = _icon_key(item_id, display_index)
    try:
        if key in _COLLECTION:
            icon_value = max(0, int(getattr(_COLLECTION[key], "icon_id", 0) or 0))
            if display_index == index:
                cached.last_displayed_index = index
            return icon_value
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


def _trim_to_indices(
    cached: CachedPreview,
    retained: set[int],
    *,
    budget_eviction: bool = False,
) -> None:
    for index in tuple(cached.loaded_indices):
        if index not in retained:
            _unload_frame(
                cached,
                index,
                budget_eviction=budget_eviction,
            )


def _loaded_frame_bytes(cached: CachedPreview, frame_index: int) -> int:
    return max(
        1,
        int(
            cached.frame_bytes.get(
                frame_index,
                MAX_THUMBNAIL_EDGE
                * MAX_THUMBNAIL_EDGE
                * PREVIEW_DECODED_BYTES_PER_PIXEL,
            )
        ),
    )


def estimated_memory_bytes() -> int:
    return sum(
        _loaded_frame_bytes(cached, frame_index)
        for cached in _ITEMS.values()
        for frame_index in cached.loaded_indices
    )


def pagination_memory_estimate() -> dict[str, int]:
    """Return conservative decoded-frame costs for adaptive gallery paging."""
    fallback_bytes = (
        MAX_THUMBNAIL_EDGE * MAX_THUMBNAIL_EDGE * PREVIEW_DECODED_BYTES_PER_PIXEL
    )
    largest_frame_bytes = max(
        (
            max(cached.frame_bytes.values(), default=fallback_bytes)
            for cached in _ITEMS.values()
        ),
        default=fallback_bytes,
    )
    resident_poster_bytes = sum(
        _loaded_frame_bytes(cached, cached.poster_index)
        for cached in _ITEMS.values()
        if cached.poster_index in cached.loaded_indices
    )
    return {
        "largest_frame_bytes": largest_frame_bytes,
        "resident_poster_bytes": resident_poster_bytes,
    }


def memory_stats() -> dict[str, int | float]:
    loaded_frames = sum(len(cached.loaded_indices) for cached in _ITEMS.values())
    estimated_bytes = estimated_memory_bytes()
    return {
        "loaded_frames": loaded_frames,
        "estimated_bytes": estimated_bytes,
        "estimated_mebibytes": estimated_bytes / (1024.0 * 1024.0),
        "requested_budget_bytes": _LAST_REQUESTED_BUDGET_BYTES,
        "requested_budget_mebibytes": (
            _LAST_REQUESTED_BUDGET_BYTES / (1024.0 * 1024.0)
        ),
        "effective_budget_bytes": _LAST_EFFECTIVE_BUDGET_BYTES,
        "effective_budget_mebibytes": (
            _LAST_EFFECTIVE_BUDGET_BYTES / (1024.0 * 1024.0)
        ),
        "frame_loads": _FRAME_LOAD_COUNT,
        "frame_reloads": _FRAME_RELOAD_COUNT,
        "budget_evictions": _BUDGET_EVICTION_COUNT,
        "current_frame_reloads": _CURRENT_FRAME_RELOAD_COUNT,
        "draw_frame_reloads": _DRAW_FRAME_RELOAD_COUNT,
        "display_fallbacks": _DISPLAY_FALLBACK_COUNT,
    }


def enforce_ram_budget(
    active_item_ids: tuple[str, ...],
    now_ms: int,
    *,
    fps_limit: int | float | None,
    ram_budget_bytes: int | None,
) -> int:
    """Evict least-recently-used surplus frames while retaining playback windows."""
    global _LAST_EFFECTIVE_BUDGET_BYTES
    global _LAST_REQUESTED_BUDGET_BYTES
    if ram_budget_bytes is None:
        _LAST_REQUESTED_BUDGET_BYTES = 0
        _LAST_EFFECTIVE_BUDGET_BYTES = 0
        return 0
    requested_budget = max(1, int(ram_budget_bytes))
    _LAST_REQUESTED_BUDGET_BYTES = requested_budget

    active_ids = tuple(dict.fromkeys(str(item_id) for item_id in active_item_ids))
    active_set = set(active_ids)
    protected: set[tuple[str, int]] = set()
    for cached in _ITEMS.values():
        if cached.poster_index in cached.loaded_indices:
            protected.add((cached.item_id, cached.poster_index))
        if (
            cached.last_displayed_index is not None
            and cached.last_displayed_index in cached.loaded_indices
        ):
            protected.add((cached.item_id, cached.last_displayed_index))
    for item_id in active_ids:
        cached = _ITEMS.get(item_id)
        if cached is None:
            continue
        current_index = _frame_index_for_cached(cached, now_ms, fps_limit)
        ordered = _rotated_reachable_indices(cached, current_index, fps_limit)
        protected_indices = {current_index}
        protected_indices.update(ordered[: PREVIEW_LOOKAHEAD_FRAMES + 1])
        for frame_index in protected_indices:
            if frame_index in cached.loaded_indices:
                protected.add((cached.item_id, frame_index))
                cached.last_access_monotonic_by_index[frame_index] = monotonic()

    minimum_working_set_bytes = sum(
        _loaded_frame_bytes(_ITEMS[item_id], frame_index)
        for item_id, frame_index in protected
        if item_id in _ITEMS and frame_index in _ITEMS[item_id].loaded_indices
    )
    resolved_budget = max(requested_budget, minimum_working_set_bytes)
    _LAST_EFFECTIVE_BUDGET_BYTES = resolved_budget
    current_bytes = estimated_memory_bytes()
    if current_bytes <= resolved_budget:
        return 0

    candidates = sorted(
        (
            (
                1 if cached.item_id in active_set else 0,
                cached.last_access_monotonic_by_index.get(frame_index, 0.0),
                cached.item_id,
                frame_index,
            )
            for cached in _ITEMS.values()
            for frame_index in cached.loaded_indices
            if (cached.item_id, frame_index) not in protected
        ),
        key=lambda candidate: (
            candidate[0],
            candidate[1],
            candidate[2],
            candidate[3],
        ),
    )
    evicted = 0
    for _active_rank, _last_access, item_id, frame_index in candidates:
        if current_bytes <= resolved_budget:
            break
        cached = _ITEMS.get(item_id)
        if cached is None or frame_index not in cached.loaded_indices:
            continue
        current_bytes -= _loaded_frame_bytes(cached, frame_index)
        _unload_frame(cached, frame_index, budget_eviction=True)
        evicted += 1
    return evicted


def _active_resident_frame_limit(
    visible: list[tuple[CachedPreview, int, tuple[int, ...]]],
    ram_budget_bytes: int | None,
) -> int | None:
    if ram_budget_bytes is None or not visible:
        return None
    fallback_bytes = (
        MAX_THUMBNAIL_EDGE * MAX_THUMBNAIL_EDGE * PREVIEW_DECODED_BYTES_PER_PIXEL
    )
    largest_frame_bytes = max(
        (
            max(cached.frame_bytes.values(), default=fallback_bytes)
            for cached in _ITEMS.values()
        ),
        default=fallback_bytes,
    )
    total_slots = max(1, int(ram_budget_bytes) // max(1, largest_frame_bytes))
    active_ids = {cached.item_id for cached, _current, _ordered in visible}
    offscreen_poster_slots = sum(
        1
        for cached in _ITEMS.values()
        if cached.item_id not in active_ids
        and cached.poster_index in cached.loaded_indices
    )
    active_slots = max(1, total_slots - offscreen_poster_slots)
    return max(
        PREVIEW_LOOKAHEAD_FRAMES + 1,
        active_slots // max(1, len(visible)),
    )


def service_visible_items(
    item_ids: tuple[str, ...],
    now_ms: int,
    *,
    fps_limit: int | float | None,
    now_monotonic: float | None = None,
    ram_budget_bytes: int | None = None,
) -> int:
    """Queue current/look-ahead frames, then gradually fill reachable frames."""
    global _LAST_PRELOAD_MONOTONIC
    global _CURRENT_FRAME_RELOAD_COUNT
    current_monotonic = monotonic() if now_monotonic is None else now_monotonic
    visible: list[tuple[CachedPreview, int, tuple[int, ...]]] = []
    for item_id in dict.fromkeys(item_ids):
        cached = _ITEMS.get(str(item_id))
        if cached is None:
            continue
        _LAST_VISIBLE_MONOTONIC[cached.item_id] = current_monotonic
        current_index = _frame_index_for_cached(cached, now_ms, fps_limit)
        if (
            current_index not in cached.loaded_indices
            and current_index in cached.ever_loaded_indices
        ):
            _CURRENT_FRAME_RELOAD_COUNT += 1
        _load_frame(cached, current_index)
        ordered = _rotated_reachable_indices(cached, current_index, fps_limit)
        visible.append((cached, current_index, ordered))

    resident_limit = _active_resident_frame_limit(visible, ram_budget_bytes)
    bounded_visible: list[tuple[CachedPreview, int, tuple[int, ...]]] = []
    for cached, current_index, ordered in visible:
        bounded_ordered = (
            ordered if resident_limit is None else ordered[: max(1, resident_limit)]
        )
        retained = set(bounded_ordered)
        retained.add(cached.poster_index)
        retained.add(current_index)
        if cached.last_displayed_index is not None:
            retained.add(cached.last_displayed_index)
        _trim_to_indices(
            cached,
            retained,
            budget_eviction=resident_limit is not None,
        )
        bounded_visible.append((cached, current_index, bounded_ordered))
    visible = bounded_visible

    loaded_count = 0
    for cached, _current_index, ordered in visible:
        for frame_index in ordered[1 : PREVIEW_LOOKAHEAD_FRAMES + 1]:
            if frame_index not in cached.loaded_indices and _load_frame(
                cached, frame_index
            ):
                loaded_count += 1

    if (
        current_monotonic - _LAST_PRELOAD_MONOTONIC
        < PREVIEW_LOAD_BATCH_INTERVAL_SECONDS
    ):
        enforce_ram_budget(
            item_ids,
            now_ms,
            fps_limit=fps_limit,
            ram_budget_bytes=ram_budget_bytes,
        )
        return loaded_count
    _LAST_PRELOAD_MONOTONIC = current_monotonic
    candidates: list[tuple[CachedPreview, int]] = []
    seen_candidates: set[tuple[str, int]] = set()
    expected_consumed_frames = int(
        sum(
            active_display_fps(
                cached.effective_fps,
                source_fps=cached.source_fps,
                requested_fps=fps_limit,
            )
            for cached, _current, _ordered in visible
        )
        * PREVIEW_LOAD_BATCH_INTERVAL_SECONDS
        + 0.999
    )
    preload_batch_size = PREVIEW_LOAD_BATCH_SIZE + expected_consumed_frames
    max_depth = max((len(ordered) for _cached, _current, ordered in visible), default=0)
    for depth in range(PREVIEW_LOOKAHEAD_FRAMES + 1, max_depth):
        for cached, _current_index, ordered in visible:
            if depth >= len(ordered):
                continue
            index = ordered[depth]
            key = (cached.item_id, index)
            if index in cached.loaded_indices or key in seen_candidates:
                continue
            candidates.append((cached, index))
            seen_candidates.add(key)
        if depth >= PREVIEW_LOOKAHEAD_FRAMES and len(candidates) >= preload_batch_size:
            break

    for cached, index in candidates[:preload_batch_size]:
        if _load_frame(cached, index):
            loaded_count += 1
    enforce_ram_budget(
        item_ids,
        now_ms,
        fps_limit=fps_limit,
        ram_budget_bytes=ram_budget_bytes,
    )
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
