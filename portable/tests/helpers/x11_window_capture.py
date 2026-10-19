"""Capture only the caller's mapped Tk window; stdlib + installed Xlib.

This never captures a whole desktop, discovers other windows, or fabricates
pixels. Intended only for the isolated Linux CI display used by UI tests.
"""
import ctypes
import ctypes.util
import os
from pathlib import Path
import struct
import zlib


class XImage(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_int), ('height', ctypes.c_int), ('xoffset', ctypes.c_int),
        ('format', ctypes.c_int), ('data', ctypes.c_void_p), ('byte_order', ctypes.c_int),
        ('bitmap_unit', ctypes.c_int), ('bitmap_bit_order', ctypes.c_int),
        ('bitmap_pad', ctypes.c_int), ('depth', ctypes.c_int),
        ('bytes_per_line', ctypes.c_int), ('bits_per_pixel', ctypes.c_int),
        ('red_mask', ctypes.c_ulong), ('green_mask', ctypes.c_ulong),
        ('blue_mask', ctypes.c_ulong),
    ]


def _chunk(kind, payload):
    return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload))


def capture(root, destination):
    root.update_idletasks()
    root.update()
    if not root.winfo_viewable() or not root.winfo_ismapped():
        raise RuntimeError('Screenshot requires a real mapped Tk window')
    width, height = root.winfo_width(), root.winfo_height()
    if not 100 <= width <= 4096 or not 100 <= height <= 4096:
        raise RuntimeError('Unexpected test window dimensions')
    library = ctypes.util.find_library('X11')
    if not library:
        raise RuntimeError('Xlib is required for the CI window capture')
    x = ctypes.CDLL(library)
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                           ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
    x.XGetImage.restype = ctypes.POINTER(XImage)
    x.XDestroyImage.argtypes = [ctypes.POINTER(XImage)]
    display = x.XOpenDisplay(os.environ.get('DISPLAY', '').encode())
    if not display:
        raise RuntimeError('Cannot open the isolated CI display')
    image = None
    try:
        x.XSync(display, 0)
        image = x.XGetImage(display, root.winfo_id(), 0, 0, width, height,
                            ctypes.c_ulong(-1).value, 2)
        if not image:
            raise RuntimeError('XGetImage did not return window pixels')
        info = image.contents
        if info.bits_per_pixel not in (24, 32) or not info.data:
            raise RuntimeError('Unsupported X11 image format')
        pixels = ctypes.string_at(info.data, info.bytes_per_line * height)
        channels = []
        for mask in (info.red_mask, info.green_mask, info.blue_mask):
            if not mask:
                raise RuntimeError('Unsupported X11 color mask')
            shift = (mask & -mask).bit_length() - 1
            channels.append((mask, shift, mask >> shift))
        size = info.bits_per_pixel // 8
        order = 'little' if info.byte_order == 0 else 'big'
        rows = bytearray()
        colors = set()
        for row in range(height):
            rows.append(0)
            start = row * info.bytes_per_line
            for col in range(width):
                offset = start + col * size
                pixel = int.from_bytes(pixels[offset:offset + size], order)
                rgb = tuple(((pixel & mask) >> shift) * 255 // maximum for mask, shift, maximum in channels)
                rows.extend(rgb)
                if len(colors) < 16:
                    colors.add(rgb)
        if len(colors) < 4:
            raise RuntimeError('Captured window is unexpectedly empty or uniform')
        payload = b'\x89PNG\r\n\x1a\n'
        payload += _chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
        payload += _chunk(b'IDAT', zlib.compress(bytes(rows), 6)) + _chunk(b'IEND', b'')
        Path(destination).write_bytes(payload)
        return dict(width=width, height=height, bytes=len(payload),
                    capture='XGetImage of the test-owned mapped Tk window')
    finally:
        if image:
            x.XDestroyImage(image)
        x.XCloseDisplay(display)
