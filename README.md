# Animated Thumbnail Preview Demo

A reusable example library for adding efficient animated preview thumbnails to
Blender extensions.

This repository turns GIFs, APNGs, videos, still images, and selected image
sequences into timed JPEG/WebP frame caches, then displays those frames inside
a normal Blender N-panel gallery through `bpy.utils.previews`.

The playback architecture is a modular extraction of the production approach
used by Beyond VRM Extension Suite:

- one guarded modal scheduler for every visible thumbnail;
- source-duration-aware frame boundaries;
- one shared Blender preview collection;
- no filesystem access in the playback hot path;
- only the visible gallery page advances;
- only the N-panel UI regions that drew the gallery are redrawn;
- a settings cog with thumbnail sizing, an 8–60 FPS live ceiling, and opt-in
  optimized playback;
- viewport, timeline, and gallery-scroll pausing that matches the Beyond VRM
  behavior;
- missed mouse-release repair on Windows and macOS; and
- a low-frequency watchdog that replaces a timer only when its heartbeat is
  stale.

The extension name intentionally avoids using Blender as product branding. The
repository and documentation use the word only to describe the host
application.

## Try the demo

1. Download the release ZIP or build one with `build.sh`/`build.bat`.
2. In Blender 4.2 or newer, open Preferences → Get Extensions, use the
   drop-down menu, and choose **Install from Disk**.
3. Open the 3D View sidebar and select the **Animated Previews** tab.
4. Click **Add Animated Media**.
5. Select one animated/image/video file, or multi-select an ordered image
   sequence.

The file browser analyzes the active media and shows its native FPS, full
duration, expected cache FPS, expected cache size, and optional trim range.
New imports default to a 60 FPS ceiling but never exceed the media's own native
rate. Use the arrow beneath any card to rebuild it with new settings, open its
cache directory, or delete it.

On the first ingest, the extension can install the platform-specific
`imageio-ffmpeg` 0.6.0 wheel into persistent extension-user storage. The wheel
contains its FFmpeg executable. Nothing is installed into Blender’s managed
extension source, the global Python environment, or a raw `.whl` path.

If Online Access is disabled, the extension asks the user to enable it before
running pip. An existing system FFmpeg executable is accepted as a fallback.

## Supported input

The practical format list is the set of image/video decoders supported by the
installed FFmpeg build. The file browser highlights common inputs:

- GIF, APNG, animated WebP;
- PNG, JPEG, WebP, BMP, TIFF, and other still images;
- MP4, MOV, M4V, AVI, MKV, WebM, MPEG, WMV, and FLV; and
- multiple selected image files treated as an ordered sequence.

Opaque inputs are normalized to square JPEG frames with black letterboxing.
Sources with an alpha channel use square WebP frames with transparent
letterboxing. Both formats load through Blender preview collections in the
supported host versions while using substantially less cache space than a
full PNG cache in common cases.

Every import preserves the complete media range by default. Cache size never
causes an automatic FPS reduction, tail cut, or shorter preview window. Large
expected caches show a warning so the user can deliberately lower the import
FPS or enable **Trim Media**. Trim is disabled by default; its inclusive
**Begin Frame** and **End Frame** values initialize to the actual first and
last source frames after analysis.

Selected image sequences have no encoded native rate, so **Playback FPS**
defines their rate. Every selected image is retained unless Trim Media is
enabled. Sequence order can be alphanumeric ascending/descending, file date
oldest/newest, or Blender file-browser selection order.

## Module map

Each feature has a narrow boundary so projects can copy only what they need.

| Module | Responsibility | Blender dependency |
| --- | --- | --- |
| `frame_rate.py` | Shared FPS clamping, sampling, and playback-grid math | None |
| `media_probe.py` | Parse native FPS, dimensions, and duration from FFmpeg | None |
| `media_selection.py` | Deterministic image-sequence ordering | None |
| `cache_format.py` | Cache filenames, metadata schema, timing records | None |
| `media_ingest.py` | FFmpeg probing, trimming, JPEG/WebP cache generation | Paths only |
| `ffmpeg_bridge.py` | Isolated wheel install and executable discovery | None |
| `paths.py` | Persistent extension-user cache/dependency paths | `bpy.utils` |
| `preferences.py` | Optional custom cache-root preference | Blender RNA |
| `preview_cache.py` | Load frames once and answer memory-only icon/timing queries | `bpy.utils.previews` |
| `preview_engine.py` | Visible-only modal scheduler, optimized mode, watchdog | Blender runtime |
| `properties.py` | Scene library items and WindowManager UI settings | Blender RNA |
| `library.py` | Scan persistent caches into Scene collections | Blender RNA |
| `ops_media.py` | File selector, install, ingest, refresh, delete, pagination | Blender operators |
| `ui_gallery.py` | N-panel grid and settings-cog popover | Blender UI |
| `auto_load.py` | Discover and register extension-owned Blender classes | Blender registration |

The top-level `__init__.py` is intentionally limited to lifecycle wiring.

Recommended arrangement inside a destination extension:

```text
your_extension/
├── __init__.py                 # lifecycle calls only
├── auto_load.py                # class discovery/registration
├── constants.py
├── frame_rate.py               # pure shared FPS policy
├── media_probe.py              # pure FFmpeg probe parser
├── media_selection.py          # pure image-sequence ordering
├── paths.py
├── cache_format.py             # pure cache model
├── ffmpeg_bridge.py            # optional ingest dependency
├── media_ingest.py             # optional ingest pipeline
├── preview_cache.py            # preview icons and frame timing
├── preview_engine.py           # one persistent scheduler
├── properties.py               # RNA definitions
├── preferences.py              # custom cache location
├── library.py                  # cache-to-RNA synchronization
├── ops_media.py                # user actions
├── ui_gallery.py               # example presentation layer
└── blender_manifest.toml
```

## Runtime call graph

```mermaid
flowchart LR
    UI["ui_gallery.py<br/>visible page"] --> PC["preview_cache.py<br/>memory-only icon lookup"]
    UI --> PE["preview_engine.py<br/>one modal scheduler"]
    PE --> PC
    PE --> R["Targeted UI-region redraw"]
    PC --> FPS["frame_rate.py<br/>shared FPS policy"]

    OP["ops_media.py<br/>file selector"] --> FB["ffmpeg_bridge.py<br/>platform wheel"]
    OP --> MI["media_ingest.py<br/>FFmpeg conversion"]
    MI --> MP["media_probe.py<br/>native source rate"]
    MI --> FPS
    MI --> CF["cache_format.py<br/>timed JPEG/WebP cache"]
    CF --> LIB["library.py<br/>persistent library scan"]
    LIB --> UI
```

## Minimum splice-in integration

For the complete reusable feature, copy these files into another extension:

```text
auto_load.py
cache_format.py
constants.py
ffmpeg_bridge.py
frame_rate.py
media_probe.py
media_selection.py
library.py
media_ingest.py
ops_media.py
paths.py
preferences.py
preview_cache.py
preview_engine.py
properties.py
ui_gallery.py
```

Then make these project-specific edits:

1. Change `ADDON_ID` in `constants.py`.
2. Rename the `ANIMTHUMB_` class prefix and `animthumb.*` operator namespace if
   the destination project could collide with another installed copy.
3. Rename `animthumb_*` RNA properties if the destination extension already
   defines similarly named Scene or WindowManager properties.
4. Merge the `[permissions]` declarations from `blender_manifest.toml`.
5. Add or preserve the platform list required by the destination extension.
6. Keep the dependency and thumbnail cache directories in persistent
   extension-user storage.

### Registration hooks

After the auto-loader registers classes, call:

```python
from . import library, preview_cache, preview_engine, properties

properties.register_properties()
preview_cache.register_runtime()
preview_engine.register_runtime()
library.schedule_startup_refresh()
```

Unregister in reverse runtime order before asking the auto-loader to unregister
classes:

```python
library.cancel_startup_refresh()
preview_engine.unregister_runtime()
preview_cache.unregister_runtime()
properties.unregister_properties()
```

Do not access `bpy.data.scenes` while RNA classes are registering. The library
scan is intentionally deferred through `bpy.app.timers`.

## Using only the playback library

Projects that already generate compatible timed image caches can skip `ffmpeg_bridge.py`,
`media_ingest.py`, and the ingest operators.

Create a cache directory containing `metadata.json` and timed images:

```text
thumbnail_cache/
└── walk_cycle_a1b2c3d4/
    ├── metadata.json
    ├── frame_000__00000000_00000100.jpg
    ├── frame_001__00000100_00000200.jpg
    └── frame_002__00000200_00000300.jpg
```

Load a Scene item once:

```python
from . import preview_cache

preview_cache.load_item(item)
```

During panel draw, get the current icon entirely from memory:

```python
from . import preview_engine, preview_cache

now_ms = preview_engine.current_preview_ms()
icon_id = preview_cache.icon_id(
    item.item_id,
    now_ms,
    fps_limit=preview_engine.preview_frame_rate(),
)
layout.template_icon(icon_value=icon_id, scale=5.0)
```

Tell the scheduler which items this UI region actually drew:

```python
visible_ids = tuple(item.item_id for item in visible_page)
preview_engine.register_ui_region(context, visible_ids)
preview_engine.schedule_start()
```

That visibility registration is essential. It is what prevents off-screen
pages, closed panels, unrelated windows, and stale regions from generating
frame work or redraw traffic.

## Using only the ingest library

The conversion layer is callable without the demo panel:

```python
from .ffmpeg_bridge import status
from .media_ingest import ingest_media

ffmpeg = status()["executable"]
result = ingest_media(
    ffmpeg,
    ["/path/to/animation.gif"],
    display_name="My Animation",
    target_fps=60,
    trim_media=False,
)
print(result["cache_dir"])
```

For image sequences, pass every file in display order:

```python
result = ingest_media(
    ffmpeg,
    [
        "/path/to/frame_0001.png",
        "/path/to/frame_0002.png",
        "/path/to/frame_0003.png",
    ],
    target_fps=60,
    sequence_order="ALPHANUMERIC_ASC",
)
```

`ingest_media()` stages the conversion, writes metadata atomically, swaps a
previous cache only after success, and restores the prior cache if the final
swap fails.

`target_fps` is optional and defaults to 60. It is clamped to the supported
8–60 FPS range by `frame_rate.clamp_preview_fps()`. For encoded animated media,
`media_probe.parse_ffmpeg_probe()` detects the source rate. The import rate is:

```text
sample_fps = min(target_fps, source_fps)  # when native FPS is known
```

An unknown source rate leaves the requested ceiling unchanged rather than being
guessed.
Consequently, requesting 60 FPS for a 12 FPS GIF/video produces an approximately
12 FPS cache instead of five duplicated cache frames per source frame. A
15-second, 24 FPS video produces the full approximately 360-frame, 15-second
cache. If `source_fps` itself is below 8 FPS, that genuine native rate is kept;
the 8 FPS minimum applies to user-selectable ceilings, not to retiming slow
source media.

Trimming is always opt-in:

```python
result = ingest_media(
    ffmpeg,
    ["/path/to/animation.mp4"],
    target_fps=30,
    trim_media=True,
    trim_start_frame=121,
    trim_end_frame=240,
)
```

Frame bounds are 1-based and inclusive. With `trim_media=False`, the begin/end
values are ignored and the complete source is cached. `trim_end_frame=0` means
the real media end when a caller cannot pre-probe it.

### Frame-rate integration contract

The demo deliberately keeps two settings separate:

- each import/refresh operator owns a per-item `target_fps` ceiling, default 60;
- `WindowManager.animthumb_preview_fps` is the current 8–60 FPS live gallery
  ceiling, default 10.

The live value must be connected to both frame lookup and scheduling:

```python
# Live playback: affects loaded caches immediately.
icon_id = preview_cache.icon_id(item_id, now_ms, fps_limit=preview_fps)
interval = preview_cache.next_interval_seconds(
    visible_ids,
    now_ms,
    fps_limit=preview_fps,
)
```

The `fps_limit` keyword is optional. Omitting it preserves uncapped,
source-boundary playback for projects that provide their own scheduler. The
demo’s `preview_engine.preview_frame_rate()` reads and clamps the registered
WindowManager value for both scheduler and panel-draw calls.
`preview_cache.py` also applies a cache’s stored `source_fps` independently, so
a high global ceiling cannot make a slower encoded source advance faster.
`preview_cache.display_frame_rate()` exposes that same resolved per-item rate
for UI labels:

```python
visible_fps = preview_cache.display_frame_rate(
    item_id,
    fps_limit=preview_fps,
)
```

The demo uses this result beneath each thumbnail, so moving the settings slider
immediately updates both live playback and the displayed FPS number. The number
is the active display rate—`min(global ceiling, cache rate, native source
rate)`—rather than immutable ingest metadata.

Changing the live ceiling does not rebuild caches. Use a card's arrow menu and
**Refresh with New FPS Settings** to change that item's import sampling,
sequence order, or trim range while preserving its cache identity.

### Mixed playback frame rates

Each cache retains its own cumulative frame boundaries and effective rate.
`preview_cache.next_interval_seconds()` calculates each visible item’s next
boundary independently and returns only the earliest one to the shared timer.
At that event:

- a 12 FPS thumbnail advances only on its own roughly 83 ms boundaries;
- a 24 FPS thumbnail advances on its own roughly 42 ms boundaries;
- a 60 FPS thumbnail can advance on roughly 17 ms boundaries; and
- static thumbnails never create animation ticks.

The engine compares signatures per item and redraws only registered UI regions
containing an item that changed. When several rates share one N-panel region,
the scheduler wakes for the earliest real boundary among them—the same policy
as the Beyond VRM implementation. The region's redraw cadence can therefore
approach the union of distinct boundaries: a 30 FPS and 12 FPS pair can cost up
to roughly 42 redraw opportunities per second when their boundaries do not
coincide. It is still capped by the live ceiling and the 60 FPS scheduler
minimum interval. Unchanged thumbnails retain their frame; they are never
advanced, decoded, or regenerated at a neighbor's rate.

### Cache location and item actions

By default, caches live in Blender's persistent extension-user storage, not in
the installed extension source. The extension Preferences panel exposes an
optional **Thumbnail Cache Location** directory. `paths.cache_root()` is the
single integration point, so changing the preference affects ingest, discovery,
refresh, and deletion consistently.

Changing the setting never moves or deletes an existing cache. The gallery
rescans the newly selected root; switching back restores discovery of caches in
the previous root. Integrations that want migration should implement it as a
separate, explicit operation.

The per-card arrow menu contains:

- **Refresh with New FPS Settings**, which atomically rebuilds the same cache
  identity;
- **Open Thumbnail Cache Directory**, which uses Blender's path-open operator
  with a capability-gated OS fallback; and
- **Delete Thumbnail**, which removes only that generated item directory.

## Cache schema

`metadata.json` is the disk/runtime boundary:

```json
{
  "schema_version": 1,
  "item_id": "e0c65c...",
  "name": "Walk",
  "source_paths": ["/absolute/path/walk.gif"],
  "width": 512,
  "height": 512,
  "media_kind": "MEDIA",
  "cache_image_format": "WEBP",
  "trim_media": false,
  "trim_start_frame": 1,
  "trim_end_frame": 72,
  "duration_ms": 6000,
  "preview_duration_ms": 6000,
  "source_duration_ms": 6000,
  "target_fps": 60.0,
  "source_fps": 12.0,
  "sample_fps": 12.0,
  "effective_fps": 11.666667,
  "frames": [
    {
      "index": 0,
      "start_ms": 0,
      "end_ms": 100,
      "file": "frame_000__00000000_00000100.webp"
    }
  ]
}
```

Timing is stored cumulatively. The engine selects the frame whose
`start_ms <= loop_time < end_ms`, then reschedules itself for the next real
boundary on the configured playback sampling grid instead of assuming every
timer tick means a new frame. `target_fps` is the user ceiling, `source_fps` is
the detected encoded-media rate, `sample_fps` is the FFmpeg extraction rate,
and `effective_fps` records the rate the completed cache actually represents.
`duration_ms`/`preview_duration_ms` describe the cached playback loop, while
`source_duration_ms` preserves the full probed input duration. They match within
frame-rounding tolerance unless the user explicitly enabled Trim Media.

FPS, source/preview duration, media kind, cache format, sequence order, and trim
fields are additive in schema version 1. Older schema-v1 PNG caches without
them continue to load.

## Playback performance contract

The fast path—panel redraw and modal `TIMER` events—must remain memory-only:

- no directory scans;
- no metadata reads;
- no image decode;
- no preview loads;
- no cache generation; and
- no full-area or full-viewport redraw.

Disk work belongs in ingest, refresh, deletion, load-post rebuild, or the first
visible-item load.

The settings-cog popover exposes:

- **Thumbnail Scale**, which drives both the visual icon scale and DPI-aware
  column wrapping and can be dragged up to 2.0×;
- **Live Playback FPS Ceiling**, which immediately caps live thumbnail sampling
  and updates each card’s active FPS label from 8 through 60 FPS; and
- **Optimized Playback Mode**, which pauses only for timeline playback,
  `(recent depsgraph activity AND real viewport drag/transform)`, or scrolling
  inside the owning preview UI region.

Plain mouse movement, background depsgraph chatter, clicks elsewhere, and
scrolling outside the gallery do not renew a pause.

Changing the preview rate does not decode or regenerate anything in the panel
draw path. Lower values immediately reduce redraw pressure for existing
caches. Raising it above a cache or source rate never upscales that item. A
visible 60 FPS item can make its shared N-panel region redraw about six times as
often as a 10 FPS item, but lower-rate neighbors keep their own frame
boundaries. Optimized mode, visible-page filtering, and one shared scheduler
keep that work bounded to the gallery that is actually on screen.

Cache generation is intentionally outside this live-performance contract. Full
source duration may produce many disk frames; the import UI warns above 1,200
estimated frames without silently changing user settings.

## Why normal Blender previews

Custom GPU drawing is unnecessary for this use case. Blender already composites
preview icons efficiently. The expensive failure modes are usually Python-side:
loading frames repeatedly, rescanning folders, redrawing broad areas, or
advancing hidden items.

The demo uses the official preview collection API available in both
[Blender 4.2](https://docs.blender.org/api/4.2/bpy.utils.previews.html) and
[Blender 5.2](https://docs.blender.org/api/5.2/bpy.utils.previews.html), plus
the versioned timer and WindowManager APIs.

## Development and validation

```bash
uv sync
./tools/lint.sh
./tools/test.sh
```

Runtime validation should cover every declared host version and UI scale. The
minimum regression matrix is:

- Blender 4.2 and the newest supported version;
- 1×, 1.5×, and 2× UI scale;
- ordinary motion, real held drags, G/R/S, NDOF, and missed releases;
- scrolling inside and outside the N-panel gallery;
- timeline playback and recovery;
- sleep/wake timer replacement;
- visible-page filtering; and
- zero filesystem access during hot playback.

This repository includes pure-Python cache tests plus Blender registration,
custom-location, full-range ingest, per-item refresh/trim, media-matrix, and
modal-engine smoke tests. Visual layout evaluation remains a manual
host-application check.

## License and dependency notes

The extension code is GPL-3.0-or-later. `imageio-ffmpeg` is installed at
runtime from PyPI and is not redistributed in this source repository; it uses
the BSD-2-Clause license. Its platform wheels include FFmpeg executables whose
applicable configuration and license information are documented by the
upstream project.
