"""Efficient visible-only animated preview scheduler modeled on Beyond VRM."""

from __future__ import annotations

import ctypes
import sys
import time

import bpy
from bpy.app.handlers import persistent

from .constants import (
    PREVIEW_FRAME_CHANGE_THROTTLE_SECONDS,
    PREVIEW_HEALTH_CHECK_INTERVAL_SECONDS,
    PREVIEW_INTERACTION_PAUSE_INTERVAL_SECONDS,
    PREVIEW_INTERACTION_THROTTLE_SECONDS,
    PREVIEW_MIN_REDRAW_INTERVAL_SECONDS,
    PREVIEW_PLAYBACK_PAUSE_INTERVAL_SECONDS,
    PREVIEW_STALE_HEARTBEAT_SECONDS,
    PREVIEW_TIMER_INTERVAL_SECONDS,
    PREVIEW_UI_TARGET_STALE_SECONDS,
)

_ENGINE_RUNNING = False
_ENGINE_INSTANCE = None
_ENGINE_START_SCHEDULED = False
_WATCHDOG_RUNNING = False
_LAST_SIGNATURE = None
_NOW_MS = 0
_LAST_HEARTBEAT_MONOTONIC = 0.0
_LAST_DEPSGRAPH_ACTIVITY_MONOTONIC = 0.0
_LAST_FRAME_CHANGE_MONOTONIC = 0.0
_LAST_PANEL_SCROLL_MONOTONIC = 0.0
_LAST_VIEWPORT_INTERACTION_MONOTONIC = 0.0
_VIEWPORT_POINTER_BUTTONS: set[str] = set()
_VIEWPORT_TRANSFORM_ACTIVE = False
_ANIMATION_PLAYBACK_ACTIVE = False
_HOST_WINDOW_PTR = 0
_UI_REGION_TARGETS: dict[int, dict] = {}
_MACOS_BUTTON_QUERY = None
_MACOS_BUTTON_QUERY_INITIALIZED = False


def _rna_pointer(value) -> int:
    if value is None:
        return 0
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)


def preview_clock_ms() -> int:
    return int(time.monotonic() * 1000.0)


def register_ui_region(context, visible_item_ids: tuple[str, ...]) -> None:
    global _HOST_WINDOW_PTR
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    scene = getattr(context, "scene", None)
    _HOST_WINDOW_PTR = _rna_pointer(window)
    if (
        window is None
        or getattr(area, "type", "") != "VIEW_3D"
        or getattr(region, "type", "") != "UI"
    ):
        return
    region_ptr = _rna_pointer(region)
    if region_ptr == 0:
        return
    _UI_REGION_TARGETS[region_ptr] = {
        "window_ptr": _rna_pointer(window),
        "area_ptr": _rna_pointer(area),
        "scene_ptr": _rna_pointer(scene),
        "visible_item_ids": tuple(dict.fromkeys(visible_item_ids)),
        "last_seen": time.monotonic(),
    }


def _live_ui_targets(now_monotonic: float | None = None) -> tuple:
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return ()
    current_time = time.monotonic() if now_monotonic is None else now_monotonic
    windows_by_ptr = {
        _rna_pointer(window): window for window in getattr(wm, "windows", ())
    }
    live_targets = []
    stale_region_ptrs = []
    for region_ptr, target in tuple(_UI_REGION_TARGETS.items()):
        last_seen = float(target.get("last_seen", 0.0) or 0.0)
        if last_seen and current_time - last_seen > PREVIEW_UI_TARGET_STALE_SECONDS:
            stale_region_ptrs.append(region_ptr)
            continue
        window = windows_by_ptr.get(int(target.get("window_ptr", 0) or 0))
        screen = getattr(window, "screen", None)
        if screen is None:
            stale_region_ptrs.append(region_ptr)
            continue
        resolved_region = None
        area_ptr = int(target.get("area_ptr", 0) or 0)
        for area in getattr(screen, "areas", ()):
            if _rna_pointer(area) != area_ptr:
                continue
            for region in getattr(area, "regions", ()):
                if (
                    _rna_pointer(region) == region_ptr
                    and getattr(region, "type", "") == "UI"
                ):
                    resolved_region = region
                    break
            break
        if resolved_region is None:
            stale_region_ptrs.append(region_ptr)
            continue
        live_targets.append((resolved_region, target))
    for region_ptr in stale_region_ptrs:
        _UI_REGION_TARGETS.pop(region_ptr, None)
    return tuple(live_targets)


def visible_item_ids() -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for _region, target in _live_ui_targets():
        for item_id in target.get("visible_item_ids", ()):
            if item_id and item_id not in seen:
                ids.append(item_id)
                seen.add(item_id)
    return tuple(ids)


def tag_targeted_redraw() -> None:
    for region, _target in _live_ui_targets():
        try:
            region.tag_redraw()
        except Exception:
            pass


def tag_targeted_layout_refresh() -> None:
    for region, _target in _live_ui_targets():
        refresh_ui = getattr(region, "tag_refresh_ui", None)
        try:
            if callable(refresh_ui):
                refresh_ui()
            region.tag_redraw()
        except Exception:
            pass


def current_preview_ms() -> int:
    return int(_NOW_MS or preview_clock_ms())


def preview_frame_rate() -> int:
    from .frame_rate import clamp_preview_fps

    wm = getattr(bpy.context, "window_manager", None)
    return clamp_preview_fps(getattr(wm, "animthumb_preview_fps", None))


def _host_window():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return None
    for window in getattr(wm, "windows", ()):
        if _rna_pointer(window) == int(_HOST_WINDOW_PTR or 0):
            return window
    return None


def _optimized_playback_enabled() -> bool:
    wm = getattr(bpy.context, "window_manager", None)
    return bool(getattr(wm, "animthumb_optimized_playback", False))


def _is_animation_playing() -> bool:
    if _ANIMATION_PLAYBACK_ACTIVE:
        return True
    if _LAST_FRAME_CHANGE_MONOTONIC <= 0.0:
        return False
    return (
        time.monotonic() - _LAST_FRAME_CHANGE_MONOTONIC
    ) < PREVIEW_FRAME_CHANGE_THROTTLE_SECONDS


def _has_recent_depsgraph_activity() -> bool:
    return bool(
        _LAST_DEPSGRAPH_ACTIVITY_MONOTONIC > 0.0
        and time.monotonic() - _LAST_DEPSGRAPH_ACTIVITY_MONOTONIC
        < PREVIEW_INTERACTION_THROTTLE_SECONDS
    )


def _has_recent_panel_scroll() -> bool:
    return bool(
        _LAST_PANEL_SCROLL_MONOTONIC > 0.0
        and time.monotonic() - _LAST_PANEL_SCROLL_MONOTONIC
        < PREVIEW_INTERACTION_THROTTLE_SECONDS
    )


def _has_recent_viewport_interaction() -> bool:
    return bool(
        _LAST_VIEWPORT_INTERACTION_MONOTONIC > 0.0
        and time.monotonic() - _LAST_VIEWPORT_INTERACTION_MONOTONIC
        < PREVIEW_INTERACTION_THROTTLE_SECONDS
    )


def _event_over_region_type(
    context,
    event,
    *,
    area_type: str,
    region_type: str,
) -> bool:
    window = getattr(context, "window", None)
    screen = getattr(window, "screen", None)
    if screen is None:
        return False
    try:
        mouse_x = int(event.mouse_x)
        mouse_y = int(event.mouse_y)
    except (AttributeError, TypeError, ValueError):
        return bool(
            getattr(context.area, "type", "") == area_type
            and getattr(context.region, "type", "") == region_type
        )
    for area in getattr(screen, "areas", ()):
        if getattr(area, "type", "") != area_type:
            continue
        for region in getattr(area, "regions", ()):
            if getattr(region, "type", "") != region_type:
                continue
            if int(region.x) <= mouse_x < int(region.x + region.width) and int(
                region.y
            ) <= mouse_y < int(region.y + region.height):
                return True
    return False


def _event_over_preview_ui(context, event) -> bool:
    window_ptr = _rna_pointer(getattr(context, "window", None))
    try:
        mouse_x = int(event.mouse_x)
        mouse_y = int(event.mouse_y)
    except (AttributeError, TypeError, ValueError):
        region_ptr = _rna_pointer(getattr(context, "region", None))
        return any(
            int(target.get("window_ptr", 0) or 0) == window_ptr
            and _rna_pointer(region) == region_ptr
            for region, target in _live_ui_targets()
        )
    for region, target in _live_ui_targets():
        if int(target.get("window_ptr", 0) or 0) != window_ptr:
            continue
        if int(region.x) <= mouse_x < int(region.x + region.width) and int(
            region.y
        ) <= mouse_y < int(region.y + region.height):
            return True
    return False


def _native_pointer_button_pressed(event_type: str) -> bool | None:
    global _MACOS_BUTTON_QUERY
    global _MACOS_BUTTON_QUERY_INITIALIZED
    if sys.platform == "win32":
        virtual_key = {
            "LEFTMOUSE": 0x01,
            "RIGHTMOUSE": 0x02,
            "MIDDLEMOUSE": 0x04,
        }.get(event_type)
        if virtual_key is None:
            return None
        try:
            user32 = vars(ctypes)["windll"].user32
            return bool(int(user32.GetAsyncKeyState(virtual_key)) & 0x8000)
        except Exception:
            return None
    if sys.platform != "darwin":
        return None
    mouse_button = {
        "LEFTMOUSE": 0,
        "RIGHTMOUSE": 1,
        "MIDDLEMOUSE": 2,
    }.get(event_type)
    if mouse_button is None:
        return None
    if not _MACOS_BUTTON_QUERY_INITIALIZED:
        _MACOS_BUTTON_QUERY_INITIALIZED = True
        try:
            framework = ctypes.CDLL(
                "/System/Library/Frameworks/"
                "ApplicationServices.framework/ApplicationServices"
            )
            query = framework.CGEventSourceButtonState
            query.argtypes = (ctypes.c_int32, ctypes.c_uint32)
            query.restype = ctypes.c_bool
            _MACOS_BUTTON_QUERY = query
        except Exception:
            _MACOS_BUTTON_QUERY = None
    if _MACOS_BUTTON_QUERY is None:
        return None
    try:
        return bool(_MACOS_BUTTON_QUERY(0, mouse_button))
    except Exception:
        return None


def _discard_confirmed_released_buttons() -> None:
    for event_type in tuple(_VIEWPORT_POINTER_BUTTONS):
        if _native_pointer_button_pressed(event_type) is False:
            _VIEWPORT_POINTER_BUTTONS.discard(event_type)


def _mark_interaction(context, event) -> None:
    global _LAST_PANEL_SCROLL_MONOTONIC
    global _LAST_VIEWPORT_INTERACTION_MONOTONIC
    global _VIEWPORT_TRANSFORM_ACTIVE

    event_type = str(getattr(event, "type", "") or "")
    event_value = str(getattr(event, "value", "") or "")
    if event_type in {
        "WHEELUPMOUSE",
        "WHEELDOWNMOUSE",
        "TRACKPADPAN",
        "TRACKPADZOOM",
        "MOUSESMARTZOOM",
    }:
        if _event_over_preview_ui(context, event):
            _LAST_PANEL_SCROLL_MONOTONIC = time.monotonic()
        return

    pointer_buttons = {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE"}
    if event_type in pointer_buttons:
        if event_value == "PRESS" and _event_over_region_type(
            context,
            event,
            area_type="VIEW_3D",
            region_type="WINDOW",
        ):
            _VIEWPORT_POINTER_BUTTONS.add(event_type)
        elif event_value == "RELEASE":
            was_dragging = event_type in _VIEWPORT_POINTER_BUTTONS
            _VIEWPORT_POINTER_BUTTONS.discard(event_type)
            if was_dragging:
                _LAST_VIEWPORT_INTERACTION_MONOTONIC = time.monotonic()
            if event_type in {"LEFTMOUSE", "RIGHTMOUSE"}:
                _VIEWPORT_TRANSFORM_ACTIVE = False
        return

    if event_type in {"ESC", "RET", "NUMPAD_ENTER", "SPACE"}:
        if event_value == "PRESS":
            _VIEWPORT_TRANSFORM_ACTIVE = False
        return
    if (
        event_type in {"G", "R", "S"}
        and event_value == "PRESS"
        and _event_over_region_type(
            context,
            event,
            area_type="VIEW_3D",
            region_type="WINDOW",
        )
    ):
        _VIEWPORT_TRANSFORM_ACTIVE = True

    if event_type in {"MOUSEROTATE", "NDOF_MOTION"}:
        is_viewport_motion = True
    elif event_type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
        _discard_confirmed_released_buttons()
        is_viewport_motion = bool(
            _VIEWPORT_POINTER_BUTTONS or _VIEWPORT_TRANSFORM_ACTIVE
        )
    else:
        is_viewport_motion = False
    if is_viewport_motion:
        _LAST_VIEWPORT_INTERACTION_MONOTONIC = time.monotonic()


@persistent
def _depsgraph_update_handler(_scene=None, _depsgraph=None) -> None:
    global _LAST_DEPSGRAPH_ACTIVITY_MONOTONIC
    _LAST_DEPSGRAPH_ACTIVITY_MONOTONIC = time.monotonic()


@persistent
def _frame_change_handler(*_args) -> None:
    global _LAST_FRAME_CHANGE_MONOTONIC
    _LAST_FRAME_CHANGE_MONOTONIC = time.monotonic()


@persistent
def _playback_pre_handler(*_args) -> None:
    global _ANIMATION_PLAYBACK_ACTIVE
    _ANIMATION_PLAYBACK_ACTIVE = True


@persistent
def _playback_post_handler(*_args) -> None:
    global _ANIMATION_PLAYBACK_ACTIVE
    _ANIMATION_PLAYBACK_ACTIVE = False


@persistent
def _load_post_handler(*_args) -> None:
    from . import library, preview_cache

    stop()
    preview_cache.clear()
    _UI_REGION_TARGETS.clear()
    library.schedule_startup_refresh()


def _mark_heartbeat() -> None:
    global _LAST_HEARTBEAT_MONOTONIC
    _LAST_HEARTBEAT_MONOTONIC = time.monotonic()


def _engine_responsive(now_monotonic: float | None = None) -> bool:
    if not _ENGINE_RUNNING or _ENGINE_INSTANCE is None:
        return False
    timer = getattr(_ENGINE_INSTANCE, "_timer", None)
    if timer is None or _LAST_HEARTBEAT_MONOTONIC <= 0.0:
        return False
    current_time = time.monotonic() if now_monotonic is None else now_monotonic
    timer_interval = max(
        0.0,
        float(getattr(_ENGINE_INSTANCE, "_timer_interval", 0.0) or 0.0),
    )
    stale_after = max(PREVIEW_STALE_HEARTBEAT_SECONDS, timer_interval * 4.0)
    return current_time - _LAST_HEARTBEAT_MONOTONIC <= stale_after


def _watchdog_tick() -> float:
    if visible_item_ids() and not _engine_responsive():
        if _ENGINE_RUNNING:
            stop()
        schedule_start()
    return PREVIEW_HEALTH_CHECK_INTERVAL_SECONDS


def _ensure_watchdog() -> None:
    global _WATCHDOG_RUNNING
    try:
        if bpy.app.timers.is_registered(_watchdog_tick):
            _WATCHDOG_RUNNING = True
            return
    except Exception:
        pass
    bpy.app.timers.register(
        _watchdog_tick,
        first_interval=0.1,
        persistent=True,
    )
    _WATCHDOG_RUNNING = True


def _ensure_engine() -> bool:
    if _ENGINE_RUNNING:
        if _engine_responsive():
            return True
        stop()
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or not getattr(wm, "windows", None):
        return False
    window = _host_window() or getattr(bpy.context, "window", None)
    if window is None:
        try:
            window = wm.windows[0]
        except (IndexError, TypeError):
            return False
    try:
        with bpy.context.temp_override(window=window, screen=window.screen):
            result = bpy.ops.animthumb.preview_engine("INVOKE_DEFAULT")
        return bool({"RUNNING_MODAL", "FINISHED"} & set(result))
    except Exception as error:
        print(f"Animated thumbnails: failed to start preview engine: {error}")
        return False


def _engine_start_timer() -> float | None:
    global _ENGINE_START_SCHEDULED
    _ENGINE_START_SCHEDULED = False
    return None if _ensure_engine() else 0.25


def schedule_start() -> None:
    global _ENGINE_START_SCHEDULED
    _ensure_watchdog()
    if _ENGINE_RUNNING and _engine_responsive():
        return
    if _ENGINE_RUNNING:
        stop()
    if _ENGINE_START_SCHEDULED:
        return
    _ENGINE_START_SCHEDULED = True
    bpy.app.timers.register(_engine_start_timer, first_interval=0.05)


def request_fast_reschedule() -> None:
    global _LAST_SIGNATURE
    _LAST_SIGNATURE = None
    instance = _ENGINE_INSTANCE
    if instance is not None:
        instance._schedule_interval(PREVIEW_TIMER_INTERVAL_SECONDS)


def stop() -> None:
    global _ENGINE_RUNNING
    global _ENGINE_INSTANCE
    global _LAST_SIGNATURE
    global _NOW_MS
    global _LAST_HEARTBEAT_MONOTONIC
    global _LAST_PANEL_SCROLL_MONOTONIC
    global _LAST_VIEWPORT_INTERACTION_MONOTONIC
    global _VIEWPORT_TRANSFORM_ACTIVE

    instance = _ENGINE_INSTANCE
    _ENGINE_RUNNING = False
    _ENGINE_INSTANCE = None
    _LAST_SIGNATURE = None
    _NOW_MS = 0
    _LAST_HEARTBEAT_MONOTONIC = 0.0
    _LAST_PANEL_SCROLL_MONOTONIC = 0.0
    _LAST_VIEWPORT_INTERACTION_MONOTONIC = 0.0
    _VIEWPORT_POINTER_BUTTONS.clear()
    _VIEWPORT_TRANSFORM_ACTIVE = False
    if instance is not None:
        try:
            instance._shutdown()
        except Exception:
            pass


class ANIMTHUMB_OT_PreviewEngine(bpy.types.Operator):
    bl_idname = "animthumb.preview_engine"
    bl_label = "Animated Thumbnail Preview Engine"
    bl_description = "Internal duration-aware thumbnail scheduler"
    bl_options = {"INTERNAL"}

    _timer = None
    _wm = None
    _window = None
    _timer_interval = 0.0

    def _schedule_interval(self, interval_seconds: float) -> None:
        wm = self._wm or getattr(bpy.context, "window_manager", None)
        window = self._window or getattr(bpy.context, "window", None)
        if wm is None or window is None:
            return
        target_interval = max(
            PREVIEW_MIN_REDRAW_INTERVAL_SECONDS,
            min(float(interval_seconds or PREVIEW_TIMER_INTERVAL_SECONDS), 2.0),
        )
        if (
            self._timer is not None
            and self._timer_interval > 0.0
            and abs(self._timer_interval - target_interval) < 0.001
        ):
            return
        if self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        try:
            self._timer = wm.event_timer_add(target_interval, window=window)
            self._timer_interval = target_interval
        except Exception:
            self._timer = None

    def _shutdown(self) -> None:
        global _ENGINE_RUNNING
        global _ENGINE_INSTANCE
        global _LAST_SIGNATURE
        global _LAST_HEARTBEAT_MONOTONIC

        owns_engine = _ENGINE_INSTANCE is self
        wm = self._wm or getattr(bpy.context, "window_manager", None)
        if wm is not None and self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
        self._timer = None
        self._wm = None
        self._window = None
        self._timer_interval = 0.0
        if owns_engine:
            _ENGINE_INSTANCE = None
            _ENGINE_RUNNING = False
            _LAST_SIGNATURE = None
            _LAST_HEARTBEAT_MONOTONIC = 0.0

    def invoke(self, context, event):
        del event
        global _ENGINE_RUNNING
        global _ENGINE_INSTANCE
        global _LAST_SIGNATURE

        if _ENGINE_RUNNING:
            if _engine_responsive():
                return {"FINISHED"}
            stop()
        wm = getattr(context, "window_manager", None)
        window = getattr(context, "window", None)
        if wm is None or window is None:
            return {"CANCELLED"}
        self._wm = wm
        self._window = window
        from . import preview_cache

        ids = visible_item_ids()
        initial_interval = preview_cache.next_interval_seconds(
            ids,
            preview_clock_ms(),
            fps_limit=preview_frame_rate(),
        )
        self._schedule_interval(initial_interval)
        if self._timer is None:
            return {"CANCELLED"}
        wm.modal_handler_add(self)
        _ENGINE_INSTANCE = self
        _ENGINE_RUNNING = True
        _LAST_SIGNATURE = None
        _mark_heartbeat()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global _LAST_SIGNATURE
        global _NOW_MS

        if not _ENGINE_RUNNING or _ENGINE_INSTANCE is not self:
            self._shutdown()
            return {"CANCELLED"}
        if event.type == "TIMER":
            event_timer = getattr(event, "timer", None)
            if event_timer is not None and self._timer is not None:
                try:
                    if _rna_pointer(event_timer) != _rna_pointer(self._timer):
                        return {"PASS_THROUGH"}
                except Exception:
                    return {"PASS_THROUGH"}
            _mark_heartbeat()
            if _optimized_playback_enabled():
                if _is_animation_playing():
                    self._schedule_interval(PREVIEW_PLAYBACK_PAUSE_INTERVAL_SECONDS)
                    return {"PASS_THROUGH"}
                if (
                    _has_recent_depsgraph_activity()
                    and _has_recent_viewport_interaction()
                ) or _has_recent_panel_scroll():
                    self._schedule_interval(PREVIEW_INTERACTION_PAUSE_INTERVAL_SECONDS)
                    return {"PASS_THROUGH"}
            ids = visible_item_ids()
            if ids:
                from . import preview_cache

                now_ms = preview_clock_ms()
                fps_limit = preview_frame_rate()
                signature = preview_cache.frame_signature(
                    ids,
                    now_ms,
                    fps_limit=fps_limit,
                )
                if signature != _LAST_SIGNATURE:
                    _LAST_SIGNATURE = signature
                    _NOW_MS = now_ms
                    wm = getattr(context, "window_manager", None) or self._wm
                    if wm is not None:
                        wm.animthumb_preview_tick = (
                            int(getattr(wm, "animthumb_preview_tick", 0) or 0) + 1
                        ) % 1_000_000
                    tag_targeted_redraw()
                self._schedule_interval(
                    preview_cache.next_interval_seconds(
                        ids,
                        now_ms,
                        fps_limit=fps_limit,
                    )
                )
            return {"PASS_THROUGH"}
        _mark_interaction(context, event)
        return {"PASS_THROUGH"}

    def cancel(self, context) -> None:
        del context
        self._shutdown()


def register_runtime() -> None:
    handlers = (
        ("load_post", _load_post_handler),
        ("depsgraph_update_post", _depsgraph_update_handler),
        ("frame_change_post", _frame_change_handler),
        ("animation_playback_pre", _playback_pre_handler),
        ("animation_playback_post", _playback_post_handler),
    )
    for name, handler in handlers:
        collection = getattr(bpy.app.handlers, name, None)
        if collection is not None and handler not in collection:
            collection.append(handler)
    _ensure_watchdog()


def unregister_runtime() -> None:
    global _ENGINE_START_SCHEDULED
    global _WATCHDOG_RUNNING
    stop()
    handlers = (
        ("load_post", _load_post_handler),
        ("depsgraph_update_post", _depsgraph_update_handler),
        ("frame_change_post", _frame_change_handler),
        ("animation_playback_pre", _playback_pre_handler),
        ("animation_playback_post", _playback_post_handler),
    )
    for name, handler in handlers:
        collection = getattr(bpy.app.handlers, name, None)
        if collection is not None and handler in collection:
            collection.remove(handler)
    for timer_function in (_engine_start_timer, _watchdog_tick):
        try:
            if bpy.app.timers.is_registered(timer_function):
                bpy.app.timers.unregister(timer_function)
        except Exception:
            pass
    _ENGINE_START_SCHEDULED = False
    _WATCHDOG_RUNNING = False
    _UI_REGION_TARGETS.clear()
