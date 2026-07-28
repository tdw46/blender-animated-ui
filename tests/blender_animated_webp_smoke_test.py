"""Decode an animated WebP through the isolated media-wheel adapter."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import bpy
import bpy.utils.previews

source_parent = os.environ.get("ANIMTHUMB_SOURCE_PARENT", "")
package_name = os.environ.get("ANIMTHUMB_PACKAGE", "blender_animated_ui")
webp_media = os.environ.get("ANIMTHUMB_WEBP_MEDIA", "")
if not webp_media:
    raise RuntimeError("ANIMTHUMB_WEBP_MEDIA is required")

if source_parent:
    sys.path.insert(0, source_parent)
package = importlib.import_module(package_name)
status = package.ffmpeg_bridge.status()
if os.environ.get("ANIMTHUMB_EXPECT_BUNDLED") == "1" and not status.get(
    "bundled_wheels_ready"
):
    raise RuntimeError(f"Manifest-managed media wheels were not selected: {status}")
if not status.get("animated_webp_ready"):
    success, detail = package.ffmpeg_bridge.install_wheel()
    if not success:
        raise RuntimeError(f"Media wheels could not be installed: {detail}")
    status = package.ffmpeg_bridge.refresh_status()
if not status.get("animated_webp_ready"):
    raise RuntimeError(f"Animated WebP tools are unavailable: {status}")

source_path = Path(webp_media).expanduser().resolve()
probe = package.media_ingest.probe_media(str(status["executable"]), source_path)
if probe.video_codec != "webp" or probe.frame_count <= 1:
    raise RuntimeError(f"Animated WebP probe failed: {probe}")

with tempfile.TemporaryDirectory(prefix="animthumb-webp-smoke-") as temporary:
    result = package.media_ingest.ingest_media(
        str(status["executable"]),
        [source_path],
        target_fps=22,
        cache_directory=temporary,
        dependency_directory=str(status["dependency_root"]),
    )
    metadata = package.cache_format.read_metadata(result.cache_dir)
    if result.frame_count != probe.frame_count:
        raise RuntimeError(
            f"Native-rate WebP lost frames: {result.frame_count} != {probe.frame_count}"
        )
    if result.duration_ms < result.source_duration_ms:
        raise RuntimeError(
            f"Animated WebP was shortened: {result.duration_ms} < "
            f"{result.source_duration_ms}"
        )
    if result.cache_image_format != "WEBP":
        raise RuntimeError(f"Animated WebP lost alpha profile: {result}")

    first_frame = metadata["records"][0].path
    image = bpy.data.images.load(str(first_frame), check_existing=False)
    try:
        cache_size = tuple(int(value) for value in image.size)
    finally:
        bpy.data.images.remove(image)
    expected_size = (
        package.constants.MAX_THUMBNAIL_EDGE,
        package.constants.MAX_THUMBNAIL_EDGE,
    )
    if cache_size != expected_size:
        raise RuntimeError(f"Unexpected cache size: {cache_size} != {expected_size}")

    preview_collection = bpy.utils.previews.new()
    try:
        preview = preview_collection.load(
            "animated_webp_smoke",
            str(first_frame),
            "IMAGE",
        )
        preview_size = tuple(int(value) for value in preview.image_size)
        preview_pixels = tuple(preview.image_pixels_float)
        if min(preview_size, default=0) <= 0 or not preview_pixels:
            raise RuntimeError(f"Animated WebP preview did not load: {preview_size}")
    finally:
        bpy.utils.previews.remove(preview_collection)

print(
    "ANIMTHUMB_ANIMATED_WEBP",
    {
        "version": tuple(bpy.app.version),
        "pillow": status.get("pillow_version"),
        "bundled_wheels_ready": status.get("bundled_wheels_ready"),
        "imageio_source": status.get("imageio_source"),
        "pillow_source": status.get("pillow_source"),
        "source_frames": probe.frame_count,
        "cache_frames": result.frame_count,
        "source_fps": probe.source_fps,
        "sample_fps": result.sample_fps,
        "source_duration_ms": result.source_duration_ms,
        "duration_ms": result.duration_ms,
        "format": result.cache_image_format,
        "cache_size": cache_size,
        "preview_size": preview_size,
    },
)
