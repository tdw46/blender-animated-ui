"""Small dependency-safe class auto-loader for modular Blender extensions."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from types import ModuleType

import bpy

_MODULES: list[ModuleType] = []
_REGISTERED_CLASSES: list[type] = []

_SKIP_BASENAMES = {
    "__init__",
    "auto_load",
}
_SKIP_PARTS = {
    "_vendor",
    "PIL",
    "site-packages",
    "tests",
    "tools",
    "wheels",
}


def _package_name() -> str:
    return __package__ or __name__.rpartition(".")[0]


def _iter_module_names() -> list[str]:
    package_name = _package_name()
    package_path = Path(__file__).resolve().parent
    names: list[str] = []
    for module_info in pkgutil.walk_packages(
        [str(package_path)],
        prefix=f"{package_name}.",
    ):
        relative = module_info.name.removeprefix(f"{package_name}.")
        parts = relative.split(".")
        if parts[-1] in _SKIP_BASENAMES or any(part in _SKIP_PARTS for part in parts):
            continue
        names.append(module_info.name)
    return sorted(names)


def init() -> None:
    """Discover and import extension modules without registering Blender classes."""
    _MODULES.clear()
    for module_name in _iter_module_names():
        module = sys.modules.get(module_name)
        if module is None:
            module = importlib.import_module(module_name)
        _MODULES.append(module)


def _is_registerable_class(value: object, module: ModuleType) -> bool:
    if not inspect.isclass(value) or value.__module__ != module.__name__:
        return False
    registerable = (
        bpy.types.AddonPreferences,
        bpy.types.Gizmo,
        bpy.types.GizmoGroup,
        bpy.types.Header,
        bpy.types.Menu,
        bpy.types.Node,
        bpy.types.NodeSocket,
        bpy.types.Operator,
        bpy.types.Panel,
        bpy.types.PropertyGroup,
        bpy.types.RenderEngine,
        bpy.types.UIList,
    )
    try:
        return issubclass(value, registerable)
    except TypeError:
        return False


def _class_priority(cls: type) -> tuple[int, str, int, str]:
    priority = 50
    try:
        if issubclass(cls, bpy.types.PropertyGroup):
            priority = 0
        elif issubclass(cls, bpy.types.AddonPreferences):
            priority = 10
        elif issubclass(cls, bpy.types.Operator):
            priority = 20
        elif issubclass(cls, bpy.types.Menu):
            priority = 30
        elif issubclass(cls, bpy.types.UIList):
            priority = 40
        elif issubclass(cls, bpy.types.Panel):
            priority = 60
    except TypeError:
        pass
    try:
        source_line = inspect.getsourcelines(cls)[1]
    except (OSError, TypeError):
        source_line = 0
    return priority, cls.__module__, source_line, cls.__name__


def register() -> None:
    """Register every Blender class declared by a discovered module."""
    if not _MODULES:
        init()
    classes = {
        value
        for module in _MODULES
        for value in vars(module).values()
        if _is_registerable_class(value, module)
    }
    for cls in sorted(classes, key=_class_priority):
        bpy.utils.register_class(cls)
        _REGISTERED_CLASSES.append(cls)


def unregister() -> None:
    """Unregister classes in exact reverse registration order."""
    for cls in reversed(_REGISTERED_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _REGISTERED_CLASSES.clear()
