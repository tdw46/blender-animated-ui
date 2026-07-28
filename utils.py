"""Small Blender-facing helpers shared by the extension's operator modules."""

from __future__ import annotations


def set_status(context, message: str, level: str = "INFO") -> None:
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        wm.animthumb_status = str(message or "")
        wm.animthumb_status_level = str(level or "INFO").upper()
    from . import preview_engine

    preview_engine.tag_targeted_layout_refresh()


def find_scene_item(scene, item_id: str):
    for item in getattr(scene, "animthumb_items", ()):
        if str(getattr(item, "item_id", "") or "") == str(item_id):
            return item
    return None


def invoke_props_dialog_compat(
    context,
    operator,
    *,
    width: int,
    title: str,
    confirm_text: str,
):
    """Use modern popup labels while retaining the Blender 4.2 fallback."""
    invoke_props_dialog = context.window_manager.invoke_props_dialog
    try:
        return invoke_props_dialog(
            operator,
            width=width,
            title=title,
            confirm_text=confirm_text,
        )
    except TypeError:
        try:
            return invoke_props_dialog(operator, width=width)
        except TypeError:
            return invoke_props_dialog(operator)
