"""
Shapes - Drawing Primitives for FrameBuffer
============================================
Standalone shape drawing functions that operate on a FrameBuffer instance.

Usage:
    from framebuffer import FrameBuffer
    from shapes import line, rect, fill_rect, circle, triangle, rounded_rect, blit

    fb = FrameBuffer(128, 296, rotation=90)
    fb.clear()

    # Draw shapes
    line(fb, 0, 0, 100, 50)
    rect(fb, 20, 20, 60, 40)
    fill_rect(fb, 100, 10, 30, 30)
    circle(fb, 150, 64, 30)
    triangle(fb, 10, 10, 50, 80, 90, 30)
"""

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from framebuffer import FrameBuffer


def _isqrt(n: int) -> int:
    """Fast integer square root via Newton's method."""
    if n < 2:
        return n
    x = n
    y = (x + 1) >> 1
    while y < x:
        x = y
        y = (x + n // x) >> 1
    return x


def line(fb: "FrameBuffer", x0: int, y0: int, x1: int, y1: int, black: bool = True) -> None:
    """Draw a line using Bresenham's algorithm.

    Args:
        fb: FrameBuffer instance
        x0, y0: Start point
        x1, y1: End point
        black: Line color (True=black, False=white)
    """
    # Optimize for axis-aligned lines
    if y0 == y1:
        if x0 > x1:
            x0, x1 = x1, x0
        fb.hline(x0, y0, x1 - x0 + 1, black)
        return
    if x0 == x1:
        if y0 > y1:
            y0, y1 = y1, y0
        fb.vline(x0, y0, y1 - y0 + 1, black)
        return

    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    while True:
        fb.pixel(x0, y0, black)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def rect(fb: "FrameBuffer", x: int, y: int, w: int, h: int, black: bool = True) -> None:
    """Draw a rectangle outline.

    Args:
        fb: FrameBuffer instance
        x, y: Top-left corner
        w, h: Width and height
        black: Line color
    """
    fb.hline(x, y, w, black)
    fb.hline(x, y + h - 1, w, black)
    fb.vline(x, y, h, black)
    fb.vline(x + w - 1, y, h, black)


def fill_rect(fb: "FrameBuffer", x: int, y: int, w: int, h: int, black: bool = True) -> None:
    """Draw a filled rectangle.

    Args:
        fb: FrameBuffer instance
        x, y: Top-left corner
        w, h: Width and height
        black: Fill color
    """
    # Clip to bounds
    if x < 0:
        w += x
        x = 0
    if y < 0:
        h += y
        y = 0
    if x + w > fb.width:
        w = fb.width - x
    if y + h > fb.height:
        h = fb.height - y

    if w <= 0 or h <= 0:
        return

    # Draw scanlines
    for row in range(h):
        fb.hline(x, y + row, w, black)


def circle(fb: "FrameBuffer", cx: int, cy: int, r: int, black: bool = True) -> None:
    """Draw a circle outline using midpoint algorithm.

    Args:
        fb: FrameBuffer instance
        cx, cy: Center point
        r: Radius
        black: Line color
    """
    if r <= 0:
        return
    x, y, err = r, 0, 0
    while x >= y:
        fb.pixel(cx + x, cy + y, black)
        fb.pixel(cx + y, cy + x, black)
        fb.pixel(cx - y, cy + x, black)
        fb.pixel(cx - x, cy + y, black)
        fb.pixel(cx - x, cy - y, black)
        fb.pixel(cx - y, cy - x, black)
        fb.pixel(cx + y, cy - x, black)
        fb.pixel(cx + x, cy - y, black)
        y += 1
        err += 1 + 2 * y
        if 2 * (err - x) + 1 > 0:
            x -= 1
            err += 1 - 2 * x


def fill_circle(fb: "FrameBuffer", cx: int, cy: int, r: int, black: bool = True) -> None:
    """Draw a filled circle using scanlines.

    Args:
        fb: FrameBuffer instance
        cx, cy: Center point
        r: Radius
        black: Fill color
    """
    if r <= 0:
        return
    r_sq = r * r
    for dy in range(-r, r + 1):
        dx = _isqrt(r_sq - dy * dy)
        fb.hline(cx - dx, cy + dy, 2 * dx + 1, black)


def triangle(fb: "FrameBuffer", x0: int, y0: int, x1: int, y1: int, x2: int, y2: int, black: bool = True) -> None:
    """Draw a triangle outline.

    Args:
        fb: FrameBuffer instance
        x0, y0: First vertex
        x1, y1: Second vertex
        x2, y2: Third vertex
        black: Line color
    """
    line(fb, x0, y0, x1, y1, black)
    line(fb, x1, y1, x2, y2, black)
    line(fb, x2, y2, x0, y0, black)


def fill_triangle(fb: "FrameBuffer", x0: int, y0: int, x1: int, y1: int, x2: int, y2: int, black: bool = True) -> None:
    """Draw a filled triangle using scanline algorithm.

    Args:
        fb: FrameBuffer instance
        x0, y0: First vertex
        x1, y1: Second vertex
        x2, y2: Third vertex
        black: Fill color
    """
    # Sort vertices by y coordinate (y0 <= y1 <= y2)
    if y0 > y1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    if y1 > y2:
        x1, y1, x2, y2 = x2, y2, x1, y1
    if y0 > y1:
        x0, y0, x1, y1 = x1, y1, x0, y0

    if y0 == y2:
        # Degenerate triangle (all points on same horizontal line)
        min_x = min(x0, x1, x2)
        max_x = max(x0, x1, x2)
        fb.hline(min_x, y0, max_x - min_x + 1, black)
        return

    # Scanline fill
    for y in range(y0, y2 + 1):
        if y < y1:
            # Upper part of triangle
            if y1 != y0:
                xa = x0 + (x1 - x0) * (y - y0) // (y1 - y0)
            else:
                xa = x0
            if y2 != y0:
                xb = x0 + (x2 - x0) * (y - y0) // (y2 - y0)
            else:
                xb = x0
        else:
            # Lower part of triangle
            if y2 != y1:
                xa = x1 + (x2 - x1) * (y - y1) // (y2 - y1)
            else:
                xa = x1
            if y2 != y0:
                xb = x0 + (x2 - x0) * (y - y0) // (y2 - y0)
            else:
                xb = x0

        if xa > xb:
            xa, xb = xb, xa
        fb.hline(xa, y, xb - xa + 1, black)


def rounded_rect(fb: "FrameBuffer", x: int, y: int, w: int, h: int, r: int, black: bool = True) -> None:
    """Draw a rounded rectangle outline.

    Args:
        fb: FrameBuffer instance
        x, y: Top-left corner
        w, h: Width and height
        r: Corner radius
        black: Line color
    """
    r = min(r, w // 2, h // 2)
    if r <= 0:
        rect(fb, x, y, w, h, black)
        return

    # Draw straight edges
    fb.hline(x + r, y, w - 2 * r, black)          # Top
    fb.hline(x + r, y + h - 1, w - 2 * r, black)  # Bottom
    fb.vline(x, y + r, h - 2 * r, black)          # Left
    fb.vline(x + w - 1, y + r, h - 2 * r, black)  # Right

    # Draw corners using circle quadrants
    px = r
    py = 0
    err = 0

    while px >= py:
        # Top-left corner
        fb.pixel(x + r - px, y + r - py, black)
        fb.pixel(x + r - py, y + r - px, black)
        # Top-right corner
        fb.pixel(x + w - 1 - r + px, y + r - py, black)
        fb.pixel(x + w - 1 - r + py, y + r - px, black)
        # Bottom-left corner
        fb.pixel(x + r - px, y + h - 1 - r + py, black)
        fb.pixel(x + r - py, y + h - 1 - r + px, black)
        # Bottom-right corner
        fb.pixel(x + w - 1 - r + px, y + h - 1 - r + py, black)
        fb.pixel(x + w - 1 - r + py, y + h - 1 - r + px, black)

        py += 1
        err += 1 + 2 * py
        if 2 * (err - px) + 1 > 0:
            px -= 1
            err += 1 - 2 * px


def blit(fb: "FrameBuffer", bitmap: bytes, x: int, y: int, w: int, h: int, black: bool = True) -> None:
    """
    Draw a 1-bit bitmap (transparent background, only set bits drawn).

    Optimized with inlined transforms and cached lookups inspired by
    Adafruit bitmap_label's fallback and GxEPD2's byte-level operations.

    Args:
        fb: FrameBuffer instance
        bitmap: 1-bit image data (MSB first, row-major)
        x, y: Top-left position
        w, h: Bitmap dimensions
        black: Color for set bits (transparent background)
    """
    # Early exit if completely off-screen
    fb_width = fb.width
    fb_height = fb.height
    if x >= fb_width or y >= fb_height or x + w <= 0 or y + h <= 0:
        return

    row_bytes = (w + 7) // 8

    # Clip to visible region
    row_start = max(0, -y)
    row_end = min(h, fb_height - y)
    col_start = max(0, -x)
    col_end = min(w, fb_width - x)

    # Get cached blit context to avoid repeated attribute lookups
    # This is critical for performance in the tight inner loop
    buf, phys_w, phys_h, phys_w_bytes, rotation_info, effective_black = fb.get_blit_context(black)
    is_swapped, x_flip, y_flip = rotation_info

    # Inlined pixel setting - avoids 3 method calls per pixel
    for row in range(row_start, row_end):
        ly = y + row
        row_offset = row * row_bytes
        for col in range(col_start, col_end):
            byte_idx = row_offset + (col >> 3)
            if bitmap[byte_idx] & (0x80 >> (col & 7)):
                lx = x + col

                # Inline transform (from fb._transform)
                if is_swapped:
                    px, py = ly, lx
                else:
                    px, py = lx, ly
                if x_flip:
                    px = phys_w - 1 - px
                if y_flip:
                    py = phys_h - 1 - py

                # Inline set_pixel_physical
                bidx = py * phys_w_bytes + (px >> 3)
                bit = px & 7
                if effective_black:
                    buf[bidx] &= ~(1 << (7 - bit)) & 0xFF
                else:
                    buf[bidx] |= 1 << (7 - bit)
