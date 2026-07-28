"""Gallery pagination operators."""

from __future__ import annotations

import bpy
from bpy.props import IntProperty


class ANIMTHUMB_OT_SetGalleryPage(bpy.types.Operator):
    bl_idname = "animthumb.set_gallery_page"
    bl_label = "Set Animated Thumbnail Page"
    bl_options = {"INTERNAL"}

    page: IntProperty(default=0, min=0)

    def execute(self, context):
        context.scene.animthumb_gallery_page = max(0, int(self.page))
        from . import preview_engine

        preview_engine.tag_targeted_layout_refresh()
        return {"FINISHED"}
