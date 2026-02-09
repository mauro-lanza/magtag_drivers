"""
Canvas - High-Level E-Paper Drawing Interface
==============================================
Unified interface combining EPD, DrawBuffer, and TextRenderer.

Updated to support:
- Font Patching (add_font)
- Multi-font rendering
- Optimized differential updates
"""

from epd import EPD
from text import TextRenderer
from draw import DrawBuffer, BLACK, WHITE, DARK_GRAY, LIGHT_GRAY

__all__ = ["Canvas", "BLACK", "WHITE", "DARK_GRAY", "LIGHT_GRAY"]


class Canvas:
    """
    High-level e-paper drawing interface.
    """

    def __init__(
        self,
        rotation: int = 90,
        depth: int = 1,
        default_font: str | None = None,
        cache_size: int = 4096,
        use_diff_buffer: bool = True,
    ):
        """
        Initialize Canvas.
        """
        # Initialize hardware
        self._epd = EPD(use_diff_buffer=use_diff_buffer)

        # Initialize drawing buffer
        self._fb = DrawBuffer(
            self._epd.WIDTH,
            self._epd.HEIGHT,
            depth=depth,
            rotation=rotation,
        )

        # Initialize text renderer
        self._text = TextRenderer(self._fb, cache_size)

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
            self._text.close()  # Close font file handles
            self._epd.deinit()
            self._closed = True

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def width(self) -> int: return self._fb.width

    @property
    def height(self) -> int: return self._fb.height

    @property
    def depth(self) -> int: return self._fb.depth

    @property
    def rotation(self) -> int: return self._fb.rotation

    @rotation.setter
    def rotation(self, value: int): self._fb.rotation = value

    @property
    def buffer(self) -> bytearray: return self._fb.buffer

    # =========================================================================
    # Drawing Operations (Delegated to DrawBuffer)
    # =========================================================================

    def clear(self, color: int = WHITE): self._fb.clear(color)

    def invert_display(self, inverted: bool = True):
        """Toggle hardware display inversion (no buffer modification).

        Uses EPD's hardware inversion which is instant and doesn't require
        redrawing. The effect is applied on the next display update.

        Args:
            inverted: If True, display will show inverted colors.
                      If False, display will show normal colors.

        Note:
            This only works for 1-bit mode. For 2-bit grayscale, use
            the software invert() method instead.
        """
        self._epd.set_invert(invert_bw=inverted)

    def invert(self):
        """Software invert the buffer (XOR all bytes).

        This modifies the buffer contents. For 1-bit mode, prefer
        invert_display() which uses hardware inversion instead.
        """
        self._fb.invert()

    def pixel(self, x, y, c=BLACK): self._fb.pixel(x, y, c)
    def line(self, x0, y0, x1, y1, c=BLACK): self._fb.line(x0, y0, x1, y1, c)
    def hline(self, x, y, length, c=BLACK): self._fb.hline(x, y, length, c)
    def vline(self, x, y, length, c=BLACK): self._fb.vline(x, y, length, c)

    def rect(self, x, y, w, h, c=BLACK): self._fb.rect(x, y, w, h, c)
    def fill_rect(self, x, y, w, h, c=BLACK): self._fb.fill_rect(x, y, w, h, c)
    def rounded_rect(self, x, y, w, h, r, c=BLACK): self._fb.rounded_rect(x, y, w, h, r, c)

    def circle(self, x, y, r, c=BLACK): self._fb.circle(x, y, r, c)
    def fill_circle(self, x, y, r, c=BLACK): self._fb.fill_circle(x, y, r, c)

    def triangle(self, x0, y0, x1, y1, x2, y2, c=BLACK): self._fb.triangle(x0, y0, x1, y1, x2, y2, c)
    def fill_triangle(self, x0, y0, x1, y1, x2, y2, c=BLACK): self._fb.fill_triangle(x0, y0, x1, y1, x2, y2, c)

    def blit(self, bmp, x, y, w, h, c=BLACK): self._fb.blit(bmp, x, y, w, h, c)

    # =========================================================================
    # Text Operations (Delegated to TextRenderer)
    # =========================================================================

    def load_font(self, path: str):
        """Load the primary (base) font."""
        self._text.load_font(path)

    def add_font(self, path: str, optional: bool = False) -> bool:
        """
        Add an extension/patch font (e.g. icons).

        Args:
            path: Path to font file
            optional: If True, do not raise error if file missing.
        """
        return self._text.add_font(path, optional)

    def text(self, string: str, x: int, y: int, color: int = BLACK,
             scale: int = 1, align: str = "left") -> int:
        """Draw text string."""
        return self._text.draw(string, x, y, color, scale, align)

    def measure_text(self, string: str, scale: int = 1) -> tuple[int, int]:
        """Return (width, height) of text."""
        w = self._text.measure_width(string, scale)
        h = self._text.measure_height(scale)
        return w, h

    # =========================================================================
    # Display Updates
    # =========================================================================

    def full_refresh(self) -> float:
        """Full display refresh - clears ghosting, resets basemap.

        Use for: Initial display, after many partials, or when changing
        significant portions of the screen.

        Always sleeps after (200ms wake overhead negligible vs 1.4s refresh).

        Returns:
            float: Refresh time in seconds
        """
        if self._fb.depth == 2:
            black, red = self._fb.to_planes()
            return self._epd.display_gray(black, red)
        else:
            mono = self._fb.to_mono()
            return self._epd.display(mono, full=True, stay_awake=False)

    def partial_refresh(self) -> float:
        """Partial display refresh - fast update for small changes.

        Use for: UI updates, counters, animations, or any incremental change.
        Requires basemap (full_refresh() done first).

        Stays awake after for fast consecutive updates (~300ms each).
        Call sleep() when done with batch of updates.

        Returns:
            float: Refresh time in seconds

        Note:
            If no basemap exists, automatically does full_refresh() instead.
        """
        if self._fb.depth == 2:
            black, red = self._fb.to_planes()
            return self._epd.display_gray(black, red)
        else:
            mono = self._fb.to_mono()
            # EPD's _display_partial already defaults to stay_awake=True
            return self._epd.display(mono, full=False, stay_awake=True)

    def custom_refresh(self, lut: bytes) -> float:
        """Full refresh using a custom LUT waveform.

        Allows using pre-defined or custom LUTs for special refresh modes:
        - LUT_LOW_FLASH: Minimal screen flashing (~2.0s)
        - LUT_TURBO: Very fast refresh (~500ms, may cause ghosting)
        - LUT_BALANCED: Single inversion, good quality (~800ms)

        Example:
            from lut import LUT_LOW_FLASH, LUT_TURBO, LUT_BALANCED

            # Comfortable refresh with less flashing
            canvas.custom_refresh(LUT_LOW_FLASH)

            # Fast refresh for rapid updates
            canvas.custom_refresh(LUT_TURBO)

        Args:
            lut: Custom LUT data (153 bytes). Import from lut module.

        Returns:
            float: Refresh time in seconds

        Note:
            After custom LUT refresh, basemap is cleared. You'll need to
            call full_refresh() before partial_refresh() works again.
        """
        if self._fb.depth == 2:
            black, red = self._fb.to_planes()
            return self._epd.display_lut(lut, black, red)
        else:
            mono = self._fb.to_mono()
            return self._epd.display_lut(lut, mono)

    def refresh(self, force_full: bool = False) -> float:
        """Smart refresh - auto-selects full or partial based on state.

        - First call or no basemap: full refresh
        - After basemap established: partial refresh
        - force_full=True: force full refresh (clear ghosting)

        Args:
            force_full: Force full refresh even if partial is available.
                        Useful to periodically clear accumulated ghosting.

        Returns:
            float: Refresh time in seconds
        """
        if self._fb.depth == 2:
            black, red = self._fb.to_planes()
            return self._epd.display_gray(black, red)
        else:
            mono = self._fb.to_mono()
            return self._epd.display(mono, full=False, force_full=force_full,
                                     stay_awake=True)

    # Backwards compatibility - deprecated
    def update(self, full: bool = False, stay_awake: bool | None = None,
                force_full: bool = False):
        """[DEPRECATED] Use full_refresh(), partial_refresh(), or refresh() instead.

        Push buffer to display.

        Args:
            full: If True, use full refresh. If False, use partial refresh.
            stay_awake: Keep display powered after update.
                        - None (default): Auto - sleep after full, stay awake after partial
                        - True: Always stay awake (for rapid consecutive updates)
                        - False: Always sleep (for power saving)
            force_full: If True with full=False, force full refresh this time.
        """
        # Default behavior: partial stays awake, full sleeps
        if stay_awake is None:
            stay_awake = not full

        if self._fb.depth == 2:
            black, red = self._fb.to_planes()
            return self._epd.display_gray(black, red)
        else:
            mono = self._fb.to_mono()
            return self._epd.display(mono, full=full,
                                     force_full=force_full, stay_awake=stay_awake)

    def update_region(self, x: int, y: int, w: int, h: int):
        """Partial update of a specific region.

        Note: Region updates always stay awake for efficiency. Call sleep()
        manually when done with all region updates.
        """
        if self._fb.depth != 1:
            raise ValueError("Region update only supported in 1-bit mode")

        # Get physical region data directly
        px, py, pw, ph = self._fb.transform_region(x, y, w, h)
        region = self._fb.get_region(px, py, pw, ph, physical=True)

        return self._epd.display_region(region, px, py, pw, ph)

    def update_regions(self, regions: list):
        """Batch update multiple regions with a single refresh.

        More efficient than calling update_region() multiple times as it
        only triggers one display refresh for all regions.

        Args:
            regions: List of (x, y, w, h) tuples defining regions to update.
                     All coordinates are in logical (rotated) space.
                     x and w must be multiples of 8.

        Returns:
            float: Refresh time in seconds

        Example:
            >>> canvas.fill_rect(10, 10, 32, 32, BLACK)  # Icon 1
            >>> canvas.fill_rect(50, 10, 32, 32, BLACK)  # Icon 2
            >>> canvas.update_regions([(8, 8, 40, 40), (48, 8, 40, 40)])
        """
        if self._fb.depth != 1:
            raise ValueError("Region update only supported in 1-bit mode")

        # Transform each region from logical to physical coordinates
        # and extract buffer data
        epd_regions = []
        for (x, y, w, h) in regions:
            px, py, pw, ph = self._fb.transform_region(x, y, w, h)
            region_data = self._fb.get_region(px, py, pw, ph, physical=True)
            epd_regions.append((region_data, px, py, pw, ph))

        return self._epd.display_regions(epd_regions)

    def sleep(self):
        """Enter deep sleep mode.

        Call this after updates when stay_awake=True or after region updates
        to minimize power consumption. Required for battery-powered devices.
        """
        self._epd.sleep()

    def deep_sleep_until_button(self, buttons=None):
        """Put both display and MCU into deep sleep, wake on button press.

        This is the most power-efficient mode for button-triggered updates.
        Both the EPD and the MCU enter their lowest power states. When any
        of the specified buttons is pressed, the MCU wakes and execution
        resumes from the beginning of code.py (not from this function).

        This uses CircuitPython's `alarm` module for deep sleep with
        PinAlarm triggers. The display is put to sleep first (RAM retained),
        then the MCU enters deep sleep.

        Typical power consumption:
          - EPD in deep sleep: ~0.5µA
          - MCU in deep sleep: ~6µA (ESP32-S2)
          - Total: <10µA vs ~50mA when active

        Args:
            buttons: List of button pins to use as wake sources.
                     Defaults to MagTag's 4 buttons if not specified.
                     Example: [board.BUTTON_A, board.BUTTON_B]

        Example:
            >>> canvas.update(full=False)
            >>> canvas.deep_sleep_until_button()  # MCU sleeps here
            >>> # After button press, code.py restarts from beginning

        Note:
            This function does not return! After wake, code.py restarts.
            Use alarm.sleep_memory to persist state across wake cycles.

        Raises:
            ImportError: If alarm module not available (older CircuitPython)
        """
        import board
        import alarm
        import alarm.pin

        # Default to MagTag buttons if not specified
        if buttons is None:
            buttons = [board.BUTTON_A, board.BUTTON_B, board.BUTTON_C, board.BUTTON_D]

        # Ensure EPD is asleep
        self._epd.sleep()

        # Create pin alarms for each button (active low, pull up)
        pin_alarms = [
            alarm.pin.PinAlarm(pin=pin, value=False, pull=True)
            for pin in buttons
        ]

        # Enter deep sleep - this function does not return!
        # On wake, code.py will restart from the beginning
        alarm.exit_and_deep_sleep_until_alarms(*pin_alarms)

    def fast_clear(self, color: int = WHITE):
        """Hardware-accelerated display clear.

        Uses EPD's auto-fill feature to clear both RAM and display without
        sending 4736 bytes over SPI. Much faster than clear() + update().

        This clears the EPD directly - the FrameBuffer is NOT updated.
        Call clear() afterwards if you need buffer consistency.

        Args:
            color: WHITE (0xFF) or BLACK (0x00)
        """
        # Map Canvas colors to EPD fill byte
        fill_byte = 0xFF if color == WHITE else 0x00
        self._epd.fast_clear(fill_byte)
        # Optionally sync buffer (user may want to draw on cleared state)
        self._fb.clear(color)

    # =========================================================================
    # Temperature & Diagnostics
    # =========================================================================

    def read_temperature(self) -> float:
        """Read temperature from the display's internal sensor.

        Returns:
            float: Temperature in degrees Celsius
        """
        return self._epd.read_temperature()

    def check_temperature(self) -> tuple[float, bool]:
        """Read temperature and check if within panel operating range (0-50°C).

        Returns:
            tuple: (temperature_celsius, is_within_range)
        """
        return self._epd.check_temperature()

    # =========================================================================
    # Partial Refresh Management
    # =========================================================================

    @property
    def partial_count(self) -> int:
        """Number of partial refreshes since last full refresh."""
        return self._epd.partial_count

    @partial_count.setter
    def partial_count(self, value: int):
        """Reset or adjust partial refresh counter."""
        self._epd.partial_count = value

    @property
    def partial_threshold(self) -> int:
        """Number of partials before auto-full refresh (0 = disabled)."""
        return self._epd.partial_threshold

    @partial_threshold.setter
    def partial_threshold(self, value: int):
        """Set auto-full refresh threshold. 0 disables auto-full."""
        self._epd.partial_threshold = value
