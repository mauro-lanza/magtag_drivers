"""
TextRenderer - Font Rendering with Multi-Font Support and Caching
=================================================================
Renders text onto a DrawBuffer using BF2 fonts.

Features:
- Multi-font stacking (base + extension fonts for icons, CJK, etc.)
- LRU glyph cache for performance
- Alignment support (left, center, right)
- Scaling support
- Pre-clipping optimization for partially visible text
- Font subsetting via add_font()

Usage:
    from buffer.draw import DrawBuffer
    from text.renderer import TextRenderer

    fb = DrawBuffer(128, 296, rotation=90)
    text = TextRenderer(fb)

    # Load base font
    text.load_font("fonts/basic.bf2")

    # Optional: add extension fonts (icons, CJK, etc.)
    text.add_font("fonts/icons.bf2", optional=True)

    # Draw text - glyphs resolved from fonts in load order
    text.draw("Hello World!", 10, 10)

    # Measure before drawing for layout
    w = text.measure_width("Hello")
    h = text.measure_height()
"""

from collections import OrderedDict
from .bf2 import BF2Font


class TextRenderer:
    """
    Text renderer with multi-font support and glyph caching.

    Resolves glyphs by searching fonts in load order (first match wins).
    Uses an LRU cache to avoid re-reading glyph data from flash storage.

    Args:
        fb: DrawBuffer instance to render onto
        cache_size: Maximum glyph cache size in bytes (default 4096)
    """

    def __init__(self, fb, cache_size: int = 4096):
        self._fb = fb
        self._cache = OrderedDict()
        self._cache_max = cache_size
        self._cache_size = 0
        self._fonts = []
        self._base_h = 8  # Fallback height before font is loaded

    def close(self):
        """Close all font file handles and clear cache."""
        for f in self._fonts:
            f.close()
        self._fonts = []
        self._cache.clear()
        self._cache_size = 0

    def __del__(self):
        """Ensure font files are closed on garbage collection."""
        try:
            self.close()
        except:
            pass

    def load_font(self, path: str):
        """
        Load a font as the primary (and only) font.

        Closes any previously loaded fonts and clears the glyph cache.

        Args:
            path: Path to .bf2 font file
        """
        for f in self._fonts:
            f.close()
        self._fonts = []
        self._cache.clear()
        self._cache_size = 0
        self.add_font(path)

    def add_font(self, path: str, optional: bool = False) -> bool:
        """
        Add a font to the font stack.

        Fonts are searched in the order they are added. The first font
        containing a requested glyph wins. This enables font subsetting:
        load a small base font for ASCII, then add optional extension
        fonts for icons, CJK characters, etc.

        Args:
            path: Path to .bf2 font file
            optional: If True, silently return False on load failure

        Returns:
            True if font was loaded successfully

        Raises:
            OSError: If font file not found and optional=False
        """
        try:
            f = BF2Font(path)
            self._fonts.append(f)
            if len(self._fonts) == 1:
                self._base_h = f.height
            return True
        except OSError:
            if optional:
                return False
            raise

    def preload_glyphs(self, chars: str):
        """
        Pre-load glyphs into cache to avoid read latency later.

        Useful for preloading commonly used characters at startup.

        Args:
            chars: String of characters to preload
        """
        for ch in chars:
            self._get_glyph(ord(ch))

    # =========================================================================
    # Measurement
    # =========================================================================

    def measure_width(self, text: str, scale: int = 1) -> int:
        """
        Measure the pixel width of a text string.

        Args:
            text: Text to measure
            scale: Scale factor

        Returns:
            Width in pixels
        """
        if not self._fonts or not text:
            return 0

        w = 0
        fallback_w = self._fonts[0].def_w
        for ch in text:
            g = self._get_glyph(ord(ch))
            w += (g[1] + 1) * scale if g else fallback_w * scale
        return w - scale  # Remove trailing spacing

    def measure_height(self, scale: int = 1) -> int:
        """
        Get line height for the primary font.

        Args:
            scale: Scale factor

        Returns:
            Height in pixels
        """
        if self._fonts:
            return self._fonts[0].height * scale
        return self._base_h * scale

    # =========================================================================
    # Drawing
    # =========================================================================

    def draw(self, text: str, x: int, y: int, color: int = 0,
             scale: int = 1, align: str = "left") -> int:
        """
        Draw text onto the buffer.

        Args:
            text: Text string to draw
            x: X position (affected by alignment)
            y: Y position (top of text)
            color: Pixel color (0=BLACK, 3=WHITE for 2-bit; 0/1 for 1-bit)
            scale: Integer scale factor (1=normal, 2=double, etc.)
            align: Text alignment - "left", "center", or "right"

        Returns:
            Total width of drawn text in pixels
        """
        if not self._fonts:
            return 0

        ctx = self._fb.get_blit_context(color)
        fallback_w = self._fonts[0].def_w

        # Single-pass: collect glyphs and measure width together
        glyphs = []
        total_width = 0
        for ch in text:
            g = self._get_glyph(ord(ch))
            if g:
                glyphs.append(g)
                total_width += (g[1] + 1) * scale
            else:
                glyphs.append(None)
                total_width += fallback_w * scale

        if glyphs:
            total_width -= scale  # Remove trailing space

        # Apply alignment offset
        if align == "center":
            x -= total_width // 2
        elif align == "right":
            x -= total_width

        # Render glyphs
        cx = x
        for g in glyphs:
            if g is None:
                cx += fallback_w * scale
            else:
                data, w, h, bpr = g
                self._render_fast(ctx, data, cx, y, w, h, bpr, scale)
                cx += (w + 1) * scale

        return total_width

    # =========================================================================
    # Internal: Glyph Cache
    # =========================================================================

    def _get_glyph(self, cp: int):
        """
        Retrieve glyph data with LRU caching.

        Returns:
            (bitmap_data, width, height, bytes_per_row) or None
        """
        if cp in self._cache:
            self._cache.move_to_end(cp)
            return self._cache[cp]

        for f in self._fonts:
            info = f.get(cp)
            if info:
                w, off = info
                data = f.read(off)
                res = (data, w if f.prop else f.max_w, f.height, f.bpr)

                # LRU eviction
                sz = len(data)
                while self._cache_size + sz > self._cache_max and self._cache:
                    _, v = self._cache.popitem(last=False)
                    self._cache_size -= len(v[0])

                self._cache[cp] = res
                self._cache_size += sz
                return res
        return None

    # =========================================================================
    # Internal: Glyph Rendering
    # =========================================================================

    def _render_fast(self, ctx, data, x, y, w, h, bpr, scale):
        """
        Render a single glyph bitmap with pre-clipping optimization.

        Pre-calculates visible row/column ranges based on the logical
        display bounds to avoid per-pixel bounds checking in the inner loop.

        Args:
            ctx: Blit context from DrawBuffer.get_blit_context()
            data: Glyph bitmap data
            x, y: Logical position
            w, h: Glyph dimensions
            bpr: Bytes per row in glyph data
            scale: Integer scale factor
        """
        buf, pw, ph, stride, (swap, xf, yf), col, _ = ctx

        # Get logical dimensions (after rotation)
        lw = ph if swap else pw
        lh = pw if swap else ph

        # Early rejection: glyph completely off-screen
        glyph_w = w * scale
        glyph_h = h * scale
        if x >= lw or y >= lh or x + glyph_w <= 0 or y + glyph_h <= 0:
            return

        # Calculate visible glyph row/column range (in glyph coordinates)
        # This avoids bounds checking in the inner loop
        col_start = (-x + scale - 1) // scale if x < 0 else 0
        col_end = (lw - x + scale - 1) // scale if x + glyph_w > lw else w
        row_start = (-y + scale - 1) // scale if y < 0 else 0
        row_end = (lh - y + scale - 1) // scale if y + glyph_h > lh else h

        # Nothing visible after clipping
        if col_start >= col_end or row_start >= row_end:
            return

        # Pre-calculate transform parameters
        if not swap:
            dx_s = pw - 1 - x if xf else x
            dx_d = -scale if xf else scale
            dy_s = ph - 1 - y if yf else y
            dy_d = -scale if yf else scale
        else:
            dx_s = pw - 1 - y if xf else y
            dx_d = -scale if xf else scale
            dy_s = ph - 1 - x if yf else x
            dy_d = -scale if yf else scale

        # Render only visible portion
        for row in range(row_start, row_end):
            row_off = row * bpr
            if not swap:
                py_anchor = dy_s + (row * dy_d)
            else:
                px_anchor = dx_s + (row * dx_d)

            for col_idx in range(col_start, col_end):
                # Check if pixel is set in glyph bitmap
                if not (data[row_off + (col_idx >> 3)] & (0x80 >> (col_idx & 7))):
                    continue

                if not swap:
                    px, py = dx_s + (col_idx * dx_d), py_anchor
                else:
                    px, py = px_anchor, dy_s + (col_idx * dy_d)

                # Scaling: draw scale×scale block per glyph pixel
                for sy in range(scale):
                    for sx in range(scale):
                        if not swap:
                            rpx = px + (sx if not xf else -sx)
                            rpy = py + (sy if not yf else -sy)
                        else:
                            rpx = px + (sy if not xf else -sy)
                            rpy = py + (sx if not yf else -sx)

                        # Bounds check needed for edge pixels when scale > 1
                        if 0 <= rpx < pw and 0 <= rpy < ph:
                            idx = rpy * stride + (rpx >> 3)
                            bit = 7 - (rpx & 7)
                            if col:
                                buf[idx] |= (1 << bit)
                            else:
                                buf[idx] &= ~(1 << bit)
