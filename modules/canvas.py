"""
Canvas - High-Level E-Paper Drawing Interface
==============================================
Unified interface combining display driver, drawing buffer, and text rendering.

This is the primary entry point for most users. It provides:
- All drawing primitives (shapes, text, bitmaps)
- Display refresh management (full, partial, region, grayscale)
- Power management (sleep, wake, deep sleep)
- Temperature monitoring
- Dependency injection for testing and customization

Usage:
    # Simple (auto-creates everything for MagTag)
    from canvas import Canvas

    canvas = Canvas()
    canvas.init()
    canvas.text("Hello!", 10, 30)
    canvas.full_refresh()

    # With dependency injection
    from hardware.spi import SPIDevice
    from drivers.ssd1680 import SSD1680

    spi = SPIDevice.from_board()
    driver = SSD1680(spi)
    canvas = Canvas(driver=driver)
"""

try:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from drivers.base import DisplayDriver
        from buffer.draw import DrawBuffer
        from text.renderer import TextRenderer
except ImportError:
    pass

from buffer import BLACK, WHITE, DARK_GRAY, LIGHT_GRAY

__all__ = ["Canvas", "BLACK", "WHITE", "DARK_GRAY", "LIGHT_GRAY"]


class Canvas:
    """
    High-level e-paper drawing interface.

    Combines display driver, drawing buffer, and text renderer into
    a unified API. Supports both simple usage and full customization
    via dependency injection.
    """

    def __init__(
        self,
        driver: "DisplayDriver | None" = None,
        buffer: "DrawBuffer | None" = None,
        text_renderer: "TextRenderer | None" = None,
        rotation: int = 90,
        depth: int = 1,
        default_font: str | None = None,
        cache_size: int = 4096,
        use_diff_buffer: bool = True,
    ):
        """
        Initialize Canvas.

        Args:
            driver: Display driver instance. If None, creates SSD1680.
            buffer: DrawBuffer instance. If None, creates one.
            text_renderer: TextRenderer instance. If None, creates one.
            rotation: Display rotation (0, 90, 180, 270).
            depth: Bit depth (1=mono, 2=grayscale).
            default_font: Path to default font file.
            cache_size: Glyph cache size in bytes.
            use_diff_buffer: Enable differential updates (driver option).
        """
        # Initialize or use provided driver
        if driver is None:
            from drivers.ssd1680 import SSD1680
            self._driver = SSD1680.create(use_diff_buffer=use_diff_buffer)
            self._owns_driver = True
        else:
            self._driver = driver
            self._owns_driver = False

        # Initialize or use provided buffer
        if buffer is None:
            from buffer import DrawBuffer
            self._buffer = DrawBuffer(
                self._driver.WIDTH,
                self._driver.HEIGHT,
                depth=depth,
                rotation=rotation,
            )
        else:
            self._buffer = buffer

        # Initialize or use provided text renderer
        if text_renderer is None:
            from text import TextRenderer
            self._text = TextRenderer(self._buffer, cache_size)
        else:
            self._text = text_renderer

        # Load default font if provided
        if default_font:
            self.load_font(default_font)

        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def close(self):
        """Release hardware resources and close font files."""
        if not self._closed:
            self._text.close()
            if self._owns_driver:
                self._driver.deinit()
            self._closed = True

    def init(self, clear: bool = True):
        """Initialize display hardware."""
        self._driver.init(clear=clear)

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def width(self) -> int:
        return self._buffer.width

    @property
    def height(self) -> int:
        return self._buffer.height

    @property
    def depth(self) -> int:
        return self._buffer.depth

    @property
    def rotation(self) -> int:
        return self._buffer.rotation

    @rotation.setter
    def rotation(self, value: int):
        self._buffer.rotation = value

    @property
    def buffer(self) -> bytearray:
        return self._buffer.buffer

    @property
    def driver(self) -> "DisplayDriver":
        """Access underlying display driver."""
        return self._driver

    # =========================================================================
    # Drawing Operations (Delegated to DrawBuffer)
    # =========================================================================

    def clear(self, color: int = WHITE):
        self._buffer.clear(color)

    def invert_display(self, inverted: bool = True):
        """Toggle hardware display inversion (instant, no redraw)."""
        self._driver.set_invert(invert_bw=inverted)

    def invert(self):
        """Software invert buffer (XOR all bytes)."""
        self._buffer.invert()

    def pixel(self, x, y, c=BLACK):
        self._buffer.pixel(x, y, c)

    def line(self, x0, y0, x1, y1, c=BLACK):
        self._buffer.line(x0, y0, x1, y1, c)

    def hline(self, x, y, length, c=BLACK):
        self._buffer.hline(x, y, length, c)

    def vline(self, x, y, length, c=BLACK):
        self._buffer.vline(x, y, length, c)

    def rect(self, x, y, w, h, c=BLACK):
        self._buffer.rect(x, y, w, h, c)

    def fill_rect(self, x, y, w, h, c=BLACK):
        self._buffer.fill_rect(x, y, w, h, c)

    def rounded_rect(self, x, y, w, h, r, c=BLACK):
        self._buffer.rounded_rect(x, y, w, h, r, c)

    def circle(self, x, y, r, c=BLACK):
        self._buffer.circle(x, y, r, c)

    def fill_circle(self, x, y, r, c=BLACK):
        self._buffer.fill_circle(x, y, r, c)

    def triangle(self, x0, y0, x1, y1, x2, y2, c=BLACK):
        self._buffer.triangle(x0, y0, x1, y1, x2, y2, c)

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, c=BLACK):
        self._buffer.fill_triangle(x0, y0, x1, y1, x2, y2, c)

    def blit(self, bmp, x, y, w, h, c=BLACK):
        self._buffer.blit(bmp, x, y, w, h, c)

    # =========================================================================
    # Text Operations (Delegated to TextRenderer)
    # =========================================================================

    def load_font(self, path: str):
        """Load the primary font."""
        self._text.load_font(path)

    def add_font(self, path: str, optional: bool = False) -> bool:
        """Add an extension font (e.g. icons)."""
        return self._text.add_font(path, optional)

    def text(
        self,
        string: str,
        x: int,
        y: int,
        color: int = BLACK,
        scale: int = 1,
        align: str = "left",
    ) -> int:
        """Draw text string. Returns width drawn."""
        return self._text.draw(string, x, y, color, scale, align)

    def measure_text(self, string: str, scale: int = 1) -> tuple:
        """Return (width, height) of text."""
        w = self._text.measure_width(string, scale)
        h = self._text.measure_height(scale)
        return w, h

    # =========================================================================
    # Display Updates
    # =========================================================================

    def full_refresh(self) -> float:
        """
        Full display refresh - clears ghosting, establishes basemap.

        Use for: Initial display, after many partials, major content changes.
        Always sleeps after to save power.

        Returns:
            Refresh time in seconds
        """
        if self._buffer.depth == 2:
            black, red = self._buffer.to_planes()
            return self._driver.display_gray(black, red)
        else:
            mono = self._buffer.to_mono()
            return self._driver.display(mono, full=True, stay_awake=False)

    def partial_refresh(self) -> float:
        """
        Partial display refresh - fast update for small changes.

        Use for: UI updates, counters, animations.
        Requires basemap (full_refresh done first).
        Stays awake for fast consecutive updates.

        Returns:
            Refresh time in seconds
        """
        if self._buffer.depth == 2:
            black, red = self._buffer.to_planes()
            return self._driver.display_gray(black, red)
        else:
            mono = self._buffer.to_mono()
            return self._driver.display(mono, full=False, stay_awake=True)

    def custom_refresh(self, lut: bytes) -> float:
        """
        Refresh using a custom LUT waveform.

        Args:
            lut: Custom LUT data (153 bytes)

        Returns:
            Refresh time in seconds
        """
        if self._buffer.depth == 2:
            black, red = self._buffer.to_planes()
            return self._driver.display_lut(lut, black, red)
        else:
            mono = self._buffer.to_mono()
            return self._driver.display_lut(lut, mono)

    def refresh(self, force_full: bool = False) -> float:
        """
        Smart refresh - auto-selects full or partial based on state.

        Args:
            force_full: Force full refresh to clear ghosting

        Returns:
            Refresh time in seconds
        """
        if self._buffer.depth == 2:
            black, red = self._buffer.to_planes()
            return self._driver.display_gray(black, red)
        else:
            mono = self._buffer.to_mono()
            return self._driver.display(
                mono,
                full=False,
                force_full=force_full,
                stay_awake=True,
            )

    def update_region(self, x: int, y: int, w: int, h: int) -> float:
        """Partial update of a specific region."""
        if self._buffer.depth != 1:
            raise ValueError("Region update only supported in 1-bit mode")

        px, py, pw, ph = self._buffer.transform_region(x, y, w, h)
        region = self._buffer.get_region(px, py, pw, ph, physical=True)
        return self._driver.display_region(region, px, py, pw, ph)

    def update_regions(self, regions: list) -> float:
        """
        Batch update multiple regions with a single refresh.

        Args:
            regions: List of (x, y, w, h) tuples

        Returns:
            Refresh time in seconds
        """
        if self._buffer.depth != 1:
            raise ValueError("Region update only supported in 1-bit mode")

        driver_regions = []
        for x, y, w, h in regions:
            px, py, pw, ph = self._buffer.transform_region(x, y, w, h)
            region_data = self._buffer.get_region(px, py, pw, ph, physical=True)
            driver_regions.append((region_data, px, py, pw, ph))

        return self._driver.display_regions(driver_regions)

    def sleep(self):
        """Enter deep sleep mode."""
        self._driver.sleep()

    def fast_clear(self, color: int = WHITE):
        """Hardware-accelerated display clear."""
        fill_byte = 0xFF if color == WHITE else 0x00
        self._driver.fast_clear(fill_byte)
        self._buffer.clear(color)

    def deep_sleep_until_button(self, buttons=None):
        """
        Put display and MCU into deep sleep, wake on button press.

        This function does not return! After wake, code.py restarts.

        Args:
            buttons: List of button indices (Buttons.A, Buttons.B, etc.)
                    If None, any button can wake the device.

        Example:
            from hardware.buttons import Buttons

            # Wake on any button
            canvas.deep_sleep_until_button()

            # Wake only on button A or B
            canvas.deep_sleep_until_button([Buttons.A, Buttons.B])
        """
        import alarm
        from hardware.buttons import Buttons

        self._driver.sleep()
        alarms = Buttons.create_deep_sleep_alarms(buttons)
        alarm.exit_and_deep_sleep_until_alarms(*alarms)

    # =========================================================================
    # Temperature & Diagnostics
    # =========================================================================

    def read_temperature(self) -> float:
        """Read temperature from display's internal sensor."""
        return self._driver.read_temperature()

    def check_temperature(self) -> tuple:
        """Read temperature and check if within operating range."""
        return self._driver.check_temperature()

    # =========================================================================
    # Partial Refresh Management
    # =========================================================================

    @property
    def partial_count(self) -> int:
        return self._driver.partial_count

    @partial_count.setter
    def partial_count(self, value: int):
        self._driver.partial_count = value

    @property
    def partial_threshold(self) -> int:
        return self._driver.partial_threshold

    @partial_threshold.setter
    def partial_threshold(self, value: int):
        self._driver.partial_threshold = value

    # =========================================================================
    # Backwards Compatibility
    # =========================================================================

    def update(
        self,
        full: bool = False,
        stay_awake: bool | None = None,
        force_full: bool = False,
    ) -> float:
        """
        [DEPRECATED] Use full_refresh(), partial_refresh(), or refresh() instead.
        """
        if stay_awake is None:
            stay_awake = not full

        if self._buffer.depth == 2:
            black, red = self._buffer.to_planes()
            return self._driver.display_gray(black, red)
        else:
            mono = self._buffer.to_mono()
            return self._driver.display(
                mono,
                full=full,
                force_full=force_full,
                stay_awake=stay_awake,
            )
