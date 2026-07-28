from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
package = types.ModuleType("blender_animated_ui")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("blender_animated_ui", package)

from blender_animated_ui.gallery_query import (  # noqa: E402
    GalleryQuery,
    filter_and_sort_media,
    source_media_type,
)


@dataclass(frozen=True)
class Item:
    item_id: str
    name: str
    source_type: str
    date_added_utc: str


class GalleryQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = (
            Item("1", "Zebra Walk", "MP4", "2026-07-28T12:00:00Z"),
            Item("2", "Alpha Wave", "GIF", "2026-07-28T13:00:00Z"),
            Item("3", "Alpha Run", "MP4", "2026-07-28T14:00:00Z"),
        )

    def test_source_type_uses_import_extension_or_sequence(self) -> None:
        self.assertEqual(source_media_type(["/tmp/test.mp4"]), "MP4")
        self.assertEqual(source_media_type(["/tmp/test.gif"]), "GIF")
        self.assertEqual(source_media_type(["/tmp/test.unknown"]), "OTHER")
        self.assertEqual(
            source_media_type(["/tmp/1.png", "/tmp/2.png"]),
            "SEQUENCE",
        )

    def test_default_sort_places_newest_media_first(self) -> None:
        result = filter_and_sort_media(self.items, GalleryQuery())
        self.assertEqual([item.item_id for item in result], ["3", "2", "1"])

    def test_search_and_type_filter_compose(self) -> None:
        result = filter_and_sort_media(
            self.items,
            GalleryQuery(
                search_text="alpha",
                media_type="MP4",
                sort_mode="NAME_ASC",
            ),
        )
        self.assertEqual([item.name for item in result], ["Alpha Run"])

    def test_name_sort_supports_both_directions(self) -> None:
        ascending = filter_and_sort_media(
            self.items,
            GalleryQuery(sort_mode="NAME_ASC"),
        )
        descending = filter_and_sort_media(
            self.items,
            GalleryQuery(sort_mode="NAME_DESC"),
        )
        self.assertEqual(
            [item.name for item in ascending],
            ["Alpha Run", "Alpha Wave", "Zebra Walk"],
        )
        self.assertEqual(
            [item.name for item in descending],
            ["Zebra Walk", "Alpha Wave", "Alpha Run"],
        )


if __name__ == "__main__":
    unittest.main()
