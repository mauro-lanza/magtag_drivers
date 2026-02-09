"""
TextRenderer - Font Subsetting & Patching
=========================================


fb = DrawBuffer(128, 296, rotation=90)
text = TextRenderer(fb)

# 1. Load the lightweight base (Fast startup)
text.load_font("fonts/basic.bf2")

# 2. Try to patch in extensions (Graceful)
text.add_font("fonts/extended.bf2", optional=True)
text.add_font("fonts/icons.bf2", optional=True)

# 3. Draw
# "A" comes from basic.bf2
# "€" comes from extended.bf2 (if found)
text.draw("Price: 50€", 10, 10)

"""
import struct
from collections import OrderedDict

_BF2_MAGIC = b"B2"
_BF2_HEADER = 12

class BF2Font:
    def __init__(self, path: str):
        self.file = open(path, "rb")
        if self.file.read(2) != _BF2_MAGIC:
            self.file.close()
            raise ValueError("Invalid BF2")

        hdr = self.file.read(10) # 12 total - 2 magic
        (_, flags, self.max_w, self.height, self.count,
         self.bpr, self.def_w, _) = struct.unpack("<BBBBHBBH", hdr)

        self.prop = bool(flags & 1)
        self.entry_size = 8 if (flags & 2) else 6
        self.data_start = _BF2_HEADER + self.count * self.entry_size

        # Load Index
        self.index = {}
        idx_data = self.file.read(self.count * self.entry_size)

        for i in range(self.count):
            off = i * self.entry_size
            if self.entry_size == 8:
                cp, w, o0, o1, o2 = struct.unpack("<IBBBB", idx_data[off:off+8])
            else:
                cp, w, o0, o1, o2 = struct.unpack("<HBBBB", idx_data[off:off+6])
            self.index[cp] = (w, o0 | (o1 << 8) | (o2 << 16))

    def get(self, cp: int): return self.index.get(cp)

    def read(self, offset):
        self.file.seek(self.data_start + offset)
        return self.file.read(self.height * self.bpr)

    def close(self): self.file.close()

class TextRenderer:
    def __init__(self, fb, cache_size=4096):
        self._fb = fb
        self._cache = OrderedDict()
        self._cache_max = cache_size
        self._cache_size = 0
        self._fonts = []
        self._base_h = 8

    def close(self):
        """Close all font file handles."""
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
            pass  # Ignore errors during GC

    def load_font(self, path):
        for f in self._fonts: f.close()
        self._fonts = []
        self._cache.clear()
        self._cache_size = 0
        self.add_font(path)

    def add_font(self, path, optional=False):
        try:
            f = BF2Font(path)
            self._fonts.append(f)
            if len(self._fonts) == 1: self._base_h = f.height
            return True
        except OSError:
            if optional: return False
            raise

    def preload_glyphs(self, chars: str):
        """Pre-load glyphs into cache to avoid lag later."""
        for ch in chars: self._get_glyph(ord(ch))

    def _get_glyph(self, cp):
        if cp in self._cache:
            self._cache.move_to_end(cp)
            return self._cache[cp]

        for f in self._fonts:
            info = f.get(cp)
            if info:
                w, off = info
                data = f.read(off)
                res = (data, w if f.prop else f.max_w, f.height, f.bpr)

                # Cache LRU
                sz = len(data)
                while self._cache_size + sz > self._cache_max and self._cache:
                    _, v = self._cache.popitem(last=False)
                    self._cache_size -= len(v[0])

                self._cache[cp] = res
                self._cache_size += sz
                return res
        return None

    def draw(self, text, x, y, color=0, scale=1, align="left"):
        if not self._fonts: return 0

        ctx = self._fb.get_blit_context(color)
        fallback_w = self._fonts[0].def_w if self._fonts else 6

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
        for i, g in enumerate(glyphs):
            if g is None:
                cx += fallback_w * scale
            else:
                data, w, h, bpr = g
                self._render_fast(ctx, data, cx, y, w, h, bpr, scale)
                cx += (w + 1) * scale

        return total_width

    def measure_width(self, text, scale=1):
        w = 0
        fallback_w = self._fonts[0].def_w if self._fonts else 6
        for ch in text:
            g = self._get_glyph(ord(ch))
            w += (g[1] + 1) * scale if g else fallback_w * scale
        return w - scale

    def measure_height(self, scale=1):
        # Use primary font's height if available, fallback to _base_h
        if self._fonts:
            return self._fonts[0].height * scale
        return self._base_h * scale

    def _render_fast(self, ctx, data, x, y, w, h, bpr, scale):
        """Render glyph with pre-clipping optimization.

        Pre-calculates visible row/column ranges to avoid per-pixel bounds checks.
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
        if x < 0:
            col_start = (-x + scale - 1) // scale  # First visible column
        else:
            col_start = 0

        if x + glyph_w > lw:
            col_end = (lw - x + scale - 1) // scale  # Last visible column + 1
        else:
            col_end = w

        if y < 0:
            row_start = (-y + scale - 1) // scale  # First visible row
        else:
            row_start = 0

        if y + glyph_h > lh:
            row_end = (lh - y + scale - 1) // scale  # Last visible row + 1
        else:
            row_end = h

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

                # Scaling - inner pixels are guaranteed visible due to pre-clipping
                for sy in range(scale):
                    for sx in range(scale):
                        if not swap:
                            rpx = px + (sx if not xf else -sx)
                            rpy = py + (sy if not yf else -sy)
                        else:
                            rpx = px + (sy if not xf else -sy)
                            rpy = py + (sx if not yf else -sx)

                        # Bounds check still needed for edge pixels when scale > 1
                        # but this is much rarer than before
                        if 0 <= rpx < pw and 0 <= rpy < ph:
                            idx = rpy * stride + (rpx >> 3)
                            bit = 7 - (rpx & 7)
                            if col:
                                buf[idx] |= (1 << bit)
                            else:
                                buf[idx] &= ~(1 << bit)
