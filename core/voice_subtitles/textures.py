"""Pictures out of the game's own texture assets (hero portraits for the Voice Subtitles tab).

A cooked Texture2D keeps, after its header, the platform data: the size,
the pixel format as a string ("PF_BC7"), then each mip's pixels followed by
that mip's own size. UI textures have one mip, so the picture is the run of
bytes, exactly as long as the format needs, that ends where its size is
written. Pillow decodes the block-compressed formats itself.
"""
from __future__ import annotations

import re
import struct

# Pillow's "bcn" decoder number and the bytes in a 4x4 block.
BLOCK_FORMATS = {"PF_DXT1": (1, 8), "PF_DXT3": (2, 16), "PF_DXT5": (3, 16), "PF_BC7": (7, 16)}
MAX_SIDE = 8192
_FORMAT_STRING = re.compile(rb"(PF_[A-Z0-9_]+)\x00")


def decode_texture(data: bytes):
    """The texture's first mip as a PIL image, or None for a format or layout this does not know."""
    from PIL import Image

    for match in reversed(list(_FORMAT_STRING.finditer(data))):
        fmt = match.group(1).decode("ascii")
        start = match.start()
        if start < 16 or struct.unpack_from("<i", data, start - 4)[0] != len(fmt) + 1:
            continue  # a name in the name table, not the serialised string
        width, height = struct.unpack_from("<ii", data, start - 16)
        if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
            continue
        if fmt in BLOCK_FORMATS:
            code, block = BLOCK_FORMATS[fmt]
            padded = ((width + 3) // 4 * 4, (height + 3) // 4 * 4)
            length = padded[0] // 4 * (padded[1] // 4) * block
        elif fmt == "PF_B8G8R8A8":
            padded, length = (width, height), width * height * 4
        else:
            return None
        trailer = struct.pack("<iii", width, height, 1)
        end = match.end()
        for offset in range(end, min(end + 64, len(data) - length)):
            if data[offset + length:offset + length + 12] != trailer:
                continue
            pixels = data[offset:offset + length]
            if fmt == "PF_B8G8R8A8":
                return Image.frombytes("RGBA", padded, pixels, "raw", "BGRA")
            return Image.frombytes("RGBA", padded, pixels, "bcn", code).crop((0, 0, width, height))
    return None


def texture_png(data: bytes, path) -> bool:
    """Write the texture as a PNG; False when it could not be read."""
    image = decode_texture(data)
    if image is None:
        return False
    image.save(path, "PNG", optimize=True)
    return True
