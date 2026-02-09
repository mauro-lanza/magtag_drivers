"""
DrawBuffer - Shape Drawing Primitives
=====================================
Extends FrameBuffer with geometric shapes and bitmaps.
"""

from .framebuffer import FrameBuffer, BLACK, WHITE, DARK_GRAY, LIGHT_GRAY, _BIT_MASKS, _INV_MASKS
__all__ = ["DrawBuffer", "BLACK", "WHITE", "DARK_GRAY", "LIGHT_GRAY"]


class DrawBuffer(FrameBuffer):
    """
    FrameBuffer with shape drawing capabilities.
    """

    # =========================================================================
    # Line
    # =========================================================================

    def line(self, x0: int, y0: int, x1: int, y1: int, color: int = BLACK) -> None:
        """Draw a line using Bresenham's algorithm with clipping."""
        # Cohen-Sutherland clipping constants
        INSIDE = 0
        LEFT = 1
        RIGHT = 2
        BOTTOM = 4
        TOP = 8

        xmin, xmax = 0, self.width - 1
        ymin, ymax = 0, self.height - 1

        def _compute_outcode(x, y):
            code = INSIDE
            if x < xmin: code |= LEFT
            elif x > xmax: code |= RIGHT
            if y < ymin: code |= BOTTOM
            elif y > ymax: code |= TOP
            return code

        code0 = _compute_outcode(x0, y0)
        code1 = _compute_outcode(x1, y1)

        # Clipping loop
        while True:
            if not (code0 | code1):  # Both inside
                break
            elif code0 & code1:  # Both outside same zone
                return
            else:
                # Pick outside point
                outcode = code0 if code0 else code1
                x, y = 0, 0

                if outcode & TOP:
                    x = x0 + (x1 - x0) * (ymax - y0) // (y1 - y0)
                    y = ymax
                elif outcode & BOTTOM:
                    x = x0 + (x1 - x0) * (ymin - y0) // (y1 - y0)
                    y = ymin
                elif outcode & RIGHT:
                    y = y0 + (y1 - y0) * (xmax - x0) // (x1 - x0)
                    x = xmax
                elif outcode & LEFT:
                    y = y0 + (y1 - y0) * (xmin - x0) // (x1 - x0)
                    x = xmin

                if outcode == code0:
                    x0, y0 = int(x), int(y)
                    code0 = _compute_outcode(x0, y0)
                else:
                    x1, y1 = int(x), int(y)
                    code1 = _compute_outcode(x1, y1)

        # Draw clipped line
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0 = y0, x0
            x1, y1 = y1, x1
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0

        dx = x1 - x0
        dy = abs(y1 - y0)
        err = dx // 2
        ystep = 1 if y0 < y1 else -1

        # Retrieve fast pixel setter to avoid lookup in loop
        # We need to handle rotation manually here if we want max speed,
        # but using pixel_fast is a good middle ground after clipping.
        # For maximum speed, we unroll the rotation check once:

        is_swapped, x_flip, y_flip = self._rot_props
        phys_w, phys_h = self._phys_w, self._phys_h
        effective_col = self._effective_color(color)

        # Pre-calculate transform factors
        # Logical (lx, ly) -> Physical (px, py)
        # If steep, (lx, ly) are actually (y, x) in loop variables

        y = y0
        for x in range(x0, x1 + 1):
            # Resolve logical coordinates
            lx, ly = (y, x) if steep else (x, y)

            # Inline Transform
            if is_swapped:
                px, py = ly, lx
            else:
                px, py = lx, ly

            if x_flip: px = phys_w - 1 - px
            if y_flip: py = phys_h - 1 - py

            # Inline Pixel Set
            if self._depth == 1:
                self._set_pixel_1bit(px, py, effective_col)
            else:
                self._set_pixel_2bit(px, py, effective_col)

            err -= dy
            if err < 0:
                y += ystep
                err += dx

    # =========================================================================
    # Rectangle
    # =========================================================================

    def rect(self, x: int, y: int, w: int, h: int, color: int = BLACK) -> None:
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    def fill_rect(self, x: int, y: int, w: int, h: int, color: int = BLACK) -> None:
        # Clip to bounds
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        if x + w > self.width:
            w = self.width - x
        if y + h > self.height:
            h = self.height - y

        if w <= 0 or h <= 0:
            return

        # Use optimized hline (which handles byte-aligned writes)
        for row in range(h):
            self.hline(x, y + row, w, color)

    # =========================================================================
    # Circle (Bresenham Optimized)
    # =========================================================================

    def circle(self, cx: int, cy: int, r: int, color: int = BLACK) -> None:
        """Draw circle outline using Bresenham's algorithm (integer only)."""
        f = 1 - r
        ddF_x = 1
        ddF_y = -2 * r
        x = 0
        y = r

        self.pixel(cx, cy + r, color)
        self.pixel(cx, cy - r, color)
        self.pixel(cx + r, cy, color)
        self.pixel(cx - r, cy, color)

        while x < y:
            if f >= 0:
                y -= 1
                ddF_y += 2
                f += ddF_y
            x += 1
            ddF_x += 2
            f += ddF_x

            self.pixel(cx + x, cy + y, color)
            self.pixel(cx - x, cy + y, color)
            self.pixel(cx + x, cy - y, color)
            self.pixel(cx - x, cy - y, color)
            self.pixel(cx + y, cy + x, color)
            self.pixel(cx - y, cy + x, color)
            self.pixel(cx + y, cy - x, color)
            self.pixel(cx - y, cy - x, color)

    def fill_circle(self, cx: int, cy: int, r: int, color: int = BLACK) -> None:
        """Draw filled circle using Bresenham's algorithm."""
        self.vline(cx, cy - r, 2 * r + 1, color)

        f = 1 - r
        ddF_x = 1
        ddF_y = -2 * r
        x = 0
        y = r

        while x < y:
            if f >= 0:
                y -= 1
                ddF_y += 2
                f += ddF_y
            x += 1
            ddF_x += 2
            f += ddF_x

            # Draw horizontal lines between mirror points
            self.vline(cx + x, cy - y, 2 * y + 1, color)
            self.vline(cx - x, cy - y, 2 * y + 1, color)
            self.vline(cx + y, cy - x, 2 * x + 1, color)
            self.vline(cx - y, cy - x, 2 * x + 1, color)

    # =========================================================================
    # Triangle
    # =========================================================================

    def triangle(self, x0: int, y0: int, x1: int, y1: int,
                 x2: int, y2: int, color: int = BLACK) -> None:
        self.line(x0, y0, x1, y1, color)
        self.line(x1, y1, x2, y2, color)
        self.line(x2, y2, x0, y0, color)

    def fill_triangle(self, x0: int, y0: int, x1: int, y1: int,
                      x2: int, y2: int, color: int = BLACK) -> None:
        # Sort vertices by y
        if y0 > y1: x0, y0, x1, y1 = x1, y1, x0, y0
        if y1 > y2: x1, y1, x2, y2 = x2, y2, x1, y1
        if y0 > y1: x0, y0, x1, y1 = x1, y1, x0, y0

        if y0 == y2: # Degenerate
            min_x = min(x0, x1, x2)
            max_x = max(x0, x1, x2)
            self.hline(min_x, y0, max_x - min_x + 1, color)
            return

        # Scanline fill
        # Upper part
        if y1 > y0:
            for y in range(y0, y1 + 1):
                xa = x0 + (x1 - x0) * (y - y0) // (y1 - y0)
                xb = x0 + (x2 - x0) * (y - y0) // (y2 - y0)
                if xa > xb: xa, xb = xb, xa
                self.hline(xa, y, xb - xa + 1, color)

        # Lower part
        if y2 > y1:
            for y in range(y1 + 1, y2 + 1):
                xa = x1 + (x2 - x1) * (y - y1) // (y2 - y1)
                xb = x0 + (x2 - x0) * (y - y0) // (y2 - y0)
                if xa > xb: xa, xb = xb, xa
                self.hline(xa, y, xb - xa + 1, color)

    # =========================================================================
    # Rounded Rectangle
    # =========================================================================

    def rounded_rect(self, x: int, y: int, w: int, h: int,
                     r: int, color: int = BLACK) -> None:
        r = min(r, w // 2, h // 2)
        if r <= 0:
            self.rect(x, y, w, h, color)
            return

        # Straight edges
        self.hline(x + r, y, w - 2 * r, color)           # Top
        self.hline(x + r, y + h - 1, w - 2 * r, color)   # Bottom
        self.vline(x, y + r, h - 2 * r, color)           # Left
        self.vline(x + w - 1, y + r, h - 2 * r, color)   # Right

        # Corner arcs
        f = 1 - r
        ddF_x = 1
        ddF_y = -2 * r
        cx, cy = 0, r

        while cx < cy:
            if f >= 0:
                cy -= 1
                ddF_y += 2
                f += ddF_y
            cx += 1
            ddF_x += 2
            f += ddF_x

            self.pixel(x + r - cx, y + r - cy, color)
            self.pixel(x + r - cy, y + r - cx, color)
            self.pixel(x + w - 1 - r + cx, y + r - cy, color)
            self.pixel(x + w - 1 - r + cy, y + r - cx, color)
            self.pixel(x + r - cx, y + h - 1 - r + cy, color)
            self.pixel(x + r - cy, y + h - 1 - r + cx, color)
            self.pixel(x + w - 1 - r + cx, y + h - 1 - r + cy, color)
            self.pixel(x + w - 1 - r + cy, y + h - 1 - r + cx, color)

    # =========================================================================
    # Bitmap Blit
    # =========================================================================

    def blit(self, bitmap: bytes, x: int, y: int, w: int, h: int, color: int = BLACK) -> None:
        """Draw 1-bit bitmap with transparent background."""
        if x >= self.width or y >= self.height or x + w <= 0 or y + h <= 0: return

        # Clip
        row_start = max(0, -y)
        row_end = min(h, self.height - y)
        col_start = max(0, -x)
        col_end = min(w, self.width - x)
        if row_start >= row_end or col_start >= col_end: return

        # Context
        ctx = self.get_blit_context(color)

        if self.depth == 1:
            self._blit_1bit(ctx, bitmap, w, x, y, row_start, row_end, col_start, col_end)
        else:
            self._blit_2bit(ctx, bitmap, w, x, y, row_start, row_end, col_start, col_end)

    def _blit_1bit(self, ctx, bmp, w, x, y, r_start, r_end, c_start, c_end):
        buf, pw, ph, stride, (swap, xf, yf), col, _ = ctx
        row_bytes = (w + 7) // 8

        # Unrolled Logic
        if not swap:
            dx_start = pw - 1 - x if xf else x
            dx_step = -1 if xf else 1
            dy_start = ph - 1 - y if yf else y
            dy_step = -1 if yf else 1

            for row in range(r_start, r_end):
                py = dy_start + (row * dy_step)
                bmp_off = row * row_bytes
                row_off = py * stride
                for col_idx in range(c_start, c_end):
                    if not (bmp[bmp_off + (col_idx >> 3)] & (0x80 >> (col_idx & 7))): continue
                    px = dx_start + (col_idx * dx_step)
                    idx = row_off + (px >> 3)
                    if col: buf[idx] |= _BIT_MASKS[px & 7]
                    else:   buf[idx] &= _INV_MASKS[px & 7]
        else:
            dx_start = pw - 1 - y if xf else y
            dx_step = -1 if xf else 1
            dy_start = ph - 1 - x if yf else x
            dy_step = -1 if yf else 1

            for row in range(r_start, r_end):
                px = dx_start + (row * dx_step)
                bmp_off = row * row_bytes
                for col_idx in range(c_start, c_end):
                    if not (bmp[bmp_off + (col_idx >> 3)] & (0x80 >> (col_idx & 7))): continue
                    py = dy_start + (col_idx * dy_step)
                    idx = py * stride + (px >> 3)
                    if col: buf[idx] |= _BIT_MASKS[px & 7]
                    else:   buf[idx] &= _INV_MASKS[px & 7]

    def _blit_2bit(self, ctx, bmp, w, x, y, r_start, r_end, c_start, c_end):
        # Fallback to safe pixel setting for 2-bit
        # (Could be optimized further, but 2-bit blit is rare)
        row_bytes = (w + 7) // 8
        color = ctx[5] # effective color

        # We need to call internal physical setter manually or use logical pixel()
        # Using logical pixel() for simplicity as 2-bit isn't the speed bottleneck
        for row in range(r_start, r_end):
            bmp_off = row * row_bytes
            for col_idx in range(c_start, c_end):
                if bmp[bmp_off + (col_idx >> 3)] & (0x80 >> (col_idx & 7)):
                    self.pixel_fast(x + col_idx, y + row, color)
