# Third-party notices

## imageio-ffmpeg

This extension redistributes unmodified platform wheels for
`imageio-ffmpeg==0.6.0` from PyPI. The compatible wheel is installed through
Blender's manifest-managed extension environment. A runtime download into
persistent extension-user storage is retained only as an explicit repair
fallback.

- Project: https://github.com/imageio/imageio-ffmpeg
- License: BSD-2-Clause
- Package: https://pypi.org/project/imageio-ffmpeg/

The platform wheels include FFmpeg executables. See the upstream package and
FFmpeg licensing documentation for the exact binary configuration and
applicable license terms.

## Pillow

This extension redistributes unmodified CPython 3.11 and 3.13 platform wheels
for `Pillow==12.3.0` from PyPI. Pillow supplies the animated WebP decoder used
when the FFmpeg build does not decode WebP animation chunks. Blender installs
the compatible wheel through the manifest; a persistent extension-user
download is retained only as an explicit repair fallback.

- Project: https://python-pillow.github.io/
- License: MIT-CMU
- Package: https://pypi.org/project/Pillow/
