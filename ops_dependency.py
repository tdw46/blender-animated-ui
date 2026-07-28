"""Runtime FFmpeg dependency installation and readiness helpers."""

from __future__ import annotations

import bpy

from . import ffmpeg_bridge
from .utils import set_status


def online_access_allowed() -> bool:
    return bool(getattr(bpy.app, "online_access", True))


def prepare_ffmpeg(
    context,
    operator,
    *,
    require_pillow: bool = False,
) -> dict | None:
    """Return media-tool status, installing wheels when permitted and necessary."""
    dependency_status = ffmpeg_bridge.status()
    if dependency_status.get("ready") and (
        not require_pillow or dependency_status.get("pillow_ready")
    ):
        return dependency_status
    if not online_access_allowed():
        message = (
            "Pillow is required for animated WebP and Online Access is disabled"
            if require_pillow and dependency_status.get("ready")
            else "Media tools are unavailable and Blender Online Access is disabled"
        )
        set_status(context, message, "ERROR")
        operator.report({"ERROR"}, message)
        return None
    set_status(context, "Repairing the platform media wheels…")
    success, detail = ffmpeg_bridge.install_wheel()
    dependency_status = ffmpeg_bridge.refresh_status()
    tools_ready = dependency_status.get("ready") and (
        not require_pillow or dependency_status.get("pillow_ready")
    )
    if not success or not tools_ready:
        set_status(context, detail, "ERROR")
        operator.report({"ERROR"}, "Media tools could not be prepared")
        return None
    return dependency_status


class ANIMTHUMB_OT_InstallFFmpeg(bpy.types.Operator):
    bl_idname = "animthumb.install_ffmpeg"
    bl_label = "Repair Media Wheels"
    bl_description = (
        "Download compatible imageio-ffmpeg and Pillow repair wheels when "
        "the bundled manifest wheels are unavailable"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not online_access_allowed():
            message = (
                "Enable Online Access in Preferences before installing media tools"
            )
            set_status(context, message, "ERROR")
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        set_status(context, "Repairing the platform media wheels…")
        success, detail = ffmpeg_bridge.install_wheel()
        ffmpeg_bridge.refresh_status()
        if not success:
            set_status(context, detail, "ERROR")
            self.report({"ERROR"}, "Media wheel installation failed")
            return {"CANCELLED"}
        set_status(context, detail)
        self.report({"INFO"}, "Media wheels repaired")
        return {"FINISHED"}
