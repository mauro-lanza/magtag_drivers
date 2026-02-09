"""
Canvas - High-level E-Paper Drawing API
========================================
Combines FrameBuffer (shapes) and TextRenderer (text) into a unified interface.

Font Support:
- BF2 fonts (*.bf2): Unicode support, variable-width, LRU caching
- Supports 16-bit and 32-bit codepoints (emoji, extended Unicode)

Color Constants:
- BLACK (True) and WHITE (False) are exported for clarity
- Example: canvas.text("Hi", 10, 10, BLACK) or canvas.rect(0, 0, 50, 50, WHITE)

Usage:
    from epd_driver import EPD
    from canvas import Canvas, BLACK, WHITE

    with EPD() as epd:
        epd.init()
        canvas = Canvas(epd, rotation=90)
        canvas.clear()
        canvas.text("Hello!", 10, 30)  # Uses default cozette font
        canvas.text("Big!", 10, 50, scale=2)
        canvas.rect(10, 80, 100, 40)
        canvas.update()

        # Region partial update (faster for small areas)
        canvas.text("12:34", 100, 50)
        canvas.update_region(96, 48, 64, 24)  # Update just the clock area

        # Batched multi-region update (one refresh for multiple areas)
        canvas.update_regions([
            (0, 0, 64, 32),    # Header area
            (96, 48, 64, 24),  # Clock area
        ])

        # Unicode fonts with extended characters
        canvas.load_font("/lib/fonts/cozette-full.bf2")
        canvas.text("▲ Menu ▼", 10, 80)

        # Cache stats
        print(canvas.cache_stats)  # (bytes_used, glyph_count)

Rotation: 0=portrait, 90=landscape, 180=portrait inverted, 270=landscape inverted
"""

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

from framebuffer import FrameBuffer
from text_renderer import TextRenderer
import shapes

if TYPE_CHECKING:
    from epd_driver import EPD as EPDType


class Canvas:
    """High-level drawing canvas combining shapes and text rendering.

    EPD Protocol:
        The epd object passed to __init__ must implement:
        - WIDTH: int - Physical display width in pixels
        - HEIGHT: int - Physical display height in pixels
        - display_full(data: bytes, fast: bool = False) -> float
        - display_partial(data: bytes) -> float
        - display_partial_region(data: bytes, x: int, y: int, w: int, h: int) -> float
        - display_partial_regions(regions: list) -> float
        - display_4gray(data: bytes) -> float
        - sleep() -> None

        This allows Canvas to work with any display driver that follows
        this interface, not just the bundled EPD driver.
    """

    def __init__(self, epd: "EPDType", rotation: int = 90, default_font: str | None = None, cache_size: int = 4096):
        """
        Initialize with EPD driver.

        Args:
            epd: EPD driver instance
            rotation: Display rotation (0/90/180/270)
            default_font: Path to default font file
            cache_size: Glyph cache size in bytes (v2 renderer only)
        """
        self.epd = epd
        self._fb: FrameBuffer = FrameBuffer(epd.WIDTH, epd.HEIGHT, rotation)
        self._text: TextRenderer = TextRenderer(self._fb, default_font, cache_size)

    # =========================================================================
    # Basic drawing operations (delegated to framebuffer)
    # =========================================================================

    def clear(self, black: bool = False) -> None:
        """Clear the buffer (white by default, black if True)."""
        self._fb.clear(black)

    def pixel(self, x: int, y: int, black: bool = True) -> None:
        """Draw a single pixel."""
        self._fb.pixel(x, y, black)

    def get_pixel(self, x: int, y: int) -> bool:
        """Get pixel value. Returns True if black."""
        return self._fb.get_pixel(x, y)

    def hline(self, x: int, y: int, length: int, black: bool = True) -> None:
        """Draw a horizontal line."""
        self._fb.hline(x, y, length, black)

    def vline(self, x: int, y: int, length: int, black: bool = True) -> None:
        """Draw a vertical line."""
        self._fb.vline(x, y, length, black)

    def invert(self) -> None:
        """Toggle buffer inversion (dark mode)."""
        self._fb.invert()

    # =========================================================================
    # Shape primitives (delegated to shapes module)
    # =========================================================================

    def line(self, x0: int, y0: int, x1: int, y1: int, black: bool = True) -> None:
        """Draw a line using Bresenham's algorithm."""
        shapes.line(self._fb, x0, y0, x1, y1, black)

    def rect(self, x: int, y: int, w: int, h: int, black: bool = True) -> None:
        """Draw a rectangle outline."""
        shapes.rect(self._fb, x, y, w, h, black)

    def fill_rect(self, x: int, y: int, w: int, h: int, black: bool = True) -> None:
        """Draw a filled rectangle."""
        shapes.fill_rect(self._fb, x, y, w, h, black)

    def circle(self, cx: int, cy: int, r: int, black: bool = True) -> None:
        """Draw a circle outline."""
        shapes.circle(self._fb, cx, cy, r, black)

    def fill_circle(self, cx: int, cy: int, r: int, black: bool = True) -> None:
        """Draw a filled circle."""
        shapes.fill_circle(self._fb, cx, cy, r, black)

    def triangle(self, x0: int, y0: int, x1: int, y1: int, x2: int, y2: int, black: bool = True) -> None:
        """Draw a triangle outline."""
        shapes.triangle(self._fb, x0, y0, x1, y1, x2, y2, black)

    def fill_triangle(self, x0: int, y0: int, x1: int, y1: int, x2: int, y2: int, black: bool = True) -> None:
        """Draw a filled triangle."""
        shapes.fill_triangle(self._fb, x0, y0, x1, y1, x2, y2, black)

    def rounded_rect(self, x: int, y: int, w: int, h: int, r: int, black: bool = True) -> None:
        """Draw a rounded rectangle outline."""
        shapes.rounded_rect(self._fb, x, y, w, h, r, black)

    def blit(self, bitmap: bytes, x: int, y: int, w: int, h: int, black: bool = True) -> None:
        """Draw a 1-bit bitmap (transparent background)."""
        shapes.blit(self._fb, bitmap, x, y, w, h, black)

    # Text renderer properties (accessed less frequently, keep as properties)
    @property
    def cache_stats(self) -> tuple[int, int]:
        return self._text.cache_stats

    @property
    def is_proportional(self) -> bool:
        return self._text.is_proportional

    @property
    def font_height_prop(self) -> int:
        return self._text.font_height

    @property
    def font_width_prop(self) -> int:
        return self._text.font_width

    # Properties
    @property
    def width(self) -> int:
        return self._fb.width

    @property
    def height(self) -> int:
        return self._fb.height

    @property
    def rotation(self) -> int:
        return self._fb.rotation

    @rotation.setter
    def rotation(self, value: int) -> None:
        self._fb.rotation = value

    @property
    def buffer(self) -> bytearray:
        return self._fb.buffer

    # Font management
    def load_font(self, font_path: str, name: str | None = None) -> None:
        """Load a BDF font. Optionally cache with a name."""
        self._text.load_font(font_path, name)

    def set_font(self, name: str) -> bool:
        """Switch to a cached font. Returns True if found."""
        return self._text.set_font(name)

    def reset_font(self) -> None:
        """Reset to the default font."""
        self._text.reset_font()

    def set_cache_size(self, max_bytes: int) -> None:
        """Change glyph cache size."""
        self._text.set_cache_size(max_bytes)

    # Text rendering
    def text(self, string: str, x: int, y: int, black: bool = True,
             scale: int = 1, align: str = "left", max_width: int | None = None,
             line_spacing: int = 2) -> tuple[int, int]:
        """Draw text with alignment and optional wrapping. Returns (width, height)."""
        return self._text.draw(string, x, y, black, scale, align, max_width, line_spacing)

    def text_box(self, string: str, x: int, y: int, w: int, h: int,
                 align: str = "left", valign: str = "top",
                 black: bool = True, scale: int = 1,
                 wrap: bool = False, line_spacing: int = 2) -> int:
        """Draw text in a box with alignment. Returns rendered height."""
        return self._text.draw_box(string, x, y, w, h, align, valign, black, scale, wrap, line_spacing)

    def text_width(self, string: str, scale: int = 1) -> int:
        """Measure text width without drawing."""
        return self._text.measure_width(string, scale)

    def text_height(self, scale: int = 1) -> int:
        """Get font line height."""
        return self._text.measure_height(scale)

    # Display output
    def update(self, mode: str = "partial", fast: bool = False) -> None:
        """Push buffer to display.

        Args:
            mode: 'partial' (~0.31s) or 'full' (~1.4s)
            fast: If True and mode='full', use fast refresh (~1.8s, less flashing)

        Behavior (like GxEPD2):
            - partial: Stays awake for fast subsequent updates
            - full: Auto-hibernates to preserve image if power cut

        Call epd.sleep() explicitly after partial updates if device may be powered off.
        """
        data = self._fb.buffer
        if mode == "full":
            self.epd.display_full(data, fast=fast)
        else:
            self.epd.display_partial(data)

    def update_region(self, x: int, y: int, w: int, h: int) -> float:
        """
        Update only a rectangular region of the display (~0.3s).

        More efficient than full update when changing small areas like
        clock digits, status icons, or progress bars.

        Args:
            x: Logical X start (must be multiple of 8)
            y: Logical Y start
            w: Width in pixels (must be multiple of 8)
            h: Height in pixels

        Returns:
            float: Refresh time in seconds
        """
        px, py, pw, ph = self._fb.transform_region(x, y, w, h)
        region_data = self._fb.get_physical_region(px, py, pw, ph)
        return self.epd.display_partial_region(region_data, px, py, pw, ph)

    def update_regions(self, regions: list[tuple[int, int, int, int]]) -> float:
        """
        Update multiple rectangular regions with a single refresh.

        More efficient than calling update_region multiple times.
        Ideal for updating clock digits, multiple status fields, etc.

        Args:
            regions: List of tuples (x, y, w, h) in logical coordinates
                - x: X start (must be multiple of 8)
                - y: Y start
                - w: Width (must be multiple of 8)
                - h: Height

        Returns:
            float: Refresh time in seconds
        """
        if not regions:
            return 0.0

        epd_regions = []
        for (x, y, w, h) in regions:
            px, py, pw, ph = self._fb.transform_region(x, y, w, h)
            region_data = self._fb.get_physical_region(px, py, pw, ph)
            epd_regions.append((region_data, px, py, pw, ph))

        return self.epd.display_partial_regions(epd_regions)

    def update_4gray(self, gray_data: bytes) -> float:
        """
        Display a 4-level grayscale image.

        Args:
            gray_data: 2bpp image data (9472 bytes for 296x128)
                       Each byte = 4 pixels, MSB first
                       Values: 00=black, 01=dark gray, 10=light gray, 11=white

        Returns:
            float: Refresh time in seconds
        """
        return self.epd.display_4gray(gray_data)

    # Region helpers
    def get_region(self, x: int, y: int, w: int, h: int) -> bytearray:
        """Extract a region's bytes (for custom partial update handling)."""
        return self._fb.get_region(x, y, w, h)

    def save(self, filepath: str) -> None:
        """Save framebuffer to a raw binary file."""
        with open(filepath, 'wb') as f:
            f.write(self._fb.buffer)
