from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
package = types.ModuleType("blender_animated_ui")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("blender_animated_ui", package)

from blender_animated_ui.media_settings import (  # noqa: E402
    MediaAnalysis,
    MediaImportSettings,
    estimate_cache,
    selected_frame_count,
)
from blender_animated_ui.media_types import (  # noqa: E402
    CacheImageProfile,
    IngestResult,
)


class MediaSettingsTests(unittest.TestCase):
    def test_settings_normalize_without_enabling_trim(self) -> None:
        settings = MediaImportSettings(
            target_fps=120,
            trim_media=False,
            trim_start_frame=-3,
            trim_end_frame=-2,
        ).normalized()
        self.assertEqual(settings.target_fps, 60)
        self.assertFalse(settings.trim_media)
        self.assertEqual(settings.trim_start_frame, 1)
        self.assertEqual(settings.trim_end_frame, 0)

    def test_encoded_media_estimate_respects_native_rate(self) -> None:
        estimate = estimate_cache(
            MediaAnalysis(
                source_fps=30.0,
                duration_seconds=2.0,
                total_frames=60,
            ),
            MediaImportSettings(target_fps=60),
        )
        self.assertEqual(estimate.sample_fps, 30.0)
        self.assertEqual(estimate.cached_frames, 60)
        self.assertEqual(estimate.preview_duration_seconds, 2.0)

    def test_sequence_trim_is_inclusive_and_opt_in(self) -> None:
        full = MediaImportSettings(
            target_fps=24,
            trim_media=False,
            trim_start_frame=4,
            trim_end_frame=6,
        )
        trimmed = MediaImportSettings(
            target_fps=24,
            trim_media=True,
            trim_start_frame=4,
            trim_end_frame=6,
        )
        self.assertEqual(selected_frame_count(10, full), 10)
        self.assertEqual(selected_frame_count(10, trimmed), 3)
        estimate = estimate_cache(
            MediaAnalysis(
                is_sequence=True,
                selection_count=10,
                total_frames=10,
            ),
            trimmed,
        )
        self.assertEqual(estimate.cached_frames, 3)
        self.assertAlmostEqual(estimate.preview_duration_seconds, 0.125)

    def test_cache_profile_validation_and_result_mapping_compatibility(self) -> None:
        profile = CacheImageProfile(
            extension=".webp",
            metadata_format="webp",
            pad_color="color=0x00000000",
            ffmpeg_args=("-quality", "90"),
        ).normalized()
        self.assertEqual(profile.extension, "webp")
        self.assertEqual(profile.metadata_format, "WEBP")
        with self.assertRaises(ValueError):
            CacheImageProfile("tga", "TGA", "", ()).normalized()

        result = IngestResult(
            item_id="item",
            name="Name",
            cache_dir="/tmp/cache",
            frame_count=2,
            duration_ms=200,
            source_duration_ms=200,
            width=64,
            height=64,
            target_fps=10,
            source_fps=10.0,
            sample_fps=10.0,
            media_kind="MEDIA",
            sequence_order="",
            cache_image_format="JPEG",
            trim_media=False,
            trim_start_frame=1,
            trim_end_frame=0,
            effective_fps=10.0,
        )
        self.assertEqual(result.name, "Name")
        self.assertEqual(result["name"], "Name")
        self.assertEqual(result.get("frame_count"), 2)
        self.assertEqual(result.as_dict()["cache_image_format"], "JPEG")


if __name__ == "__main__":
    unittest.main()
