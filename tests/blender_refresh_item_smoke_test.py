"""Rebuild one cache at a new per-item FPS without changing its identity."""

from __future__ import annotations

import os
from pathlib import Path

import addon_utils
import bpy

MODULE = os.environ.get(
    "ANIMTHUMB_MODULE",
    "bl_ext.user_default.blender_animated_ui",
)
sample_path = os.environ.get("ANIMTHUMB_SAMPLE_MEDIA", "")
if not sample_path:
    raise RuntimeError("ANIMTHUMB_SAMPLE_MEDIA is required")

addon_utils.enable(MODULE, default_set=True)
resolved_sample_path = Path(sample_path).resolve()
add_result = set(
    bpy.ops.animthumb.ingest_media(
        filepath=str(resolved_sample_path),
        display_name="Initial Imported Name",
        target_fps=30,
    )
)
if "FINISHED" not in add_result:
    raise RuntimeError(f"Initial ingest failed: {sorted(add_result)}")

items = tuple(
    item
    for item in bpy.context.scene.animthumb_items
    if Path(str(item.source_path)).resolve() == resolved_sample_path
)
if len(items) != 1:
    raise RuntimeError(f"Expected one matching cache, found {len(items)}")
item_id = str(items[0].item_id)
original_cache_dir = str(items[0].cache_dir)
if str(items[0].name) != "Initial Imported Name":
    raise RuntimeError("Initial ingest ignored Imported Name")

package = __import__(
    MODULE,
    fromlist=["cache_format", "library", "preview_cache"],
)
initial_cached_preview = package.preview_cache._ITEMS[item_id]
refresh_result = set(
    bpy.ops.animthumb.refresh_item(
        item_id=item_id,
        display_name="Refresh Imported Name",
        target_fps=12,
    )
)
if "FINISHED" not in refresh_result:
    raise RuntimeError(f"Per-item refresh failed: {sorted(refresh_result)}")

refreshed = next(
    (
        item
        for item in bpy.context.scene.animthumb_items
        if str(item.item_id) == item_id
    ),
    None,
)
if refreshed is None:
    raise RuntimeError("Refresh changed or removed the cache identity")
if str(refreshed.name) != "Refresh Imported Name":
    raise RuntimeError("Refresh ignored Imported Name")
if str(refreshed.cache_dir) != original_cache_dir:
    raise RuntimeError("Refresh moved the cache after its imported name changed")
if package.preview_cache._ITEMS[item_id] is initial_cached_preview:
    raise RuntimeError("Rebuilt item incorrectly retained its stale previews")
metadata = package.cache_format.read_metadata(str(refreshed.cache_dir))
if str(metadata.get("name", "")) != "Refresh Imported Name":
    raise RuntimeError("Refresh did not persist Imported Name")
if float(metadata.get("target_fps", 0.0)) != 12.0:
    raise RuntimeError("Refresh did not persist the new per-item FPS")
sample_fps = float(metadata.get("sample_fps", 0.0))
source_fps = float(metadata.get("source_fps", 0.0))
if sample_fps > 12.01 or (source_fps > 0.0 and sample_fps > source_fps * 1.01):
    raise RuntimeError("Refreshed cache exceeded its requested/native FPS")
source_duration_ms = int(metadata.get("source_duration_ms", 0) or 0)
preview_duration_ms = int(metadata.get("preview_duration_ms", 0) or 0)
duration_tolerance_ms = max(150, int(round(source_duration_ms * 0.05)))
if abs(preview_duration_ms - source_duration_ms) > duration_tolerance_ms:
    raise RuntimeError("Untrimmed refresh shortened the source preview window")
full_frame_count = int(refreshed.frame_count)
refreshed_cached_preview = package.preview_cache._ITEMS[item_id]
refreshed_loaded_count = package.preview_cache.loaded_frame_count(item_id)

rename_result = set(
    bpy.ops.animthumb.rename_item(
        item_id=item_id,
        new_name="Renamed Without Rebuild",
    )
)
if "FINISHED" not in rename_result:
    raise RuntimeError(f"Per-item rename failed: {sorted(rename_result)}")
renamed_item = next(
    item for item in bpy.context.scene.animthumb_items if str(item.item_id) == item_id
)
if str(renamed_item.name) != "Renamed Without Rebuild":
    raise RuntimeError("Per-item rename did not update the gallery item")
if str(renamed_item.cache_dir) != original_cache_dir:
    raise RuntimeError("Per-item rename moved the cache directory")
if package.preview_cache._ITEMS[item_id] is not refreshed_cached_preview:
    raise RuntimeError("Metadata-only rename replaced unchanged previews")
if package.preview_cache.loaded_frame_count(item_id) != refreshed_loaded_count:
    raise RuntimeError("Metadata-only rename reloaded preview frames")
renamed_metadata = package.cache_format.read_metadata(str(renamed_item.cache_dir))
if str(renamed_metadata.get("name", "")) != "Renamed Without Rebuild":
    raise RuntimeError("Per-item rename did not persist cache metadata")

trim_result = set(
    bpy.ops.animthumb.refresh_item(
        item_id=item_id,
        target_fps=12,
        trim_media=True,
        trim_start_frame=2,
        trim_end_frame=4,
    )
)
if "FINISHED" not in trim_result:
    raise RuntimeError(f"Trimmed per-item refresh failed: {sorted(trim_result)}")
trimmed_item = next(
    item for item in bpy.context.scene.animthumb_items if str(item.item_id) == item_id
)
trimmed_metadata = package.cache_format.read_metadata(str(trimmed_item.cache_dir))
if not bool(trimmed_metadata.get("trim_media", False)):
    raise RuntimeError("Trimmed refresh did not persist Trim Media")
if int(trimmed_metadata.get("trim_start_frame", 0)) != 2:
    raise RuntimeError("Trimmed refresh did not persist Begin Frame")
if int(trimmed_metadata.get("trim_end_frame", 0)) != 4:
    raise RuntimeError("Trimmed refresh did not persist End Frame")
if int(trimmed_metadata.get("preview_duration_ms", 0)) >= preview_duration_ms:
    raise RuntimeError("Explicit Trim Media did not shorten the preview window")

print(
    "ANIMTHUMB_REFRESH_ITEM",
    {
        "item_id_preserved": True,
        "imported_name_preserved": True,
        "rename_without_rebuild": True,
        "cache_directory_preserved": True,
        "target_fps": float(metadata["target_fps"]),
        "source_fps": source_fps,
        "sample_fps": sample_fps,
        "full_frame_count": full_frame_count,
        "trimmed_frame_count": int(trimmed_item.frame_count),
        "explicit_trim": [2, 4],
    },
)

if not package.library.remove_item(item_id):
    raise RuntimeError("Refresh smoke cache cleanup failed")
addon_utils.disable(MODULE)
