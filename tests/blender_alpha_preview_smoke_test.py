"""Verify that transparent WebM pixels survive FFmpeg and Blender previews."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import bpy
import bpy.utils.previews

source_parent = os.environ.get("ANIMTHUMB_SOURCE_PARENT", "")
ffmpeg = os.environ.get("ANIMTHUMB_FFMPEG", "")
alpha_media = os.environ.get("ANIMTHUMB_ALPHA_MEDIA", "")
if not all((source_parent, ffmpeg, alpha_media)):
    raise RuntimeError(
        "ANIMTHUMB_SOURCE_PARENT, ANIMTHUMB_FFMPEG, and "
        "ANIMTHUMB_ALPHA_MEDIA are required"
    )

sys.path.insert(0, source_parent)
package = importlib.import_module("blender_animated_ui")
source_path = Path(alpha_media).expanduser().resolve()
probe = package.media_ingest.probe_media(ffmpeg, source_path)
decoder = package.media_ingest._alpha_decoder_name(source_path, probe)
if not probe.has_alpha or decoder not in {"libvpx", "libvpx-vp9"}:
    raise RuntimeError(
        f"Transparent WebM probe failed: alpha={probe.has_alpha}, "
        f"codec={probe.video_codec!r}, decoder={decoder!r}"
    )

with tempfile.TemporaryDirectory(prefix="animthumb-alpha-smoke-") as temporary:
    result = package.media_ingest.ingest_media(
        ffmpeg,
        [source_path],
        display_name="Alpha Smoke",
        target_fps=30,
        trim_media=True,
        trim_start_frame=1,
        trim_end_frame=2,
        cache_directory=temporary,
    )
    metadata = package.cache_format.read_metadata(result.cache_dir)
    if result.cache_image_format != "WEBP":
        raise RuntimeError(
            f"Transparent WebM used {result.cache_image_format}, expected WEBP"
        )
    first_frame = metadata["records"][0].path

    image = bpy.data.images.load(str(first_frame), check_existing=False)
    try:
        image_pixels = tuple(image.pixels)
        image_alpha = image_pixels[3::4]
        image_alpha_range = (min(image_alpha), max(image_alpha))
    finally:
        bpy.data.images.remove(image)
    if image_alpha_range[0] >= 1.0 or image_alpha_range[1] <= 0.0:
        raise RuntimeError(f"Cached WebP lost transparency: alpha={image_alpha_range}")

    preview_collection = bpy.utils.previews.new()
    try:
        preview = preview_collection.load(
            "alpha_smoke",
            str(first_frame),
            "IMAGE",
        )
        preview_pixels = tuple(preview.image_pixels_float)
        preview_alpha = preview_pixels[3::4]
        preview_alpha_range = (
            (min(preview_alpha), max(preview_alpha)) if preview_alpha else ()
        )
        if (
            not preview_alpha_range
            or preview_alpha_range[0] >= 1.0
            or preview_alpha_range[1] <= 0.0
        ):
            raise RuntimeError(
                f"Blender preview lost transparency: alpha={preview_alpha_range}"
            )
        preview_size = tuple(int(value) for value in preview.image_size)
        icon_id = int(preview.icon_id)
    finally:
        bpy.utils.previews.remove(preview_collection)

print(
    "ANIMTHUMB_ALPHA_PREVIEW",
    {
        "version": tuple(bpy.app.version),
        "codec": probe.video_codec,
        "decoder": decoder,
        "cache_format": result.cache_image_format,
        "frame_count": result.frame_count,
        "image_alpha_range": image_alpha_range,
        "preview_alpha_range": preview_alpha_range,
        "preview_size": preview_size,
        "icon_id": icon_id,
    },
)
