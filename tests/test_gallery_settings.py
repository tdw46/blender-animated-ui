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

from blender_animated_ui.gallery_settings import (  # noqa: E402
    DEFAULT_GALLERY_SETTINGS,
    MAX_THUMBNAIL_SCALE,
    MIN_THUMBNAIL_SCALE,
    normalized_thumbnail_scale,
)


class GallerySettingsTests(unittest.TestCase):
    def test_default_value_maps_to_original_one_point_five_visual_size(self) -> None:
        self.assertEqual(DEFAULT_GALLERY_SETTINGS.thumbnail_scale, 1.0)
        self.assertEqual(DEFAULT_GALLERY_SETTINGS.preview_ram_budget_mb, 32)
        self.assertEqual(normalized_thumbnail_scale(1.0), 1.5)

    def test_minimum_preserves_original_point_seven_five_size(self) -> None:
        self.assertEqual(MIN_THUMBNAIL_SCALE, 0.5)
        self.assertEqual(normalized_thumbnail_scale(MIN_THUMBNAIL_SCALE), 0.75)

    def test_scale_is_clamped_to_public_slider_range(self) -> None:
        self.assertEqual(normalized_thumbnail_scale(None), 1.5)
        self.assertEqual(normalized_thumbnail_scale(0.0), 0.75)
        self.assertEqual(
            normalized_thumbnail_scale(999.0),
            MAX_THUMBNAIL_SCALE * 1.5,
        )


if __name__ == "__main__":
    unittest.main()
