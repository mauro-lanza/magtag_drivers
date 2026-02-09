"""
FrameBuffer - Display Buffer with Basic Drawing Operations
==========================================================
Manages a 1-bit display buffer with rotation support and basic pixel operations.

For shape primitives (line, rect, circle, triangle, etc.), see the shapes module.

GxEPD2 Compatible:
    Rotation transforms match GxEPD2 library for easy C++ porting:
    - Rotation 0: No change
    - Rotation 90: swap(x,y); x = WIDTH - x - 1
    - Rotation 180: x = WIDTH - x - 1; y = HEIGHT - y - 1
    - Rotation 270: swap(x,y); y = HEIGHT - y - 1

Usage:
    from framebuffer import FrameBuffer
    from shapes import line, rect, fill_rect, circle, triangle

    # Create buffer for 128x296 display, landscape mode
    fb = FrameBuffer(128, 296, rotation=90)
    fb.clear()

    # Basic drawing (built-in)
    fb.pixel(10, 10)
    fb.hline(0, 50, 100)
    fb.vline(50, 0, 100)

    # Shape primitives (from shapes module)
    line(fb, 0, 0, 100, 50)
    rect(fb, 20, 20, 60, 40)
    fill_rect(fb, 100, 10, 30, 30)
    circle(fb, 150, 64, 30)
    triangle(fb, 10, 10, 50, 80, 90, 30)

    # Toggle dark mode (inverts buffer in-place)
    fb.invert()

    # Get raw buffer for display
    data = fb.buffer

Rotation:
    0   = Portrait (width x height as given)
    90  = Landscape (height x width), rotated 90° CW
    180 = Portrait inverted
    270 = Landscape inverted
"""

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

# Color constants for clarity
BLACK = True
WHITE = False

# Pre-computed bit masks for faster pixel operations
_BIT_MASKS = tuple(1 << (7 - i) for i in range(8))
_INV_BIT_MASKS = tuple(~(1 << (7 - i)) & 0xFF for i in range(8))


# Rotation transform constants for lookup-based dispatch
# Each rotation maps: (is_swapped, x_flip, y_flip)
# is_swapped: True if x,y are swapped in physical coords
# x_flip/y_flip: True if that axis is inverted
_ROTATION_INFO = {
    0: (False, False, False),
    90: (True, True, False),
    180: (False, True, True),
    270: (True, False, True),
}


class FrameBuffer:
    """
    1-bit framebuffer with rotation and drawing primitives.

    The buffer is always stored in physical orientation (WIDTH x HEIGHT).
    Rotation transforms logical coordinates to physical coordinates.

    Optimized for CircuitPython with:
    - Pre-computed bit masks
    - Byte-aligned operations where possible
    - Scanline algorithms for filled shapes
    """

    def __init__(self, phys_width: int, phys_height: int, rotation: int = 0):
        """
        Initialize the framebuffer.

        Args:
            phys_width: Physical display width in pixels
            phys_height: Physical display height in pixels
            rotation: Display rotation (0, 90, 180, 270)
        """
        self._phys_width = phys_width
        self._phys_height = phys_height
        self._phys_width_bytes = phys_width // 8
        self._rotation = rotation % 360
        self._buffer_size = phys_width * phys_height // 8
        self._buffer: bytearray = bytearray(self._buffer_size)
        self._inverted = False  # Invert output when reading buffer

        # Calculate logical dimensions based on rotation
        self._update_dimensions()
        self.clear()

    def _update_dimensions(self):
        """Update logical width/height based on rotation."""
        if self._rotation in (0, 180):
            self.width = self._phys_width
            self.height = self._phys_height
        else:
            self.width = self._phys_height
            self.height = self._phys_width

    @property
    def rotation(self) -> int:
        """Get current rotation."""
        return self._rotation

    @rotation.setter
    def rotation(self, value: int):
        """Set rotation and recalculate dimensions."""
        self._rotation = value % 360
        self._update_dimensions()

    @property
    def buffer(self) -> bytearray:
        """Get the raw buffer for display output."""
        return self._buffer

    @property
    def buffer_size(self) -> int:
        """Get buffer size in bytes."""
        return self._buffer_size

    @property
    def is_inverted(self) -> bool:
        """Check if buffer is currently inverted (dark mode)."""
        return self._inverted

    def invert(self) -> None:
        """Toggle buffer inversion in-place (dark mode).

        XORs all bytes in the buffer. Call again to restore original.
        When inverted, clear() and drawing operations automatically flip colors.
        """
        buf = self._buffer
        for i in range(self._buffer_size):
            buf[i] ^= 0xFF
        self._inverted = not self._inverted

    def _effective_black(self, black: bool) -> bool:
        """Get effective color considering inverted state."""
        return not black if self._inverted else black

    def get_blit_context(self, black: bool = True) -> tuple:
        """Get internal state needed for optimized bitmap blitting.

        Returns a tuple of cached values to avoid repeated attribute lookups
        in tight loops. Used by shapes.blit() for maximum performance.

        Args:
            black: The color to use for set bits

        Returns:
            (buffer, phys_width, phys_height, phys_width_bytes, rotation_info, effective_black)
            where rotation_info is (is_swapped, x_flip, y_flip)
        """
        return (
            self._buffer,
            self._phys_width,
            self._phys_height,
            self._phys_width_bytes,
            _ROTATION_INFO[self._rotation],
            self._effective_black(black),
        )

    # =========================================================================
    # Coordinate transformation
    # =========================================================================

    def _transform(self, x: int, y: int) -> tuple[int, int]:
        """Transform logical (x,y) to physical buffer coordinates.

        Matches GxEPD2's rotation logic for easy porting.
        Uses lookup table for consistent rotation handling.
        """
        is_swapped, x_flip, y_flip = _ROTATION_INFO[self._rotation]
        if is_swapped:
            x, y = y, x
        if x_flip:
            x = self._phys_width - 1 - x
        if y_flip:
            y = self._phys_height - 1 - y
        return x, y

    def transform_region(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        """Transform logical region to physical coordinates.

        Args:
            x, y: Logical top-left corner
            w, h: Logical width and height

        Returns:
            (px, py, pw, ph): Physical coordinates and dimensions
        """
        is_swapped, x_flip, y_flip = _ROTATION_INFO[self._rotation]
        if is_swapped:
            x, y, w, h = y, x, h, w
        if x_flip:
            x = self._phys_width - x - w
        if y_flip:
            y = self._phys_height - y - h
        return x, y, w, h

    def _set_pixel_physical(self, px: int, py: int, black: bool = True) -> None:
        """Set a pixel using physical coordinates (no bounds check)."""
        byte_idx = py * self._phys_width_bytes + (px >> 3)
        bit_idx = px & 7
        if black:
            self._buffer[byte_idx] &= _INV_BIT_MASKS[bit_idx]
        else:
            self._buffer[byte_idx] |= _BIT_MASKS[bit_idx]

    def _get_pixel_physical(self, px: int, py: int) -> bool:
        """Get a pixel value using physical coordinates (no bounds check)."""
        byte_idx = py * self._phys_width_bytes + (px >> 3)
        bit_idx = px & 7
        return not (self._buffer[byte_idx] & _BIT_MASKS[bit_idx])

    # =========================================================================
    # Region extraction for partial updates
    # =========================================================================

    def get_region(self, x: int, y: int, w: int, h: int) -> bytearray:
        """
        Extract a rectangular region as bytes for partial display updates.

        The region is extracted in physical buffer format, suitable for
        epd_driver.display_partial_region().

        Args:
            x: Logical X start (must be multiple of 8)
            y: Logical Y start
            w: Width in pixels (must be multiple of 8)
            h: Height in pixels

        Returns:
            bytearray of region data (w * h // 8 bytes)

        Raises:
            ValueError: If x or w not aligned to 8 pixels
        """
        if x % 8 != 0 or w % 8 != 0:
            raise ValueError("x and w must be multiples of 8")

        # Clip to bounds
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError("Region out of bounds")

        region_bytes = w * h // 8
        region = bytearray(region_bytes)
        r = self._rotation

        if r == 0:
            # Direct copy - region maps directly to physical buffer (fastest path)
            src_row_bytes = self._phys_width_bytes
            dst_row_bytes = w // 8
            px_start = x // 8

            for row in range(h):
                src_offset = (y + row) * src_row_bytes + px_start
                dst_offset = row * dst_row_bytes
                region[dst_offset:dst_offset + dst_row_bytes] = \
                    self._buffer[src_offset:src_offset + dst_row_bytes]
        else:
            # Generic rotation path - handles 90, 180, 270
            dst_row_bytes = w // 8
            buf = self._buffer
            phys_w_bytes = self._phys_width_bytes
            transform = self._transform

            for ly in range(h):
                for lx in range(w):
                    px, py = transform(x + lx, y + ly)
                    byte_idx = py * phys_w_bytes + (px >> 3)
                    bit_idx = px & 7
                    pixel_black = not (buf[byte_idx] & _BIT_MASKS[bit_idx])
                    dst_byte = ly * dst_row_bytes + (lx >> 3)
                    dst_bit = lx & 7
                    if pixel_black:
                        region[dst_byte] &= _INV_BIT_MASKS[dst_bit]
                    else:
                        region[dst_byte] |= _BIT_MASKS[dst_bit]

        return region

    def get_physical_region(self, px: int, py: int, pw: int, ph: int) -> bytearray:
        """
        Extract a region using physical coordinates (no rotation transform).

        Faster than get_region() when you know the physical coordinates.
        Use this for partial updates when rotation is handled elsewhere.

        Args:
            px: Physical X start (must be multiple of 8)
            py: Physical Y start
            pw: Physical width (must be multiple of 8)
            ph: Physical height

        Returns:
            bytearray of region data
        """
        if px % 8 != 0 or pw % 8 != 0:
            raise ValueError("px and pw must be multiples of 8")

        region_bytes = pw * ph // 8
        region = bytearray(region_bytes)
        src_row_bytes = self._phys_width_bytes
        dst_row_bytes = pw // 8
        px_start = px // 8

        for row in range(ph):
            src_offset = (py + row) * src_row_bytes + px_start
            dst_offset = row * dst_row_bytes
            region[dst_offset:dst_offset + dst_row_bytes] = \
                self._buffer[src_offset:src_offset + dst_row_bytes]

        return region

    # =========================================================================
    # Drawing primitives
    # =========================================================================

    def clear(self, black: bool = False) -> None:
        """Clear the buffer (white by default, black if True).

        Respects inverted state: if inverted, colors are flipped.
        """
        effective = self._effective_black(black)
        fill = 0x00 if effective else 0xFF
        # Single allocation + slice assignment is faster than chunked loop
        # ~5KB temp allocation is fine on ESP32-S2 (2MB RAM, this is 0.2%)
        self._buffer[:] = bytes([fill] * self._buffer_size)

    def pixel(self, x: int, y: int, black: bool = True) -> None:
        """Draw a single pixel. Respects inverted state."""
        if 0 <= x < self.width and 0 <= y < self.height:
            px, py = self._transform(x, y)
            self._set_pixel_physical(px, py, self._effective_black(black))

    def get_pixel(self, x: int, y: int) -> bool:
        """Get pixel value. Returns True if black."""
        if 0 <= x < self.width and 0 <= y < self.height:
            px, py = self._transform(x, y)
            return self._get_pixel_physical(px, py)
        return False

    def set_pixel_fast(self, x: int, y: int, black: bool = True) -> None:
        """Set pixel with coordinate transform, no bounds check.

        Use this for tight loops where bounds are pre-validated.
        Faster than pixel() by skipping bounds checking.

        Args:
            x, y: Logical coordinates (must be in bounds!)
            black: Pixel color (respects inverted state)
        """
        px, py = self._transform(x, y)
        self._set_pixel_physical(px, py, self._effective_black(black))

    def hline(self, x: int, y: int, length: int, black: bool = True) -> None:
        """Draw a horizontal line with byte-aligned optimizations."""
        if length <= 0 or y < 0 or y >= self.height:
            return
        if x >= self.width or x + length <= 0:
            return

        # Clip to bounds
        if x < 0:
            length += x
            x = 0
        if x + length > self.width:
            length = self.width - x

        if length <= 0:
            return

        effective = self._effective_black(black)
        # Use lookup-based rotation dispatch
        is_swapped, x_flip, y_flip = _ROTATION_INFO[self._rotation]

        if is_swapped:
            # Logical hline becomes physical vline
            px = (self._phys_width - 1 - y) if x_flip else y
            py = (self._phys_height - x - length) if y_flip else x
            self._vline_physical(px, py, length, effective)
        else:
            # Stays as hline
            px = (self._phys_width - x - length) if x_flip else x
            py = (self._phys_height - 1 - y) if y_flip else y
            self._hline_physical(px, py, length, effective)

    def _hline_physical(self, px: int, py: int, length: int, black: bool) -> None:
        """Draw horizontal line in physical coords with byte optimization."""
        if length <= 0:
            return

        buf = self._buffer
        row = py * self._phys_width_bytes
        end = px + length
        b0, bit0 = px >> 3, px & 7
        b1, bit1 = (end - 1) >> 3, (end - 1) & 7

        if b0 == b1:
            # All in one byte - create mask for bits [bit0..bit1]
            mask = ((0xFF >> bit0) & (0xFF << (7 - bit1))) & 0xFF
            if black:
                buf[row + b0] &= mask ^ 0xFF
            else:
                buf[row + b0] |= mask
        else:
            # Start partial byte - bits [bit0..7]
            start_mask = 0xFF >> bit0
            if black:
                buf[row + b0] &= start_mask ^ 0xFF
            else:
                buf[row + b0] |= start_mask
            # Full bytes in middle - use slice assignment (faster than loop)
            if b1 > b0 + 1:
                fill_len = b1 - b0 - 1
                buf[row + b0 + 1:row + b1] = (b'\x00' if black else b'\xff') * fill_len
            # End partial byte - bits [0..bit1]
            end_mask = (0xFF << (7 - bit1)) & 0xFF
            if black:
                buf[row + b1] &= end_mask ^ 0xFF
            else:
                buf[row + b1] |= end_mask

    def _vline_physical(self, px: int, py: int, length: int, black: bool) -> None:
        """Draw vertical line in physical coords."""
        if length <= 0:
            return
        buf = self._buffer
        row_bytes = self._phys_width_bytes
        byte_col = px >> 3
        bit_mask = _BIT_MASKS[px & 7]
        inv_mask = _INV_BIT_MASKS[px & 7]

        if black:
            for i in range(length):
                buf[(py + i) * row_bytes + byte_col] &= inv_mask
        else:
            for i in range(length):
                buf[(py + i) * row_bytes + byte_col] |= bit_mask

    def vline(self, x: int, y: int, length: int, black: bool = True) -> None:
        """Draw a vertical line with optimizations for all rotations."""
        if length <= 0 or x < 0 or x >= self.width:
            return

        # Clip to bounds
        if y < 0:
            length += y
            y = 0
        if y + length > self.height:
            length = self.height - y

        if length <= 0:
            return

        effective = self._effective_black(black)
        # Use lookup-based rotation dispatch
        is_swapped, x_flip, y_flip = _ROTATION_INFO[self._rotation]

        if is_swapped:
            # Logical vline becomes physical hline
            px = (self._phys_width - y - length) if x_flip else y
            py = (self._phys_height - 1 - x) if y_flip else x
            self._hline_physical(px, py, length, effective)
        else:
            # Stays as vline
            px = (self._phys_width - 1 - x) if x_flip else x
            py = (self._phys_height - y - length) if y_flip else y
            self._vline_physical(px, py, length, effective)
