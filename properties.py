"""RNA property definitions kept separate from runtime engines."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from .constants import (
    MAX_PREVIEW_FPS,
    MAX_PREVIEW_RAM_BUDGET_MB,
    MIN_PREVIEW_FPS,
    MIN_PREVIEW_RAM_BUDGET_MB,
)
from .gallery_query import (
    GALLERY_SORT_ITEMS,
    MEDIA_TYPE_FILTER_ITEMS,
)
from .gallery_settings import (
    DEFAULT_GALLERY_SETTINGS,
    MAX_THUMBNAIL_SCALE,
    MIN_THUMBNAIL_SCALE,
)


def _update_gallery_settings(_owner, _context) -> None:
    from . import preview_engine

    preview_engine.request_fast_reschedule()
    preview_engine.tag_targeted_redraw()
    preview_engine.tag_targeted_layout_refresh()


def _update_preview_ram_budget(_owner, _context) -> None:
    from . import preview_engine

    preview_engine.apply_preview_ram_budget()
    _update_gallery_settings(None, _context)


def _update_gallery_query(owner, context) -> None:
    del owner
    scene = getattr(context, "scene", None)
    if scene is not None and hasattr(scene, "animthumb_gallery_page"):
        scene.animthumb_gallery_page = 0
    _update_gallery_settings(None, context)


def reset_gallery_settings(context) -> None:
    """Restore every settings-cog control to its shared default."""
    wm = context.window_manager
    defaults = DEFAULT_GALLERY_SETTINGS
    values = (
        ("animthumb_gallery_search", defaults.search_text),
        ("animthumb_gallery_media_type", defaults.media_type),
        ("animthumb_gallery_sort", defaults.sort_mode),
        ("animthumb_thumbnail_scale", defaults.thumbnail_scale),
        ("animthumb_preview_fps", defaults.preview_fps),
        ("animthumb_preview_ram_budget_mb", defaults.preview_ram_budget_mb),
        ("animthumb_optimized_playback", defaults.optimized_playback),
    )
    changed = False
    for property_name, default_value in values:
        if getattr(wm, property_name) != default_value:
            setattr(wm, property_name, default_value)
            changed = True
    scene = getattr(context, "scene", None)
    if scene is not None and hasattr(scene, "animthumb_gallery_page"):
        scene.animthumb_gallery_page = 0
    if not changed:
        _update_gallery_settings(wm, context)


class ANIMTHUMB_PG_ThumbnailItem(bpy.types.PropertyGroup):
    item_id: StringProperty(name="Item ID", options={"HIDDEN"})
    name: StringProperty(name="Name")
    cache_dir: StringProperty(name="Cache Directory", subtype="DIR_PATH")
    source_path: StringProperty(name="Source", subtype="FILE_PATH")
    source_type: StringProperty(name="Source Type", default="OTHER")
    date_added_utc: StringProperty(name="Date Added", default="")
    frame_count: IntProperty(name="Frame Count", default=0, min=0)
    duration_ms: IntProperty(name="Duration (ms)", default=0, min=0)
    source_fps: FloatProperty(name="Source FPS", default=0.0, min=0.0, precision=3)
    effective_fps: FloatProperty(
        name="Effective FPS",
        default=0.0,
        min=0.0,
        precision=3,
    )
    width: IntProperty(name="Source Width", default=0, min=0)
    height: IntProperty(name="Source Height", default=0, min=0)


def register_properties() -> None:
    bpy.types.Scene.animthumb_items = CollectionProperty(
        type=ANIMTHUMB_PG_ThumbnailItem
    )
    bpy.types.Scene.animthumb_gallery_page = IntProperty(
        name="Gallery Page",
        default=0,
        min=0,
    )
    bpy.types.WindowManager.animthumb_preview_tick = IntProperty(
        name="Animated Preview Tick",
        default=0,
        options={"HIDDEN"},
    )
    bpy.types.WindowManager.animthumb_gallery_search = StringProperty(
        name="Search",
        description="Filter animated thumbnails by name",
        default=DEFAULT_GALLERY_SETTINGS.search_text,
        update=_update_gallery_query,
    )
    bpy.types.WindowManager.animthumb_gallery_media_type = EnumProperty(
        name="Media Type",
        description="Show only imported media of this source type",
        items=MEDIA_TYPE_FILTER_ITEMS,
        default=DEFAULT_GALLERY_SETTINGS.media_type,
        update=_update_gallery_query,
    )
    bpy.types.WindowManager.animthumb_gallery_sort = EnumProperty(
        name="Sort",
        description="Choose the animated thumbnail gallery order",
        items=GALLERY_SORT_ITEMS,
        default=DEFAULT_GALLERY_SETTINGS.sort_mode,
        update=_update_gallery_query,
    )
    bpy.types.WindowManager.animthumb_thumbnail_scale = FloatProperty(
        name="Thumbnail Scale",
        description="Scale thumbnails in the animated preview gallery",
        default=DEFAULT_GALLERY_SETTINGS.thumbnail_scale,
        min=MIN_THUMBNAIL_SCALE,
        max=MAX_THUMBNAIL_SCALE,
        soft_min=MIN_THUMBNAIL_SCALE,
        soft_max=MAX_THUMBNAIL_SCALE,
        step=5,
        precision=2,
        update=_update_gallery_settings,
    )
    bpy.types.WindowManager.animthumb_preview_fps = IntProperty(
        name="Live Playback FPS Ceiling",
        description=(
            "Maximum live gallery redraw and playback rate from 8 to 60 FPS; "
            "import sampling is configured per media item"
        ),
        default=DEFAULT_GALLERY_SETTINGS.preview_fps,
        min=MIN_PREVIEW_FPS,
        max=MAX_PREVIEW_FPS,
        soft_min=MIN_PREVIEW_FPS,
        soft_max=MAX_PREVIEW_FPS,
        step=1,
        update=_update_gallery_settings,
    )
    bpy.types.WindowManager.animthumb_preview_ram_budget_mb = IntProperty(
        name="Preview RAM Budget",
        description=(
            "Approximate decoded thumbnail-frame memory budget in MiB; active "
            "frames, short look-ahead windows, and one poster per item are retained"
        ),
        default=DEFAULT_GALLERY_SETTINGS.preview_ram_budget_mb,
        min=MIN_PREVIEW_RAM_BUDGET_MB,
        max=MAX_PREVIEW_RAM_BUDGET_MB,
        soft_min=MIN_PREVIEW_RAM_BUDGET_MB,
        soft_max=512,
        step=8,
        subtype="UNSIGNED",
        update=_update_preview_ram_budget,
    )
    bpy.types.WindowManager.animthumb_optimized_playback = BoolProperty(
        name="Optimized Playback Mode",
        description=(
            "Pause animated thumbnails during scene playback, real viewport "
            "interaction, and scrolling inside this gallery"
        ),
        default=DEFAULT_GALLERY_SETTINGS.optimized_playback,
        update=_update_gallery_settings,
    )
    bpy.types.WindowManager.animthumb_status = StringProperty(
        name="Animated Thumbnail Status",
        default="",
    )
    bpy.types.WindowManager.animthumb_status_level = StringProperty(
        name="Animated Thumbnail Status Level",
        default="INFO",
        options={"HIDDEN"},
    )


def unregister_properties() -> None:
    property_names = (
        (bpy.types.WindowManager, "animthumb_status_level"),
        (bpy.types.WindowManager, "animthumb_status"),
        (bpy.types.WindowManager, "animthumb_gallery_sort"),
        (bpy.types.WindowManager, "animthumb_gallery_media_type"),
        (bpy.types.WindowManager, "animthumb_gallery_search"),
        (bpy.types.WindowManager, "animthumb_optimized_playback"),
        (bpy.types.WindowManager, "animthumb_preview_ram_budget_mb"),
        (bpy.types.WindowManager, "animthumb_preview_fps"),
        (bpy.types.WindowManager, "animthumb_thumbnail_scale"),
        (bpy.types.WindowManager, "animthumb_preview_tick"),
        (bpy.types.Scene, "animthumb_gallery_page"),
        (bpy.types.Scene, "animthumb_items"),
    )
    for owner, name in property_names:
        if hasattr(owner, name):
            delattr(owner, name)
