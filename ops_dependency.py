"""Runtime FFmpeg dependency installation and readiness helpers."""

from __future__ import annotations

import bpy

from . import ffmpeg_bridge
from .utils import set_status


def online_access_allowed() -> bool:
    return bool(getattr(bpy.app, "online_access", True))


def prepare_ffmpeg(context, operator) -> dict | None:
    """Return FFmpeg status, installing the wheel when permitted and necessary."""
    dependency_status = ffmpeg_bridge.status()
    if dependency_status.get("ready"):
        return dependency_status
    if not online_access_allowed():
        message = "FFmpeg is unavailable and Blender Online Access is disabled"
        set_status(context, message, "ERROR")
        operator.report({"ERROR"}, message)
        return None
    set_status(context, "Preparing the platform FFmpeg wheel…")
    success, detail = ffmpeg_bridge.install_wheel()
    dependency_status = ffmpeg_bridge.refresh_status()
    if not success or not dependency_status.get("ready"):
        set_status(context, detail, "ERROR")
        operator.report({"ERROR"}, "FFmpeg could not be prepared")
        return None
    return dependency_status


class ANIMTHUMB_OT_InstallFFmpeg(bpy.types.Operator):
    bl_idname = "animthumb.install_ffmpeg"
    bl_label = "Install FFmpeg Wheel"
    bl_description = (
        "Install the platform-specific imageio-ffmpeg wheel into this "
        "extension's persistent user storage"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not online_access_allowed():
            message = "Enable Online Access in Preferences before installing FFmpeg"
            set_status(context, message, "ERROR")
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        set_status(context, "Installing the platform FFmpeg wheel…")
        success, detail = ffmpeg_bridge.install_wheel()
        ffmpeg_bridge.refresh_status()
        if not success:
            set_status(context, detail, "ERROR")
            self.report({"ERROR"}, "FFmpeg wheel installation failed")
            return {"CANCELLED"}
        set_status(context, detail)
        self.report({"INFO"}, "FFmpeg wheel installed")
        return {"FINISHED"}
