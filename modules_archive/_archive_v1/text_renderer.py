"""
TextRenderer V2 - Text Rendering for FrameBuffer with BF2 Font Support
=======================================================================
Handles font loading, text measurement, and rendering with alignment/wrapping.

Features:
- LRU glyph cache with configurable size limits
- Batch glyph loading for reduced I/O
- Variable-width (proportional) font support
- Unicode character support (BMP + extended planes with 32-bit mode)

Usage:
    from framebuffer import FrameBuffer
    from text_renderer import TextRenderer

    fb = FrameBuffer(128, 296, rotation=90)
    text = TextRenderer(fb)

    # Load BF2 font
    text.load_font("/fonts/ucs-5x8.bf2")
    text.draw("Hello World! ▲▼", 10, 10)

Dependencies:
    - framebuffer.FrameBuffer for pixel operations
    - shapes module for placeholder boxes (missing glyphs only)

BF2 Font Format:
    Header (12 bytes):
        magic: 2 bytes ("B2")
        version: 1 byte (1)
        flags: 1 byte
            bit 0: proportional (0=mono, 1=variable-width)
            bit 1: 32-bit codepoints (0=16-bit, 1=32-bit)
        max_width: 1 byte
        height: 1 byte
        glyph_count: 2 bytes (little-endian, up to 65535)
        bytes_per_row: 1 byte (ceil(max_width/8))
        default_width: 1 byte (for missing glyphs)
        reserved: 2 bytes

    Index table (sorted by codepoint):
        16-bit mode: glyph_count * 6 bytes
            codepoint: 2 bytes (little-endian)
            width: 1 byte
            offset: 3 bytes (little-endian)
        32-bit mode: glyph_count * 8 bytes
            codepoint: 4 bytes (little-endian)
            width: 1 byte
            offset: 3 bytes (little-endian)

    Glyph data:
        Each glyph: height * bytes_per_row bytes (row-major, MSB first)
"""

import struct
from collections import OrderedDict

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from framebuffer import FrameBuffer

# Default fallback font path
_DEFAULT_FONT_PATH = "/lib/fonts/cozette.bf2"

# BF2 format constants
_BF2_MAGIC = b"B2"
_BF2_HEADER_SIZE = 12
_BF2_INDEX_ENTRY_SIZE = 6

# Flag bits
_FLAG_PROPORTIONAL = 0x01
_FLAG_32BIT_CODEPOINTS = 0x02


class LRUCache:
    """LRU cache with size limit for glyph data.

    Uses OrderedDict for O(1) access, insertion, and eviction.
    Size is tracked in bytes for memory budgeting.
    """

    def __init__(self, max_bytes: int = 4096):
        """Initialize cache with maximum size in bytes."""
        self._max_bytes: int = max_bytes
        self._current_bytes: int = 0
        self._cache: OrderedDict[int, tuple[bytes, int]] = OrderedDict()

    def get(self, key: int) -> tuple[bytes, int] | None:
        """Get item from cache, updating access order. Returns None if not found."""
        if key in self._cache:
            self._cache.move_to_end(key)  # O(1) move to most recently used
            return self._cache[key]
        return None

    def put(self, key: int, data: bytes, width: int) -> None:
        """Add item to cache, evicting LRU items if needed."""
        size_bytes = len(data)
        # If already in cache, remove old entry first
        if key in self._cache:
            old_data, _ = self._cache.pop(key)
            self._current_bytes -= len(old_data)

        # Evict LRU items (front of OrderedDict) until we have space
        while self._current_bytes + size_bytes > self._max_bytes and self._cache:
            _, (lru_data, _) = self._cache.popitem(last=False)  # O(1) pop oldest
            self._current_bytes -= len(lru_data)

        # Add new item at end (most recently used)
        self._cache[key] = (data, width)
        self._current_bytes += size_bytes

    def clear(self) -> None:
        """Clear all cached items."""
        self._cache.clear()
        self._current_bytes = 0

    def __contains__(self, key: int) -> bool:
        return key in self._cache

    @property
    def size(self):
        """Current cache size in bytes."""
        return self._current_bytes

    @property
    def count(self):
        """Number of cached glyphs."""
        return len(self._cache)


class TextRenderer:
    """Text rendering with LRU cache, batch loading, and Unicode support."""

    def __init__(self, framebuffer: "FrameBuffer", default_font_path: str | None = None, cache_size: int = 4096):
        """
        Initialize with a FrameBuffer.

        Args:
            framebuffer: FrameBuffer instance to draw on
            default_font_path: Path to default font file
            cache_size: Maximum glyph cache size in bytes (default 4KB)
        """
        self._fb = framebuffer
        self._default_font_path: str = default_font_path or _DEFAULT_FONT_PATH

        # Font state
        self._font_file = None
        self._font_path = None
        self._is_32bit = False    # 32-bit codepoints mode
        self._index_entry_size = 6  # 6 for 16-bit, 8 for 32-bit
        self._font_width = 5      # Max/fixed width
        self._font_height = 8
        self._proportional = False
        self._default_glyph_width = 5
        self._bytes_per_row = 1
        self._glyph_count = 0

        # BF2 index cache (codepoint -> (width, offset))
        self._bf2_index = {}

        # LRU glyph cache
        self._glyph_cache = LRUCache(max_bytes=cache_size)

        # Named font registry
        self._font_registry = {}

    @property
    def font_height(self):
        """Current font height in pixels."""
        return self._font_height

    @property
    def font_width(self):
        """Current font max/default width in pixels."""
        return self._font_width

    @property
    def has_font(self):
        """True if a font is loaded."""
        return self._font_file is not None

    @property
    def is_proportional(self):
        """True if current font is proportional (variable-width)."""
        return self._proportional

    @property
    def cache_stats(self):
        """Return cache statistics (size_bytes, glyph_count)."""
        return (self._glyph_cache.size, self._glyph_cache.count)

    # =========================================================================
    # Font management
    # =========================================================================

    def _ensure_font(self) -> None:
        """Load default font if none loaded."""
        if self._font_file is None:
            try:
                self.load_font(self._default_font_path)
            except Exception:
                pass

    def load_font(self, font_path: str, name: str | None = None) -> None:
        """
        Load a BF2 font file.

        Args:
            font_path: Path to .bf2 font file
            name: Optional name to register font for quick switching
        """
        # Close any existing font
        self._close_font()

        try:
            self._font_file = open(font_path, "rb")
            self._font_path = font_path

            # Read and verify magic
            magic = self._font_file.read(2)
            if magic != _BF2_MAGIC:
                self._font_file.close()
                self._font_file = None
                raise ValueError(f"Invalid BF2 font: {font_path}")

            self._load_bf2_header()

            # Clear glyph cache when font changes
            self._glyph_cache.clear()

            # Register font if name provided
            if name:
                self._font_registry[name] = {
                    'path': font_path,
                    'width': self._font_width,
                    'height': self._font_height,
                    'proportional': self._proportional
                }

        except OSError as e:
            raise OSError(f"Could not load font: {font_path}") from e

    def _load_bf2_header(self) -> None:
        """Load BF2 format header and index table."""
        # Read rest of header (already read 2-byte magic)
        header = self._font_file.read(_BF2_HEADER_SIZE - 2)
        (version, flags, max_width, height, glyph_count,
         bytes_per_row, default_width, _reserved) = struct.unpack("<BBBBHBBH", header)

        self._font_width = max_width
        self._font_height = height
        self._proportional = bool(flags & _FLAG_PROPORTIONAL)
        self._is_32bit = bool(flags & _FLAG_32BIT_CODEPOINTS)
        self._index_entry_size = 8 if self._is_32bit else 6
        self._default_glyph_width = default_width
        self._bytes_per_row = bytes_per_row
        self._glyph_count = glyph_count

        # Load index table into memory for fast lookup
        self._bf2_index.clear()
        index_data = self._font_file.read(glyph_count * self._index_entry_size)

        for i in range(glyph_count):
            offset = i * self._index_entry_size
            if self._is_32bit:
                # 32-bit: codepoint(4) + width(1) + offset(3) = 8 bytes
                codepoint, width, off_low, off_mid, off_high = struct.unpack(
                    "<IBBBB", index_data[offset:offset + 8]
                )
            else:
                # 16-bit: codepoint(2) + width(1) + offset(3) = 6 bytes
                codepoint, width, off_low, off_mid, off_high = struct.unpack(
                    "<HBBBB", index_data[offset:offset + 6]
                )
            glyph_offset = off_low | (off_mid << 8) | (off_high << 16)
            self._bf2_index[codepoint] = (width, glyph_offset)

    def _close_font(self) -> None:
        """Close current font file."""
        if self._font_file is not None:
            self._font_file.close()
            self._font_file = None
            self._font_path = None
            self._is_32bit = False
            self._index_entry_size = 6
            self._bf2_index.clear()

    def set_font(self, name: str) -> bool:
        """Switch to a registered font by name. Returns True if found."""
        if name in self._font_registry:
            info = self._font_registry[name]
            self.load_font(info['path'])
            return True
        return False

    def unload_font(self, name: str | None = None) -> None:
        """Unload a font (by name from registry) or the current font."""
        if name:
            self._font_registry.pop(name, None)
        else:
            self._close_font()
            self._font_width = 5
            self._font_height = 8
            self._proportional = False
            self._glyph_cache.clear()

    def reset_font(self) -> None:
        """Reset to the default font."""
        self.load_font(self._default_font_path)

    def set_cache_size(self, max_bytes: int) -> None:
        """Change the maximum cache size. Clears existing cache."""
        self._glyph_cache = LRUCache(max_bytes=max_bytes)

    # =========================================================================
    # Glyph loading with caching and batching
    # =========================================================================

    def _get_glyph(self, codepoint: int) -> tuple[bytes | None, int]:
        """
        Get glyph data for a codepoint, using cache.

        Returns: (glyph_data, width) or (None, default_width) if not found
        """
        # Check cache first
        cached = self._glyph_cache.get(codepoint)
        if cached is not None:
            return (cached[0], cached[1])

        # Load from font file
        return self._load_glyph(codepoint)

    def _load_glyph(self, codepoint: int) -> tuple[bytes | None, int]:
        """Load a glyph from BF2 format."""
        if codepoint not in self._bf2_index:
            return (None, self._default_glyph_width)

        width, offset = self._bf2_index[codepoint]
        glyph_size = self._font_height * self._bytes_per_row

        # Seek to glyph data (after header + index table)
        data_start = _BF2_HEADER_SIZE + self._glyph_count * self._index_entry_size
        self._font_file.seek(data_start + offset)

        try:
            data = self._font_file.read(glyph_size)
            if len(data) == glyph_size:
                actual_width = width if self._proportional else self._font_width
                self._glyph_cache.put(codepoint, data, actual_width)
                return (data, actual_width)
        except RuntimeError:
            pass
        return (None, self._default_glyph_width)

    def _batch_load_glyphs(self, codepoints: set[int]) -> None:
        """
        Pre-load multiple glyphs into cache.

        Args:
            codepoints: Iterable of codepoint integers
        """
        # Filter to only uncached codepoints
        to_load = [cp for cp in codepoints if cp not in self._glyph_cache]

        if not to_load:
            return

        self._batch_load(to_load)

    def _batch_load(self, codepoints: list[int]) -> None:
        """Batch load glyphs from BF2 format."""
        glyph_size = self._font_height * self._bytes_per_row
        data_start = _BF2_HEADER_SIZE + self._glyph_count * self._index_entry_size

        # Sort by file offset for sequential reads
        to_load = []
        for cp in codepoints:
            if cp in self._bf2_index:
                width, offset = self._bf2_index[cp]
                to_load.append((offset, cp, width))

        to_load.sort()  # Sort by offset

        for offset, cp, width in to_load:
            self._font_file.seek(data_start + offset)
            try:
                data = self._font_file.read(glyph_size)
                if len(data) == glyph_size:
                    actual_width = width if self._proportional else self._font_width
                    self._glyph_cache.put(cp, data, actual_width)
            except RuntimeError:
                pass

    # =========================================================================
    # Text measurement
    # =========================================================================

    def measure_width(self, string: str, scale: int = 1) -> int:
        """Calculate text width without drawing."""
        self._ensure_font()

        if not self._proportional:
            # Fixed-width: simple calculation
            return len(string) * (self._font_width + 1) * scale

        # Variable-width: measure each character
        total = 0
        for char in string:
            cp = ord(char)
            if cp in self._bf2_index:
                width, _ = self._bf2_index[cp]
                total += (width + 1) * scale
            else:
                total += (self._default_glyph_width + 1) * scale
        return total

    def measure_height(self, scale: int = 1) -> int:
        """Get current font line height."""
        return self._font_height * scale

    def get_glyph_width(self, char: str | int) -> int:
        """Get width of a single character."""
        cp = ord(char) if isinstance(char, str) else char

        if not self._proportional:
            return self._font_width

        if cp in self._bf2_index:
            return self._bf2_index[cp][0]

        return self._default_glyph_width

    # =========================================================================
    # Text rendering
    # =========================================================================

    def draw(self, string: str, x: int, y: int, black: bool = True, scale: int = 1,
             align: str = "left", max_width: int | None = None,
             line_spacing: int = 2) -> tuple[int, int]:
        """
        Draw text with optional alignment and word wrapping.

        Args:
            string: Text to draw
            x: X position
            y: Y position
            black: True for black text, False for white
            scale: Text scale factor
            align: "left", "center", or "right"
            max_width: If set, wrap text to this width
            line_spacing: Pixels between wrapped lines

        Returns:
            (width, height) of rendered text
        """
        self._ensure_font()

        # Handle wrapping
        if max_width is not None:
            return self._draw_wrapped(string, x, y, max_width, black, scale,
                                      line_spacing, align)

        # Calculate x position based on alignment
        text_w = self.measure_width(string, scale)
        if align == "center":
            x = x - text_w // 2
        elif align == "right":
            x = x - text_w

        # Pre-load all glyphs for this string (batch I/O)
        unique_codepoints = set(ord(c) for c in string)
        self._batch_load_glyphs(unique_codepoints)

        # Render text
        if self._font_file is not None:
            return self._draw_glyphs(string, x, y, black, scale)
        else:
            return self._draw_placeholder(string, x, y, black, scale)

    def draw_box(self, string: str, x: int, y: int, w: int, h: int,
                 align: str = "left", valign: str = "top",
                 black: bool = True, scale: int = 1,
                 wrap: bool = False, line_spacing: int = 2) -> int:
        """
        Draw text in a bounding box with alignment.

        Args:
            string: Text to draw
            x, y: Box top-left position
            w, h: Box dimensions
            align: "left", "center", "right"
            valign: "top", "middle", "bottom"
            black: True for black text
            scale: Text scale factor
            wrap: Enable word wrapping
            line_spacing: Pixels between lines

        Returns:
            Height of rendered text
        """
        if wrap:
            lines = self._wrap_lines(string, w, scale)
            line_height = self.measure_height(scale) + line_spacing
            total_height = len(lines) * line_height - line_spacing if lines else 0

            if valign == "middle":
                ty = y + (h - total_height) // 2
            elif valign == "bottom":
                ty = y + h - total_height
            else:
                ty = y

            self.draw(string, x, ty, black, scale, align, max_width=w,
                      line_spacing=line_spacing)
            return total_height
        else:
            text_h = self.measure_height(scale)

            if align == "center":
                tx = x + w // 2
            elif align == "right":
                tx = x + w
            else:
                tx = x

            if valign == "middle":
                ty = y + (h - text_h) // 2
            elif valign == "bottom":
                ty = y + h - text_h
            else:
                ty = y

            self.draw(string, tx, ty, black, scale, align=align)
            return text_h

    # =========================================================================
    # Internal rendering methods
    # =========================================================================

    def _draw_glyphs(self, string: str, x: int, y: int, black: bool, scale: int) -> tuple[int, int]:
        """Render glyphs from BF2 format.

        Args:
            string: Text to render
            x, y: Position
            black: Color
            scale: Scale factor

        Returns:
            (width, height) of rendered text
        """
        font_h = self._font_height
        fb = self._fb
        fb_width, fb_height = fb.width, fb.height
        bytes_per_row = self._bytes_per_row

        cursor = x

        for char in string:
            glyph_data, glyph_width = self._get_glyph(ord(char))
            char_spacing = (glyph_width + 1) * scale

            # Handle missing glyph - draw placeholder box (inlined rect)
            if glyph_data is None:
                box_w = glyph_width * scale
                box_h = font_h * scale
                fb.hline(cursor, y, box_w, black)
                fb.hline(cursor, y + box_h - 1, box_w, black)
                fb.vline(cursor, y, box_h, black)
                fb.vline(cursor + box_w - 1, y, box_h, black)
                cursor += char_spacing
                continue

            # Bounds check - skip if completely off-screen
            if cursor + glyph_width * scale <= 0 or cursor >= fb_width:
                cursor += char_spacing
                continue
            if y + font_h * scale <= 0 or y >= fb_height:
                cursor += char_spacing
                continue

            # Render glyph pixels
            self._render_glyph(glyph_data, cursor, y, glyph_width,
                               font_h, bytes_per_row, scale, black)

            cursor += char_spacing

        return (cursor - x, font_h * scale)

    def _render_glyph(self, glyph_data: bytes, x: int, y: int, glyph_width: int,
                      font_h: int, bytes_per_row: int, scale: int, black: bool) -> None:
        """Render BF2 format glyph (row-major, MSB first).

        Scaled rendering is inlined here to avoid shapes module dependency
        in the hot path. Uses hline for horizontal runs which is faster
        than individual pixels.
        """
        fb = self._fb
        if scale > 1:
            # Scaled rendering - inline fill_rect logic (hline per row)
            # This removes shapes dependency from the text rendering hot path
            for row in range(font_h):
                row_start = row * bytes_per_row
                py = y + row * scale
                for col in range(glyph_width):
                    byte_idx = col >> 3
                    bit_idx = 7 - (col & 7)
                    if (glyph_data[row_start + byte_idx] >> bit_idx) & 1:
                        px = x + col * scale
                        # Inline fill_rect: draw 'scale' horizontal lines
                        for sy in range(scale):
                            fb.hline(px, py + sy, scale, black)
        else:
            # Unscaled - use pixel directly
            for row in range(font_h):
                row_start = row * bytes_per_row
                for col in range(glyph_width):
                    byte_idx = col >> 3
                    bit_idx = 7 - (col & 7)
                    if (glyph_data[row_start + byte_idx] >> bit_idx) & 1:
                        fb.pixel(x + col, y + row, black)

    def _draw_placeholder(self, string: str, x: int, y: int, black: bool, scale: int) -> tuple[int, int]:
        """Draw placeholder boxes when no font is loaded."""
        w, h, spacing = 5 * scale, 7 * scale, scale
        cursor = x
        for _ in string:
            shapes.rect(self._fb, cursor, y, w, h, black)
            cursor += w + spacing
        return (cursor - x, h)

    def _draw_wrapped(self, string: str, x: int, y: int, max_width: int, black: bool,
                      scale: int, line_spacing: int, align: str) -> tuple[int, int]:
        """Draw text with automatic word wrapping."""
        lines = self._wrap_lines(string, max_width, scale)
        if not lines or lines == ['']:
            return (0, 0)

        line_height = self.measure_height(scale) + line_spacing

        if align == "center":
            lx = x + max_width // 2
        elif align == "right":
            lx = x + max_width
        else:
            lx = x

        cursor_y = y
        max_line_width = 0
        for line_text in lines:
            max_line_width = max(max_line_width, self.measure_width(line_text, scale))
            self.draw(line_text, lx, cursor_y, black, scale, align=align)
            cursor_y += line_height

        return (max_line_width, cursor_y - y)

    def _wrap_lines(self, string: str, max_width: int, scale: int) -> list[str]:
        """Split text into lines that fit within max_width."""
        if not string:
            return ['']

        words = string.split(' ')
        if not words:
            return ['']

        space_w = self.measure_width(' ', scale)
        measure = self.measure_width

        lines = []
        line_words = []
        line_width = 0

        for word in words:
            word_w = measure(word, scale)
            add_width = (space_w if line_words else 0) + word_w

            if line_width + add_width <= max_width:
                line_words.append(word)
                line_width += add_width
            else:
                if line_words:
                    lines.append(' '.join(line_words))
                line_words = [word]
                line_width = word_w

        if line_words:
            lines.append(' '.join(line_words))

        return lines if lines else ['']
