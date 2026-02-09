"""
Buffer subsystem - pixel buffers and drawing primitives.

Modules:
    framebuffer: Core pixel buffer with rotation and depth support
    draw: Shape drawing primitives (lines, rectangles, circles, etc.)
"""
from .framebuffer import FrameBuffer, BLACK, WHITE, DARK_GRAY, LIGHT_GRAY
from .draw import DrawBuffer

__all__ = [
    "FrameBuffer",
    "DrawBuffer",
    "BLACK",
    "WHITE",
    "DARK_GRAY",
    "LIGHT_GRAY",
]
