"""
FrameBuffer - Core Display Buffer with Depth Support
=====================================================
Manages a display buffer with configurable bit depth and rotation.

Supports:
- 1-bit (monochrome): BLACK/WHITE
- 2-bit (grayscale): BLACK/DARK_GRAY/LIGHT_GRAY/WHITE

Optimized with:
- Rotation Property Caching
- LUT-based buffer conversion
"""

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

# =============================================================================
# Color Constants
# =============================================================================

BLACK = 0
DARK_GRAY = 1
LIGHT_GRAY = 2
WHITE = 3

# =============================================================================
# Bit Manipulation Constants
# =============================================================================

_BITS_PER_BYTE = 8
_BYTE_MASK = 0xFF
_BYTE_ZERO = 0x00
_TWO_BIT_MASK = 0b11
_TWO_BIT_FILL = 0x55  # Pattern for 2-bit value repeated 4x per byte

# Byte literals for fast buffer slice filling
_FILL_WHITE = b'\xff'  # All bits set (white in 1-bit mode)
_FILL_BLACK = b'\x00'  # No bits set (black in 1-bit mode)

# Pixel thresholds for grayscale conversion
_MONO_THRESHOLD = 2  # Values >= 2 (LIGHT_GRAY, WHITE) map to white in mono

# Bit positions for 2-bit pixel packing (4 pixels per byte, MSB first)
_PIXELS_PER_BYTE_2BIT = 4
_TWO_BIT_SHIFT_BASE = 6  # Starting shift for first 2-bit pixel in byte

# =============================================================================
# Internal Lookup Tables
# =============================================================================

_BIT_MASKS = tuple(1 << (7 - i) for i in range(_BITS_PER_BYTE))
_INV_MASKS = tuple(~(1 << (7 - i)) & _BYTE_MASK for i in range(_BITS_PER_BYTE))

_ROTATION = {
    0: (False, False, False),
    90: (True, True, False),
    180: (False, True, True),
    270: (True, False, True),
}

# --- Lazy LUT for 2-bit to 1-bit conversion ---
# Saves ~768 bytes until 4-gray mode is first used.
# We process 1 byte (4 pixels) of 2-bit data and output 4 bits (nibble).

_LUT_MONO = None
_LUT_BLACK = None
_LUT_RED = None

def _init_luts():
    """Initialize LUTs on first use (lazy loading)."""
    global _LUT_MONO, _LUT_BLACK, _LUT_RED
    if _LUT_MONO is not None:
        return

    mono = bytearray(256)
    black = bytearray(256)
    red = bytearray(256)

    for i in range(256):
        m = b = r = 0
        for p in range(_PIXELS_PER_BYTE_2BIT):
            # Extract 2-bit pixel (MSB first)
            val = (i >> (_TWO_BIT_SHIFT_BASE - 2 * p)) & _TWO_BIT_MASK
            out_bit = 1 << ((_PIXELS_PER_BYTE_2BIT - 1) - p)

            if val >= _MONO_THRESHOLD: m |= out_bit  # Mono threshold
            if (val >> 1) & 1: b |= out_bit          # Black plane (high bit)
            if val & 1: r |= out_bit                 # Red plane (low bit)

        mono[i] = m
        black[i] = b
        red[i] = r

    _LUT_MONO = bytes(mono)
    _LUT_BLACK = bytes(black)
    _LUT_RED = bytes(red)


class FrameBuffer:
    """
    Display buffer with configurable depth and rotation.
    """

    def __init__(self, phys_width: int, phys_height: int,
                 depth: int = 1, rotation: int = 0):
        if depth not in (1, 2):
            raise ValueError("depth must be 1 or 2")

        self._phys_w = phys_width
        self._phys_h = phys_height
        self._depth = depth

        total_bits = phys_width * phys_height * depth
        self._buffer_size = (total_bits + 7) // 8
        self._buffer = bytearray(self._buffer_size)
        self._row_bytes = (phys_width * depth + 7) // 8

        self._inverted = False

        # Cache for rotation properties
        self._rot_props = (False, False, False)
        self._rotation = 0
        self.rotation = rotation

    def _update_dimensions(self):
        if self._rotation in (0, 180):
            self.width = self._phys_w
            self.height = self._phys_h
        else:
            self.width = self._phys_h
            self.height = self._phys_w

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def depth(self) -> int: return self._depth

    @property
    def rotation(self) -> int: return self._rotation

    @rotation.setter
    def rotation(self, value: int):
        self._rotation = value % 360
        self._rot_props = _ROTATION[self._rotation]
        self._update_dimensions()

    @property
    def buffer(self) -> bytearray: return self._buffer

    @property
    def is_inverted(self) -> bool: return self._inverted

    # =========================================================================
    # Coordinate Transformation & Pixel Ops
    # =========================================================================

    def _transform(self, x: int, y: int) -> tuple[int, int]:
        is_swapped, x_flip, y_flip = self._rot_props
        if is_swapped: x, y = y, x
        if x_flip: x = self._phys_w - 1 - x
        if y_flip: y = self._phys_h - 1 - y
        return x, y

    def transform_region(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        is_swapped, x_flip, y_flip = self._rot_props
        if is_swapped: x, y, w, h = y, x, h, w
        if x_flip: x = self._phys_w - x - w
        if y_flip: y = self._phys_h - y - h
        return x, y, w, h

    def _set_pixel_1bit(self, px: int, py: int, color: int) -> None:
        idx = py * self._row_bytes + (px >> 3)
        bit = px & 7
        if color: self._buffer[idx] |= _BIT_MASKS[bit]
        else: self._buffer[idx] &= _INV_MASKS[bit]

    def _get_pixel_1bit(self, px: int, py: int) -> int:
        idx = py * self._row_bytes + (px >> 3)
        return WHITE if (self._buffer[idx] & _BIT_MASKS[px & 7]) else BLACK

    def _set_pixel_2bit(self, px: int, py: int, color: int) -> None:
        bit_off = (py * self._phys_w + px) * 2
        byte_idx = bit_off >> 3
        bit_pos = _TWO_BIT_SHIFT_BASE - (bit_off & 7)
        mask = ~(_TWO_BIT_MASK << bit_pos) & _BYTE_MASK
        self._buffer[byte_idx] = (self._buffer[byte_idx] & mask) | ((color & _TWO_BIT_MASK) << bit_pos)

    def _get_pixel_2bit(self, px: int, py: int) -> int:
        bit_off = (py * self._phys_w + px) * 2
        return (self._buffer[bit_off >> 3] >> (_TWO_BIT_SHIFT_BASE - (bit_off & 7))) & _TWO_BIT_MASK

    # --- Physical pixel setters (for DrawBuffer's optimized loops) ---
    def _set_pixel_1bit_phys(self, px: int, py: int, color: int) -> None:
        """Set 1-bit pixel at physical coords (no transform, no bounds check)."""
        idx = py * self._row_bytes + (px >> 3)
        if color:
            self._buffer[idx] |= _BIT_MASKS[px & 7]
        else:
            self._buffer[idx] &= _INV_MASKS[px & 7]

    def _set_pixel_2bit_phys(self, px: int, py: int, color: int) -> None:
        """Set 2-bit pixel at physical coords (no transform, no bounds check)."""
        off = (py * self._phys_w + px) * 2
        idx = off >> 3
        shift = _TWO_BIT_SHIFT_BASE - (off & 7)
        self._buffer[idx] = (self._buffer[idx] & ~(_TWO_BIT_MASK << shift)) | ((color & _TWO_BIT_MASK) << shift)

    def pixel(self, x: int, y: int, color: int = BLACK) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height): return

        is_swapped, x_flip, y_flip = self._rot_props
        if is_swapped: x, y = y, x
        px = (self._phys_w - 1 - x) if x_flip else x
        py = (self._phys_h - 1 - y) if y_flip else y

        eff = self._effective_color(color)
        if self._depth == 1: self._set_pixel_1bit(px, py, eff)
        else: self._set_pixel_2bit(px, py, eff)

    def get_pixel(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height): return WHITE
        # Inline transform to avoid function call overhead
        is_swapped, x_flip, y_flip = self._rot_props
        if is_swapped: x, y = y, x
        px = (self._phys_w - 1 - x) if x_flip else x
        py = (self._phys_h - 1 - y) if y_flip else y
        if self._depth == 1: return self._get_pixel_1bit(px, py)
        else: return self._get_pixel_2bit(px, py)

    def pixel_fast(self, x: int, y: int, color: int = BLACK) -> None:
        """Set pixel without bounds checking (faster for known-safe coords)."""
        # Inline transform to avoid function call overhead in MicroPython
        is_swapped, x_flip, y_flip = self._rot_props
        if is_swapped: x, y = y, x
        px = (self._phys_w - 1 - x) if x_flip else x
        py = (self._phys_h - 1 - y) if y_flip else y
        eff = self._effective_color(color)
        if self._depth == 1: self._set_pixel_1bit(px, py, eff)
        else: self._set_pixel_2bit(px, py, eff)

    # =========================================================================
    # Buffer Ops
    # =========================================================================

    def clear(self, color: int = WHITE) -> None:
        """Clear the buffer to a color, respecting inversion."""
        # Calculate effective color first to handle inversion
        eff_color = self._effective_color(color)

        if self._depth == 1:
            fill = _BYTE_MASK if eff_color else _BYTE_ZERO
        else:
            # 2-bit packing: (color & 3) repeated 4 times
            fill = (eff_color & _TWO_BIT_MASK) * _TWO_BIT_FILL

        # Fast fill using slice assignment
        # Creating a small pattern and multiplying is faster than a loop
        self._buffer[:] = bytes((fill,)) * self._buffer_size

    def invert(self) -> None:
        """Software invert all buffer contents.

        This XORs every byte in the buffer, useful for 2-bit grayscale mode.
        For 1-bit mode with EPD displays, prefer using EPD.set_invert() or
        Canvas.invert_display() which uses hardware inversion - it's instant
        and doesn't require redrawing the buffer.

        Note: This is O(n) where n = buffer_size (4736 bytes for 296x128).
        """
        buf = self._buffer
        for i in range(self._buffer_size): buf[i] ^= _BYTE_MASK
        self._inverted = not self._inverted

    def _effective_color(self, color: int) -> int:
        """Apply inversion to color if buffer is in inverted state."""
        if not self._inverted: return color
        if self._depth == 1: return BLACK if color else WHITE
        else: return (~color) & _TWO_BIT_MASK

    def get_blit_context(self, color: int = BLACK) -> tuple:
        return (self._buffer, self._phys_w, self._phys_h, self._row_bytes,
                self._rot_props, self._effective_color(color), self._depth)

    # =========================================================================
    # Internal Line Primitives
    # =========================================================================

    def hline(self, x: int, y: int, length: int, color: int = BLACK) -> None:
        # (Standard implementation from previous optimized version)
        if length <= 0 or y < 0 or y >= self.height: return
        if x >= self.width or x + length <= 0: return
        if x < 0: length += x; x = 0
        if x + length > self.width: length = self.width - x
        if length <= 0: return

        effective = self._effective_color(color)
        is_swapped, x_flip, y_flip = self._rot_props

        if is_swapped:
            px = (self._phys_w - 1 - y) if x_flip else y
            py = (self._phys_h - x - length) if y_flip else x
            self._vline_phys(px, py, length, effective)
        else:
            px = (self._phys_w - x - length) if x_flip else x
            py = (self._phys_h - 1 - y) if y_flip else y
            self._hline_phys(px, py, length, effective)

    def vline(self, x: int, y: int, length: int, color: int = BLACK) -> None:
        if length <= 0 or x < 0 or x >= self.width: return
        if y < 0: length += y; y = 0
        if y + length > self.height: length = self.height - y
        if length <= 0: return

        effective = self._effective_color(color)
        is_swapped, x_flip, y_flip = self._rot_props

        if is_swapped:
            px = (self._phys_w - y - length) if x_flip else y
            py = (self._phys_h - 1 - x) if y_flip else x
            self._hline_phys(px, py, length, effective)
        else:
            px = (self._phys_w - 1 - x) if x_flip else x
            py = (self._phys_h - y - length) if y_flip else y
            self._vline_phys(px, py, length, effective)

    def _hline_phys(self, px: int, py: int, length: int, color: int) -> None:
        if self._depth == 2:
            for i in range(length): self._set_pixel_2bit(px + i, py, color)
            return

        # 1-bit optimization
        buf = self._buffer
        row = py * self._row_bytes
        end = px + length
        b0, bit0 = px >> 3, px & 7
        b1, bit1 = (end - 1) >> 3, (end - 1) & 7

        if b0 == b1:
            mask = ((_BYTE_MASK >> bit0) & (_BYTE_MASK << (7 - bit1))) & _BYTE_MASK
            if color: buf[row + b0] |= mask
            else: buf[row + b0] &= mask ^ _BYTE_MASK
        else:
            start_mask = _BYTE_MASK >> bit0
            if color: buf[row + b0] |= start_mask
            else: buf[row + b0] &= start_mask ^ _BYTE_MASK

            if b1 > b0 + 1:
                fill = _FILL_WHITE if color else _FILL_BLACK
                buf[row + b0 + 1:row + b1] = fill * (b1 - b0 - 1)

            end_mask = (_BYTE_MASK << (7 - bit1)) & _BYTE_MASK
            if color: buf[row + b1] |= end_mask
            else: buf[row + b1] &= end_mask ^ _BYTE_MASK

    def _vline_phys(self, px: int, py: int, length: int, color: int) -> None:
        if self._depth == 2:
            for i in range(length): self._set_pixel_2bit(px, py + i, color)
            return

        buf = self._buffer
        row_bytes = self._row_bytes
        byte_col = px >> 3
        mask = _BIT_MASKS[px & 7]
        inv = _INV_MASKS[px & 7]

        # Calculate starting index and stride to avoid multiplication in loop
        idx = py * row_bytes + byte_col
        if color:
            for _ in range(length):
                buf[idx] |= mask
                idx += row_bytes
        else:
            for _ in range(length):
                buf[idx] &= inv
                idx += row_bytes

    def get_region(self, x: int, y: int, w: int, h: int, physical: bool = False) -> bytearray:
        if not physical: x, y, w, h = self.transform_region(x, y, w, h)

        px, py, pw, ph = x, y, w, h
        if self._depth == 1:
            if px % _BITS_PER_BYTE != 0 or pw % _BITS_PER_BYTE != 0: raise ValueError("x/w must be multiple of 8")
            region = bytearray(pw * ph // _BITS_PER_BYTE)
            src_stride = self._row_bytes
            dst_stride = pw // _BITS_PER_BYTE
            px_byte = px // _BITS_PER_BYTE
            for row in range(ph):
                src = (py + row) * src_stride + px_byte
                dst = row * dst_stride
                region[dst:dst + dst_stride] = self._buffer[src:src + dst_stride]
            return region
        else:
            region = bytearray(pw * ph * 2 // _BITS_PER_BYTE)
            # 2-bit region extraction remains pixel-by-pixel for now
            for row in range(ph):
                for col in range(pw):
                    val = self._get_pixel_2bit(px + col, py + row)
                    bo = (row * pw + col) * 2
                    region[bo >> 3] |= (val << (_TWO_BIT_SHIFT_BASE - (bo & 7)))
            return region

    # =========================================================================
    # Format Conversion (LUT Optimized)
    # =========================================================================

    def to_mono(self) -> bytes:
        """Convert buffer to 1-bit packed bytes (Fast LUT)."""
        if self._depth == 1:
            return bytes(self._buffer)

        _init_luts()  # Lazy init
        buf = self._buffer
        mono = bytearray(self._buffer_size // 2)

        for i in range(0, self._buffer_size, 2):
            mono[i // 2] = (_LUT_MONO[buf[i]] << 4) | _LUT_MONO[buf[i + 1]]

        return bytes(mono)

    def to_planes(self) -> tuple[bytes, bytes]:
        """Convert 2-bit buffer to bit planes (Fast LUT)."""
        if self._depth != 2:
            raise ValueError("depth=2 required")

        _init_luts()  # Lazy init
        buf = self._buffer
        plane_size = self._buffer_size // 2
        black = bytearray(plane_size)
        red = bytearray(plane_size)

        for i in range(0, self._buffer_size, 2):
            black[i // 2] = (_LUT_BLACK[buf[i]] << 4) | _LUT_BLACK[buf[i + 1]]
            red[i // 2] = (_LUT_RED[buf[i]] << 4) | _LUT_RED[buf[i + 1]]

        return bytes(black), bytes(red)
