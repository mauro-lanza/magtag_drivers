"""
SSD1680 Fast E-Paper Driver for MagTag
======================================
A clean, reusable driver that supports multiple refresh modes.

GxEPD2 Compatible:
    - Data entry mode 0x03 (X and Y both increment)
    - RAM addressing matches GxEPD2 library for easy C++ porting
    - SPI at 20MHz (maximum supported by SSD1680)
    - Hibernation state tracking for proper wake from deep sleep

Usage:
    from epd_driver import EPD

    # Basic usage (differential buffer enabled by default)
    epd = EPD()
    epd.init()

    # Without differential buffer (only if memory-constrained, partial updates will ghost)
    epd = EPD(use_diff_buffer=False)
    epd.init()

    # Full refresh (~1.4s) - best quality, no ghosting
    epd.display_full(image_bytes)

    # Fast full refresh (~1.5s) - good quality, uses temp trick
    epd.display_full(image_bytes, fast=True)

    # Partial refresh (~0.31s) - fastest, may have slight ghosting
    epd.display_partial(image_bytes)

    # 4-Gray mode - 4 levels of gray (requires 2bpp data)
    epd.display_4gray(gray_data)

    # Region partial update - update only a rectangle
    epd.display_partial_region(data, x, y, w, h)

    # Refresh control
    epd.set_partial_refresh_threshold(5)  # Full refresh every 5 partials
    epd.set_partial_refresh_threshold(0)  # Disable auto-full refresh
    epd.force_full_refresh(image_bytes)   # Manual full refresh
    print(f"Partials since full: {epd.get_partial_count()}")

    # Power management
    epd.sleep()                    # Deep sleep (hibernation)
    print(epd.is_hibernating())    # Check if in deep sleep
    epd.init()                     # Auto-wakes from hibernation

    # Or use as context manager
    with EPD() as epd:
        epd.init()
        epd.display_full(image_bytes)
    # Automatically deinits on exit

Refresh Mode Comparison (MagTag 2.9" GDEY029T94 display):
    - Full:      ~1.4s - best quality, clears ghosting
    - Full+fast: ~1.8s - good quality, uses 100°C temp trick
    - Partial:   ~0.3s - fastest, slight ghosting
    - 4-Gray:    ~1.5s - 4 grayscale levels using 90°C temp trick

Optimizations:
    - SPI at 20MHz (max supported) for faster data transfer
    - Differential buffering writes previous frame to RAM 0x26,
      enabling hardware-level pixel comparison to reduce ghosting
    - Configurable auto-full-refresh threshold
    - Hibernation tracking ensures proper wake with hardware reset

Differential Update Design (vs GxEPD2's writeImageAgain):
    GxEPD2 syncs RAMs post-refresh with writeImageAgain() = 3 SPI transfers/update.
    We use a software buffer (_prev_buffer) to write previous frame pre-refresh = 2 SPI transfers.

    Measured on MagTag (ESP32-S2, SPI @ 20MHz):
    | Approach            | SPI Transfers | SPI Time | Notes                |
    |---------------------|---------------|----------|----------------------|
    | No buffer           | 1             | 3.0ms    | Ghosts accumulate!   |
    | Our (_prev_buffer)  | 2             | 5.3ms    | Correct, recommended |
    | GxEPD2 writeAgain   | 3             | 8.0ms    | Correct, slower      |

    ESP32-S2 has ~2MB free RAM, so we default to use_diff_buffer=True for:
    - 2.7ms faster per partial update (33% less SPI overhead)
    - 4.7KB buffer cost is negligible (0.2% of free RAM)
    - Correct differential updates (without buffer, RAM 0x26 goes stale)

Based on GxEPD2 library by Jean-Marc Zingg and official Good Display
GDEY029T94 Arduino/ESP32 sample code.
"""

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

import gc
import time

import board
import busio
import digitalio
import displayio

# Release built-in display to free SPI
displayio.release_displays()

# =============================================================================
# SSD1680 Command Constants (from datasheet)
# =============================================================================

# RAM write commands
CMD_RAM_BLACK = 0x24            # Write to black/white RAM (new image)
CMD_RAM_RED = 0x26              # Write to red/previous RAM (for differential)

# Display control commands
CMD_SW_RESET = 0x12             # Software reset
CMD_DRIVER_OUTPUT = 0x01        # Driver output control (gate lines)
CMD_DATA_ENTRY = 0x11           # Data entry mode (X/Y increment direction)
CMD_BORDER_WAVEFORM = 0x3C      # Border waveform control
CMD_DISPLAY_UPDATE_1 = 0x21     # Display update control 1 (RAM content)
CMD_DISPLAY_UPDATE_2 = 0x22     # Display update control 2 (update sequence)
CMD_MASTER_ACTIVATE = 0x20      # Master activation (trigger update)
CMD_DEEP_SLEEP = 0x10           # Enter deep sleep mode

# RAM address window
CMD_RAM_X_RANGE = 0x44          # Set RAM X address start/end
CMD_RAM_Y_RANGE = 0x45          # Set RAM Y address start/end
CMD_RAM_X_COUNTER = 0x4E        # Set RAM X address counter
CMD_RAM_Y_COUNTER = 0x4F        # Set RAM Y address counter

# Temperature sensor
CMD_TEMP_SENSOR = 0x18          # Temperature sensor control
CMD_TEMP_WRITE = 0x1A           # Write temperature register (for temp tricks)
CMD_LUT = 0x32                  # Write look-up table (waveform data)

# Update sequence control bytes (for CMD_DISPLAY_UPDATE_2)
UPDATE_FULL = 0xF7              # Full refresh: load LUT, display, power off
UPDATE_PARTIAL = 0xFC           # Partial refresh: display, stay powered
UPDATE_FAST = 0xC7              # Fast refresh: display, power off
UPDATE_LOAD_TEMP = 0xB1         # Load temperature value
UPDATE_USE_TEMP = 0x91          # Apply temperature setting
UPDATE_POWER_ON = 0xE0          # Power on sequence
UPDATE_POWER_OFF = 0x83         # Power off sequence

# Border waveform settings
BORDER_FULL = 0x05              # Border for full refresh
BORDER_PARTIAL = 0x80           # Border for partial refresh

# Temperature tricks (fake temps for different waveforms)
TEMP_FAST = 0x64                # 100°C - triggers fast refresh waveforms
TEMP_4GRAY = 0x5A               # 90°C - triggers 4-gray waveforms

# Data entry mode flags
DATA_ENTRY_XINC_YINC = 0x03     # X increment, Y increment (GxEPD2 compatible)

# =============================================================================
# Custom Look-Up Tables (Waveforms)
# =============================================================================

# 4-level grayscale LUT from Adafruit's ssd1680 grayscale example
# This waveform drives pixels to achieve 4 distinct gray levels
LUT_4GRAY = (
    b"\x2a\x60\x15\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L0
    b"\x20\x60\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L1
    b"\x28\x60\x14\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L2
    b"\x00\x60\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L3
    b"\x00\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L4
    b"\x00\x02\x00\x05\x14\x00\x00"  # TP, SR, RP of Group0
    b"\x1e\x1e\x00\x00\x00\x00\x01"  # TP, SR, RP of Group1
    b"\x00\x02\x00\x05\x14\x00\x00"  # TP, SR, RP of Group2
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group3
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group4
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group5
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group6
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group7
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group8
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group9
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group10
    b"\x00\x00\x00\x00\x00\x00\x00"  # TP, SR, RP of Group11
    b"\x24\x22\x22\x22\x23\x32\x00\x00\x00"  # FR, XON
)

# EPD state flags (bit flags for compact state tracking)
_STATE_POWER_ON = 0x01          # Panel power is on
_STATE_HIBERNATING = 0x02       # In deep sleep (needs HW reset)
_STATE_INIT_DONE = 0x04         # Display init sequence completed
_STATE_BASEMAP_SET = 0x08       # Full refresh done, partial updates allowed
_STATE_INITIAL = 0x10           # First refresh pending (must be full)


class EPD:
    """
    SSD1680 E-Paper Display Driver with Partial Refresh Support.

    Optimized for MagTag 2.9" display (296x128 pixels).
    Supports context manager protocol for automatic resource cleanup.
    """

    # Display dimensions (physical, before rotation)
    WIDTH = 128
    HEIGHT = 296
    BUFFER_SIZE = WIDTH * HEIGHT // 8  # 4736 bytes

    def __init__(self, use_diff_buffer: bool = True) -> None:
        """Initialize the EPD driver.

        Args:
            use_diff_buffer: If True (default), allocates a secondary buffer (~4.7KB)
                           to track the previous frame for differential partial updates.
                           This is REQUIRED for correct partial updates - without it,
                           RAM 0x26 becomes stale and ghosting increases.
                           Only set to False on memory-constrained systems where
                           partial updates won't be used.
        """
        # Pre-allocate reusable buffers to avoid repeated allocations
        self._cmd_buf: bytearray = bytearray(1)
        self._data_buf: bytearray = bytearray(4)  # Max 4 data bytes in a single command

        self._init_hardware()
        self._state: int = _STATE_INITIAL  # Compact state: initial refresh pending
        self._partial_count: int = 0
        self._max_partial_before_full: int = 10  # Full refresh every N partials

        # Optional differential buffer for reduced ghosting (None = disabled)
        self._prev_buffer: bytearray | None = bytearray(self.BUFFER_SIZE) if use_diff_buffer else None

    def __enter__(self) -> "EPD":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - ensure cleanup."""
        self.deinit()
        return False

    def _init_hardware(self) -> None:
        """Set up SPI and GPIO pins."""
        # SPI bus - 20MHz is max supported by SSD1680, saves ~20-40ms per frame
        self.spi = busio.SPI(board.EPD_SCK, board.EPD_MOSI)  # type: ignore[attr-defined]
        while not self.spi.try_lock():
            pass
        self.spi.configure(baudrate=20000000, phase=0, polarity=0)
        self.spi.unlock()

        # Control pins - helper to reduce repetition
        def _pin(p, out=True):
            pin = digitalio.DigitalInOut(p)
            pin.direction = digitalio.Direction.OUTPUT if out else digitalio.Direction.INPUT
            if out:
                pin.value = True
            return pin

        self.cs = _pin(board.EPD_CS)  # type: ignore[attr-defined]
        self.dc = _pin(board.EPD_DC)  # type: ignore[attr-defined]
        self.reset_pin = _pin(board.EPD_RESET)  # type: ignore[attr-defined]
        self.busy = _pin(board.EPD_BUSY, out=False)  # type: ignore[attr-defined]

    def deinit(self) -> None:
        """Release hardware resources. Call when done with the display."""
        try:
            self.sleep()
        except Exception:
            pass
        # Release GPIO pins
        for pin in (self.cs, self.dc, self.reset_pin, self.busy):
            try:
                pin.deinit()
            except Exception:
                pass
        # Release SPI
        try:
            self.spi.deinit()
        except Exception:
            pass

    # =========================================================================
    # Low-level SPI communication
    # =========================================================================

    def _write(self, cmd: int, data: int | bytes | bytearray | tuple | list | None = None) -> None:
        """Send a command byte, optionally followed by data bytes.

        Args:
            cmd: Command byte to send
            data: None, single int, tuple/list of ints, or bytes/bytearray for bulk
        """
        while not self.spi.try_lock():
            pass
        try:
            # Send command
            self._cmd_buf[0] = cmd
            self.dc.value = False
            self.cs.value = False
            self.spi.write(self._cmd_buf)
            self.cs.value = True

            # Send data if provided
            if data is not None:
                self.dc.value = True
                self.cs.value = False
                if isinstance(data, int):
                    self._data_buf[0] = data
                    self.spi.write(memoryview(self._data_buf)[:1])
                elif isinstance(data, (bytes, bytearray, memoryview)):
                    self.spi.write(data)
                else:  # tuple/list of ints
                    n = len(data)
                    for i in range(n):
                        self._data_buf[i] = data[i]
                    self.spi.write(memoryview(self._data_buf)[:n])
                self.cs.value = True
        finally:
            self.spi.unlock()

    def _write_data_only(self, data: bytes | bytearray | memoryview) -> None:
        """Send data bytes without command (for chunked writes after _write(cmd))."""
        while not self.spi.try_lock():
            pass
        try:
            self.dc.value = True
            self.cs.value = False
            self.spi.write(data)
            self.cs.value = True
        finally:
            self.spi.unlock()

    def _wait_busy(self, timeout: float = 10.0):
        """Wait for display to be ready. Returns time waited in seconds."""
        start = time.monotonic()
        deadline = start + timeout
        while self.busy.value and time.monotonic() < deadline:
            time.sleep(0.001)  # 1ms polling for more accurate timing
        return time.monotonic() - start

    def _reset(self) -> None:
        """Hardware reset the display. Clears hibernating and init flags."""
        self.reset_pin.value = False
        time.sleep(0.01)
        self.reset_pin.value = True
        time.sleep(0.01)
        # After HW reset, display needs re-initialization
        self._state &= ~(_STATE_HIBERNATING | _STATE_INIT_DONE)

    # =========================================================================
    # Display initialization modes
    # =========================================================================

    def _init_full(self) -> None:
        """Initialize for full refresh mode."""
        if self._state & _STATE_HIBERNATING:
            self._reset()  # Hardware reset required to wake from deep sleep
        if self._state & _STATE_INIT_DONE:
            return  # Already initialized, skip redundant init

        self._wait_busy()
        self._write(CMD_SW_RESET)
        self._wait_busy()

        h = self.HEIGHT - 1
        # Register configuration using named constants
        for cmd, *data in [
            (CMD_DRIVER_OUTPUT, h & 0xFF, h >> 8, 0x00),
            (CMD_DATA_ENTRY, DATA_ENTRY_XINC_YINC),
            (CMD_RAM_X_RANGE, 0x00, self.WIDTH // 8 - 1),
            (CMD_RAM_Y_RANGE, 0x00, 0x00, h & 0xFF, h >> 8),
            (CMD_BORDER_WAVEFORM, BORDER_FULL),
            (CMD_DISPLAY_UPDATE_1, 0x00, 0x80),
            (CMD_TEMP_SENSOR, 0x80),  # Use internal temp sensor
            (CMD_RAM_X_COUNTER, 0x00),
            (CMD_RAM_Y_COUNTER, 0x00, 0x00),
        ]:
            self._write(cmd, data if data else None)
        self._wait_busy()
        self._state |= _STATE_INIT_DONE

    def _init_partial(self, x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> None:
        """Initialize for partial refresh mode.

        Based on official Good Display sample code.
        Does a hardware reset and sets up registers for partial mode.
        Official timing: ~0.3s at 25°C.

        Note: After hibernate, _STATE_BASEMAP_SET is cleared (unless diff buffer),
        so display_partial() will automatically do a full refresh first.

        Args:
            x, y, w, h: Optional region (in pixels). Defaults to full screen.
                        x and w must be multiples of 8.
        """
        # Hardware reset clears all registers, so we need to re-init
        self._reset()
        self._wait_busy()
        self._write(CMD_SW_RESET)
        self._wait_busy()

        # Re-configure essential registers after reset
        h_max = self.HEIGHT - 1
        for cmd, *data in [
            (CMD_DRIVER_OUTPUT, h_max & 0xFF, h_max >> 8, 0x00),
            (CMD_DATA_ENTRY, DATA_ENTRY_XINC_YINC),
            (CMD_BORDER_WAVEFORM, BORDER_PARTIAL),  # Partial mode border
            (CMD_DISPLAY_UPDATE_1, 0x00, 0x80),
            (CMD_TEMP_SENSOR, 0x80),
        ]:
            self._write(cmd, data if data else None)

        # Set RAM window for the region
        self._set_ram_window(x, y, w, h)

    def _init_temp_mode(self, temp: int) -> None:
        """Initialize using temperature LUT trick for fast full refresh.

        Tricks the display into using waveforms for a different temperature.
        - TEMP_FAST (100°C) = fast refresh (~1.5s)

        Args:
            temp: Temperature constant (TEMP_FAST)
        """
        if self._state & _STATE_HIBERNATING:
            self._reset()  # Hardware reset to wake from deep sleep
        self._write(CMD_SW_RESET)
        self._wait_busy()

        # Configure display after reset (same as _init_full)
        h = self.HEIGHT - 1
        self._write(CMD_DRIVER_OUTPUT, (h & 0xFF, h >> 8, 0x00))
        self._write(CMD_DATA_ENTRY, DATA_ENTRY_XINC_YINC)
        self._write(CMD_RAM_X_RANGE, (0x00, self.WIDTH // 8 - 1))
        self._write(CMD_RAM_Y_RANGE, (0x00, 0x00, h & 0xFF, h >> 8))
        self._write(CMD_BORDER_WAVEFORM, BORDER_FULL)
        self._write(CMD_RAM_X_COUNTER, 0x00)
        self._write(CMD_RAM_Y_COUNTER, (0x00, 0x00))

        # Step 1: Read internal temperature sensor
        self._write(CMD_TEMP_SENSOR, 0x80)
        self._write(CMD_DISPLAY_UPDATE_2, UPDATE_LOAD_TEMP)
        self._write(CMD_MASTER_ACTIVATE)
        self._wait_busy()

        # Step 2: Override temperature to trick display
        self._write(CMD_TEMP_WRITE, (temp, 0x00))
        self._write(CMD_DISPLAY_UPDATE_2, UPDATE_USE_TEMP)
        self._write(CMD_MASTER_ACTIVATE)
        self._wait_busy()

        # Mark initialization as done
        self._state |= _STATE_INIT_DONE

    def _set_ram_window(self, x: int = 0, y: int = 0, w: int | None = None, h: int | None = None) -> None:
        """Set RAM address window for partial updates.

        With data entry mode 0x03, both X and Y increment.
        Y=0 is top of display, Y increases downward.

        Args:
            x: X start position in pixels (will be converted to bytes)
            y: Y start position in pixels
            w: Width in pixels, defaults to full width
            h: Height in pixels, defaults to full height
        """
        w = w or self.WIDTH
        h = h or self.HEIGHT
        x_bytes = x >> 3  # x // 8
        x_end_bytes = (x + w - 1) >> 3
        y_end = y + h - 1

        self._write(CMD_RAM_X_RANGE, (x_bytes, x_end_bytes))
        self._write(CMD_RAM_Y_RANGE, (y & 0xFF, y >> 8, y_end & 0xFF, y_end >> 8))
        self._write(CMD_RAM_X_COUNTER, x_bytes)
        self._write(CMD_RAM_Y_COUNTER, (y & 0xFF, y >> 8))

    # =========================================================================
    # Update modes
    # =========================================================================

    def _update(self, mode: int = UPDATE_FULL):
        """Execute update waveform. Returns refresh time in seconds.

        Args:
            mode: Update sequence constant (UPDATE_FULL, UPDATE_PARTIAL, UPDATE_FAST)

        Power state after update (per GxEPD2):
            - UPDATE_FULL: power OFF
            - UPDATE_PARTIAL: power ON (for fast subsequent updates)
            - UPDATE_FAST: power OFF
        """
        self._write(CMD_DISPLAY_UPDATE_2, mode)
        self._write(CMD_MASTER_ACTIVATE)
        refresh_time = self._wait_busy()
        # Track power state: partial keeps power on, others turn it off
        if mode == UPDATE_PARTIAL:
            self._state |= _STATE_POWER_ON
        else:
            self._state &= ~_STATE_POWER_ON
        return refresh_time

    # =========================================================================
    # Public API
    # =========================================================================

    def init(self, clear: bool = True) -> None:
        """Initialize the display. Call this before first use.

        Args:
            clear: If True (default), clears display to white with full refresh.
                   Set to False for fast boot when you'll immediately draw content.
                   Note: First display_partial() will auto-do a full refresh anyway
                   to establish the basemap.
        """
        self._init_full()
        if clear:
            self.clear()

    def clear(self, color: int = 0xFF) -> None:
        """
        Clear screen to a solid color.

        Args:
            color: 0xFF for white, 0x00 for black
        """
        self._init_full()
        # Single allocation - ESP32-S2 has plenty of RAM
        clear_data = bytes([color]) * self.BUFFER_SIZE

        self._write(CMD_RAM_BLACK, clear_data)
        self._write(CMD_RAM_RED, clear_data)
        self._update(UPDATE_FULL)
        self._state |= _STATE_BASEMAP_SET

        # Sync differential buffer with cleared state (avoid per-byte loop)
        if self._prev_buffer:
            self._prev_buffer[:] = clear_data

        # Hibernate to preserve image if power is cut
        self.sleep()

    def display_full(
        self,
        data: bytes,
        fast: bool = False,
        lut: bytes | None = None
    ) -> float:
        """
        Display image with full refresh.

        Args:
            data: Image data as bytes (4736 bytes, 1 bit per pixel)
            fast: If True, use temperature trick for faster refresh
                  Like GxEPD2's useFastFullUpdate. Good for normal temps.
            lut: Optional custom LUT (153 bytes). If provided, uses the custom
                 waveform instead of OTP. Ignored if fast=True.

        Returns:
            float: Refresh time in seconds (time BUSY pin was high)
        """
        if fast:
            self._init_temp_mode(TEMP_FAST)
        else:
            self._init_full()

        # Load custom LUT if provided (not needed for fast mode)
        if lut is not None and not fast:
            self._write(CMD_LUT, lut)

        self._write(CMD_RAM_BLACK, data)
        self._write(CMD_RAM_RED, data)

        # Use UPDATE_FAST for custom LUT, otherwise normal mode selection
        if lut is not None and not fast:
            update_mode = UPDATE_FAST
        else:
            update_mode = UPDATE_FAST if fast else UPDATE_FULL
        refresh_time = self._update(update_mode)
        # Set basemap, clear initial refresh flag
        self._state = (self._state | _STATE_BASEMAP_SET) & ~_STATE_INITIAL
        self._partial_count = 0

        # Sync differential buffer with current display state
        if self._prev_buffer:
            self._prev_buffer[:] = data

        # Hibernate after full refresh to preserve image if power is cut
        self.sleep()

        return refresh_time

    def display_partial(
        self,
        data: bytes,
        force_full: bool = False,
        lut: bytes | None = None
    ) -> float:
        """
        Display image with partial refresh (~0.31s).
        Automatically does full refresh every N updates to clear ghosting.

        If use_diff_buffer=True was set in __init__, this writes the previous
        frame to CMD_RAM_RED for hardware-level differential updates, which
        significantly reduces ghosting.

        Partial refresh stays awake for fast subsequent updates (like GxEPD2).
        Call sleep() explicitly when done to preserve image if power may be cut.

        Args:
            data: Image data as bytes (4736 bytes, 1 bit per pixel)
            force_full: Force a full refresh this time
            lut: Optional custom LUT (153 bytes). If provided, uses the custom
                 waveform for partial update. Useful for faster partials or
                 custom visual effects.

        Returns:
            float: Refresh time in seconds (time BUSY pin was high)
        """
        # Do full refresh if: initial, basemap not set, forced, or too many partials
        needs_full = (self._state & (_STATE_INITIAL | _STATE_BASEMAP_SET)) != _STATE_BASEMAP_SET
        # Auto-full threshold: 0 = disabled, otherwise check count
        threshold_exceeded = (
            self._max_partial_before_full > 0
            and self._partial_count >= self._max_partial_before_full
        )
        if needs_full or force_full or threshold_exceeded:
            return self.display_full(data, lut=lut)

        self._init_partial()

        # Load custom LUT if provided
        if lut is not None:
            self._write(CMD_LUT, lut)

        # Write previous frame to OLD RAM for differential comparison
        # NOTE: Without _prev_buffer, RAM contains stale data from last
        # display_full(), causing increasing ghosting with each partial update.
        if self._prev_buffer:
            self._write(CMD_RAM_RED, self._prev_buffer)

        # Write new frame to NEW RAM
        self._write(CMD_RAM_BLACK, data)

        # Use UPDATE_FAST for custom LUT to avoid OTP reload
        refresh_time = self._update(UPDATE_FAST if lut else UPDATE_PARTIAL)

        # Store current frame as previous for next differential update
        if self._prev_buffer:
            self._prev_buffer[:] = data

        self._partial_count += 1
        gc.collect()

        return refresh_time

    def display_with_lut(
        self,
        lut: bytes,
        data_black: bytes,
        data_red: bytes | None = None,
        update_mode: int = UPDATE_FAST
    ) -> float:
        """
        Display image using a custom look-up table (waveform).

        Custom LUTs allow specialized display modes like grayscale, faster
        refresh, or custom visual effects by controlling how pixels transition.

        Args:
            lut: Custom LUT data (typically 153 bytes for SSD1680).
                 Use LUT_4GRAY for 4-level grayscale.
            data_black: Data for RAM_BLACK plane (primary image data).
                        For 1bpp: 4736 bytes. For 2bpp split: 4736 bytes.
            data_red: Data for RAM_RED plane (secondary/color plane).
                      If None, data_black is written to both planes.
            update_mode: Display update sequence (default UPDATE_FAST=0xC7).
                         Use UPDATE_FAST for custom LUTs.

        Returns:
            float: Refresh time in seconds

        Example:
            # Display with 4-gray LUT using pre-split bit planes
            epd.display_with_lut(LUT_4GRAY, black_plane, red_plane)
        """
        self._init_full()

        # Load custom LUT
        self._write(CMD_LUT, lut)

        # Write to RAM planes
        self._write(CMD_RAM_BLACK, data_black)
        self._write(CMD_RAM_RED, data_red if data_red is not None else data_black)

        refresh_time = self._update(update_mode)
        self._state &= ~_STATE_BASEMAP_SET  # Custom LUT invalidates basemap
        gc.collect()
        return refresh_time

    def display_4gray(self, data: bytes) -> float:
        """
        Display 4-level grayscale image using custom LUT.

        Convenience wrapper around display_with_lut() that handles 2bpp to
        dual 1bpp conversion automatically.

        Input format: 2bpp packed, 4 pixels per byte, MSB first.
        - 00 = Black, 01 = Dark Gray, 10 = Light Gray, 11 = White

        Args:
            data: 2bpp image data (9472 bytes for 128x296 native display)
                  Each byte contains 4 pixels, MSB first.

        Returns:
            float: Refresh time in seconds
        """
        # Convert 2bpp input to two 1bpp planes
        # The LUT expects: RAM_BLACK=high bit, RAM_RED=low bit
        # For grayscale: 00=black, 01=dark, 10=light, 11=white
        data_len = len(data)
        ram_black = bytearray(data_len // 2)
        ram_red = bytearray(data_len // 2)

        out_idx = 0
        for i in range(0, data_len, 2):
            d1 = data[i]
            d2 = data[i + 1] if i + 1 < data_len else 0
            black_byte = 0
            red_byte = 0

            # Process 4 pixels from d1
            for _ in range(4):
                pix = (d1 >> 6) & 0x03  # Get top 2 bits as 0-3
                # High bit goes to RAM_BLACK, low bit goes to RAM_RED
                black_byte = (black_byte << 1) | ((pix >> 1) & 1)
                red_byte = (red_byte << 1) | (pix & 1)
                d1 <<= 2

            # Process 4 pixels from d2
            for _ in range(4):
                pix = (d2 >> 6) & 0x03
                black_byte = (black_byte << 1) | ((pix >> 1) & 1)
                red_byte = (red_byte << 1) | (pix & 1)
                d2 <<= 2

            ram_black[out_idx] = black_byte
            ram_red[out_idx] = red_byte
            out_idx += 1

        return self.display_with_lut(LUT_4GRAY, ram_black, ram_red)

    def display_partial_region(self, data: bytes, x: int, y: int, w: int, h: int):
        """
        Update only a rectangular region of the display (~0.3s).

        Args:
            data: Image data for the region (w * h // 8 bytes)
            x: X start position (must be multiple of 8)
            y: Y start position
            w: Width in pixels (must be multiple of 8)
            h: Height in pixels

        Returns:
            float: Refresh time in seconds
        """
        if not (self._state & _STATE_BASEMAP_SET):
            raise RuntimeError("Must call display_full() first")
        if x & 7 or w & 7:
            raise ValueError("x and w must be multiples of 8")
        if len(data) != w * h >> 3:
            raise ValueError("Data size mismatch")

        self._init_partial(x, y, w, h)
        self._write(CMD_RAM_BLACK, data)
        refresh_time = self._update(UPDATE_PARTIAL)
        self._partial_count += 1
        gc.collect()
        return refresh_time

    def display_partial_regions(self, regions: list[tuple[bytes, int, int, int, int]]) -> float:
        """
        Update multiple rectangular regions with a single refresh.

        Args:
            regions: List of tuples (data, x, y, w, h)
                x and w must be multiples of 8.

        Returns:
            float: Refresh time in seconds
        """
        if not (self._state & _STATE_BASEMAP_SET):
            raise RuntimeError("Must call display_full() first")
        if not regions:
            return 0.0

        for i, (data, x, y, w, h) in enumerate(regions):
            if x & 7 or w & 7:
                raise ValueError(f"Region {i}: x/w must be multiples of 8")
            if len(data) != w * h >> 3:
                raise ValueError(f"Region {i}: data size mismatch")

            # First region does full partial init
            if i == 0:
                self._init_partial(x, y, w, h)
            else:
                # Just update RAM window for subsequent regions
                self._set_ram_window(x, y, w, h)

            self._write(CMD_RAM_BLACK, data)

        refresh_time = self._update(UPDATE_PARTIAL)
        self._partial_count += 1
        gc.collect()
        return refresh_time

    # =========================================================================
    # Power control (GxEPD2 compatible)
    # =========================================================================

    def power_on(self) -> None:
        """Turn on panel driving voltages.

        Called automatically by display methods. Manual use allows
        pre-powering before writing data for faster updates.

        Note: If display is hibernating, this requires init() first.
        """
        if self._state & _STATE_HIBERNATING:
            # Can't power on from hibernate without hardware reset + init
            return
        if not (self._state & _STATE_POWER_ON):
            self._write(CMD_DISPLAY_UPDATE_2, UPDATE_POWER_ON)
            self._write(CMD_MASTER_ACTIVATE)
            self._wait_busy()
            self._state |= _STATE_POWER_ON

    def power_off(self) -> None:
        """Turn off panel driving voltages.

        Prevents screen fading over time when display is idle.
        Call this after updates if display will be idle for a while.
        The display content is preserved (e-paper is bistable).
        """
        if self._state & _STATE_HIBERNATING:
            # Already in hibernate (deeper than power off)
            return
        if self._state & _STATE_POWER_ON:
            self._write(CMD_DISPLAY_UPDATE_2, UPDATE_POWER_OFF)
            self._write(CMD_MASTER_ACTIVATE)
            self._wait_busy()
            self._state &= ~_STATE_POWER_ON

    def sleep(self) -> None:
        """Enter deep sleep mode. Call when done to preserve display lifespan.

        Deep sleep powers off completely and requires hardware reset to wake.
        Display content is preserved (e-paper is bistable), but display RAM
        may be undefined after wake, so next update will do a full refresh
        (unless _prev_buffer is enabled, which can restore RAM).
        """
        self.power_off()  # Ensure clean power off first
        self._write(CMD_DEEP_SLEEP, 0x01)
        time.sleep(0.1)
        # Set hibernating, clear power/init flags
        self._state = (self._state | _STATE_HIBERNATING) & ~(_STATE_POWER_ON | _STATE_INIT_DONE)
        # Only clear basemap if no software buffer to restore from
        if not self._prev_buffer:
            self._state &= ~_STATE_BASEMAP_SET

    # =========================================================================
    # Refresh control
    # =========================================================================

    def force_full_refresh(self, data: bytes | None = None):
        """
        Force a full refresh to clear ghosting.

        Args:
            data: Image data. If None, uses previous buffer (requires diff buffer).

        Returns:
            float: Refresh time in seconds
        """
        if data is None:
            if not self._prev_buffer:
                raise ValueError("No data and diff buffer not enabled")
            data = self._prev_buffer
        return self.display_full(data)

    def set_partial_refresh_threshold(self, count: int) -> None:
        """
        Set how many partial refreshes before automatic full refresh.

        Lower values = less ghosting but slower average update time.
        Higher values = faster updates but more ghosting accumulation.

        Args:
            count: Number of partial refreshes before auto full refresh.
                   - 0: Disable auto-full refresh (manual control only)
                   - 1-50: Auto-full after N partials (clamped to range)
        """
        if count <= 0:
            self._max_partial_before_full = 0
        else:
            self._max_partial_before_full = min(50, count)

    def get_partial_refresh_threshold(self) -> int:
        """Get current partial refresh threshold."""
        return self._max_partial_before_full

    def get_partial_count(self) -> int:
        """Get number of partial refreshes since last full refresh."""
        return self._partial_count

    def reset_partial_count(self) -> None:
        """Reset partial refresh counter without doing a full refresh."""
        self._partial_count = 0

    def is_power_on(self) -> bool:
        """Check if panel power is currently on."""
        return bool(self._state & _STATE_POWER_ON)

    def is_hibernating(self) -> bool:
        """Check if display is in deep sleep (requires reset to wake)."""
        return bool(self._state & _STATE_HIBERNATING)

    def is_init_done(self) -> bool:
        """Check if display init sequence has been run."""
        return bool(self._state & _STATE_INIT_DONE)
