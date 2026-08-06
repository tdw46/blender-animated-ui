"""Animated Thumbnail Preview Demo Blender extension."""

from __future__ import annotations

from . import auto_load

bl_info = {
    "name": "Animated Thumbnail Preview Demo",
    "author": "Tyler Walker",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Animated Previews",
    "description": "Reusable animated preview thumbnail gallery example",
    "category": "Interface",
}

auto_load.init()


def register() -> None:
    auto_load.register()

    from . import library, preview_cache, preview_engine, properties

    properties.register_properties()
    preview_cache.register_runtime()
    preview_engine.register_runtime()
    library.schedule_startup_refresh()


def unregister() -> None:
    from . import library, preview_cache, preview_engine, properties

    library.cancel_startup_refresh()
    preview_engine.unregister_runtime()
    preview_cache.unregister_runtime()
    properties.unregister_properties()
    auto_load.unregister()


if __name__ == "__main__":
    register()
