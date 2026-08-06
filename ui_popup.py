"""Close-safe animated properties-dialog example."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty


def _find_item(scene, item_id: str):
    resolved_item_id = str(item_id or "")
    return next(
        (
            item
            for item in getattr(scene, "animthumb_items", ())
            if str(item.item_id) == resolved_item_id
        ),
        None,
    )


class ANIMTHUMB_OT_show_animated_popup(bpy.types.Operator):
    """Display one cached gallery item in a safely owned animated dialog."""

    bl_idname = "animthumb.show_animated_popup"
    bl_label = "Show Animated Popup"
    bl_description = "Show this thumbnail in a close-safe animated dialog example"
    bl_options = {"INTERNAL"}

    item_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.scene, "animthumb_items", ()))

    def invoke(self, context, _event):
        from . import preview_cache, preview_engine

        item = _find_item(context.scene, self.item_id)
        if item is None:
            items = tuple(getattr(context.scene, "animthumb_items", ()))
            item = items[0] if items else None
        if item is None or preview_cache.load_item(item) is None:
            self.report({"ERROR"}, "The animated preview is unavailable.")
            return {"CANCELLED"}
        self.item_id = str(item.item_id)
        preview_engine.capture_popup_context(context, self)
        invoke_props_dialog = context.window_manager.invoke_props_dialog
        try:
            return invoke_props_dialog(
                self,
                width=520,
                title=str(item.name or "Animated Preview").upper(),
                confirm_text="Close",
            )
        except TypeError:
            try:
                return invoke_props_dialog(self, width=520)
            except TypeError:
                return invoke_props_dialog(self)

    def draw(self, context):
        from . import preview_cache, preview_engine

        item = _find_item(context.scene, self.item_id)
        if item is None:
            self.layout.label(text="The preview item is no longer available.")
            return
        preview_engine.register_popup_region(context, self.item_id, self)
        _preview_tick = int(
            getattr(context.window_manager, "animthumb_preview_tick", 0) or 0
        )
        del _preview_tick
        icon_id = preview_cache.icon_id(
            self.item_id,
            preview_engine.current_preview_ms(),
            fps_limit=preview_engine.preview_frame_rate(),
        )
        content = self.layout.row(align=False)
        icon_column = content.column(align=True)
        icon_column.ui_units_x = 9.0
        if icon_id:
            icon_column.template_icon(icon_value=icon_id, scale=8.0)
        else:
            icon_column.label(text="Preview unavailable", icon="IMAGE_DATA")
        details = content.column(align=True)
        details.separator(factor=1.2)
        details.label(text="Animated properties-dialog example")
        details.label(text=f"{int(item.frame_count)} cached frames", icon="TIME")
        details.label(text="Cancel and confirm both release the popup safely.")

    def execute(self, _context):
        from . import preview_engine

        preview_engine.release_popup_region(self)
        return {"FINISHED"}

    def cancel(self, _context):
        from . import preview_engine

        preview_engine.release_popup_region(self)
