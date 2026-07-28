"""Persistent cache discovery and Scene collection synchronization."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import bpy

from .cache_format import read_metadata
from .constants import GALLERY_PAGE_SIZE
from .frame_rate import effective_fps
from .gallery_query import source_media_type
from .paths import cache_root

_STARTUP_REFRESH_SCHEDULED = False


def _populate_item(item, cache_dir: Path, metadata: dict) -> None:
    item.item_id = str(metadata.get("item_id", "") or cache_dir.name)
    item.name = str(metadata.get("name", "") or cache_dir.name)
    item.cache_dir = str(cache_dir)
    source_paths = metadata.get("source_paths") or []
    item.source_path = str(source_paths[0]) if source_paths else ""
    item.source_type = str(metadata.get("source_type", "OTHER") or "OTHER").upper()
    item.date_added_utc = str(metadata.get("date_added_utc", "") or "")
    records = metadata.get("records") or ()
    item.frame_count = len(records)
    item.duration_ms = max(0, int(metadata.get("duration_ms", 0) or 0))
    item.source_fps = max(0.0, float(metadata.get("source_fps", 0.0) or 0.0))
    item.effective_fps = max(
        0.0,
        float(
            metadata.get("effective_fps", 0.0)
            or effective_fps(item.frame_count, item.duration_ms)
        ),
    )
    item.width = max(0, int(metadata.get("width", 0) or 0))
    item.height = max(0, int(metadata.get("height", 0) or 0))


def discover_caches() -> tuple[tuple[Path, dict], ...]:
    discovered: list[tuple[Path, dict]] = []
    for metadata_path in sorted(cache_root().glob("*/metadata.json")):
        try:
            metadata = read_metadata(metadata_path.parent)
        except (OSError, ValueError, KeyError):
            continue
        source_paths = metadata.get("source_paths") or ()
        metadata["source_type"] = str(
            metadata.get("source_type", "")
            or source_media_type(
                source_paths,
                is_sequence=str(metadata.get("media_kind", "")).upper() == "SEQUENCE",
            )
        ).upper()
        if not str(metadata.get("date_added_utc", "") or ""):
            try:
                modified = metadata_path.stat().st_mtime
            except OSError:
                modified = 0.0
            metadata["date_added_utc"] = (
                datetime.fromtimestamp(modified, UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
        discovered.append((metadata_path.parent, metadata))
    discovered.sort(key=lambda entry: str(entry[1].get("name", "")).casefold())
    discovered.sort(
        key=lambda entry: str(entry[1].get("date_added_utc", "") or ""),
        reverse=True,
    )
    return tuple(discovered)


def refresh_scene(scene) -> int:
    if scene is None or not hasattr(scene, "animthumb_items"):
        return 0
    discovered = discover_caches()
    scene.animthumb_items.clear()
    from . import preview_cache

    preview_cache.clear()
    for cache_dir, metadata in discovered:
        item = scene.animthumb_items.add()
        _populate_item(item, cache_dir, metadata)
        preview_cache.load_item(item)
    max_page = max(0, (len(discovered) - 1) // GALLERY_PAGE_SIZE)
    scene.animthumb_gallery_page = min(
        max(0, int(scene.animthumb_gallery_page)),
        max_page,
    )
    return len(discovered)


def refresh_all_scenes() -> int:
    count = 0
    for scene in getattr(bpy.data, "scenes", ()):
        count = max(count, refresh_scene(scene))
    return count


def remove_item(item_id: str) -> bool:
    target_dir: Path | None = None
    for cache_dir, metadata in discover_caches():
        if str(metadata.get("item_id", "") or "") == str(item_id):
            target_dir = cache_dir
            break
    if target_dir is None:
        return False
    from . import preview_cache

    preview_cache.unload_item(item_id)
    shutil.rmtree(target_dir)
    refresh_all_scenes()
    return True


def _startup_refresh() -> None:
    global _STARTUP_REFRESH_SCHEDULED
    _STARTUP_REFRESH_SCHEDULED = False
    try:
        refresh_all_scenes()
    except Exception as error:
        print(f"Animated thumbnails: startup refresh failed: {error}")
    return None


def schedule_startup_refresh() -> None:
    global _STARTUP_REFRESH_SCHEDULED
    if _STARTUP_REFRESH_SCHEDULED:
        return
    _STARTUP_REFRESH_SCHEDULED = True
    try:
        bpy.app.timers.register(_startup_refresh, first_interval=0.0)
    except Exception:
        _STARTUP_REFRESH_SCHEDULED = False


def cancel_startup_refresh() -> None:
    global _STARTUP_REFRESH_SCHEDULED
    try:
        if bpy.app.timers.is_registered(_startup_refresh):
            bpy.app.timers.unregister(_startup_refresh)
    except Exception:
        pass
    _STARTUP_REFRESH_SCHEDULED = False
