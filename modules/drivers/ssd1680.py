"""
SSD1680 - E-Paper Display Driver
================================
Driver for the SSD1680 EPD controller used in the Adafruit MagTag
and similar displays (GDEY029T94 - 2.9" 296x128 B/W).

Architecture
------------
This driver uses a layered architecture:
  - SPIDevice: Low-level SPI communication
  - DriverState: Clean state management
  - SSD1680: Display-specific logic

The SSD1680 has two display RAMs:
  - BW RAM (0x24): Black/White image data (1=white, 0=black)
  - RED RAM (0x26): Red data OR previous frame for differential updates

The controller selects one of 5 LUTs based on RAM bit combinations,
enabling hardware-accelerated differential updates.
"""
import gc
import time

try:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from hardware.spi import SPIDevice
except ImportError:
    pass

from .base import DisplayDriver
from .state import DisplayState, DriverState
from . import commands as CMD
from . import sequences as SEQ


class SSD1680(DisplayDriver):
    """
    SSD1680 E-Paper Display Driver.

    Controls the GDEY029T94 2.9" 296x128 black/white e-paper display.
    Supports full refresh, partial refresh, region updates, and 4-gray mode.

    Example:
        from hardware import SPIDevice
        from drivers import SSD1680

        with SPIDevice.from_board() as spi:
            epd = SSD1680(spi)
            epd.init()
            epd.display(buffer)
            epd.sleep()
    """
    WIDTH = 128
    HEIGHT = 296
    BUFFER_SIZE = 4736  # (WIDTH // 8) * HEIGHT

    def __init__(
        self,
        spi: "SPIDevice",
        use_diff_buffer: bool = True,
    ):
        """
        Initialize the SSD1680 driver.

        Args:
            spi: Configured SPIDevice instance
            use_diff_buffer: If True, maintain previous frame for
                differential updates (uses 4736 bytes extra RAM)
        """
        self._spi = spi
        self._state = DriverState()
        self._prev_buffer = bytearray(self.BUFFER_SIZE) if use_diff_buffer else None

    @classmethod
    def create(cls, use_diff_buffer: bool = True) -> "SSD1680":
        """
        Factory method that creates SSD1680 with auto-configured SPI.

        Convenience method for typical MagTag usage.

        Args:
            use_diff_buffer: Enable differential update buffer

        Returns:
            Configured SSD1680 instance
        """
        # Import here to avoid circular imports and allow lazy loading
        import displayio
        displayio.release_displays()

        from hardware.spi import SPIDevice
        spi = SPIDevice.from_board()
        return cls(spi, use_diff_buffer)

    def deinit(self):
        """Release hardware resources."""
        if not self._state.is_sleeping:
            self.sleep()
        self._spi.deinit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.deinit()
        return False

    # =========================================================================
    # Initialization
    # =========================================================================

    def _init_full(self):
        """
        Initialize for full refresh mode (Mode 1).

        Configures the SSD1680 for a complete display refresh using
        the Mode 1 waveform from OTP.
        """
        if self._state.is_sleeping:
            self._spi.hardware_reset()
            self._state.on_wake()

        if self._state.state == DisplayState.READY and not self._state.in_partial_mode:
            return  # Already initialized for full mode

        self._spi.wait_ready(timeout=SEQ.TIMEOUT_COMMAND)
        self._spi.write_command(CMD.CMD_SW_RESET)
        self._spi.wait_ready(timeout=SEQ.TIMEOUT_COMMAND)

        # Configure gate driver for panel height
        h = self.HEIGHT - 1
        self._spi.write_command(CMD.CMD_DRIVER_OUTPUT, (h & 0xFF, h >> 8, 0x00))

        # Data entry mode: X increment, Y increment, X first
        self._spi.write_command(CMD.CMD_DATA_ENTRY, SEQ.DATA_ENTRY_INC)

        # Set full RAM window
        self._spi.write_command(CMD.CMD_RAM_X, (0x00, self.WIDTH // 8 - 1))
        self._spi.write_command(CMD.CMD_RAM_Y, (0x00, 0x00, h & 0xFF, h >> 8))

        # Border waveform: follow LUT for clean full refresh
        self._spi.write_command(CMD.CMD_BORDER, SEQ.BORDER_FULL)

        # Display Update Control 1: Normal RAM, centered source
        self._spi.write_command(CMD.CMD_UPDATE_CTRL1, (0x00, 0x80))

        # Use internal temperature sensor
        self._spi.write_command(CMD.CMD_TEMP_SENSOR, SEQ.TEMP_SENSOR_INTERNAL)

        # Booster soft start
        self._spi.write_command(CMD.CMD_SOFT_START, SEQ.SOFT_START_DEFAULT)

        # Initialize RAM counters
        self._spi.write_command(CMD.CMD_RAM_X_CNT, 0x00)
        self._spi.write_command(CMD.CMD_RAM_Y_CNT, (0x00, 0x00))

        self._spi.wait_ready(timeout=SEQ.TIMEOUT_COMMAND)
        self._state.on_init_complete()
        self._state.in_partial_mode = False

    def _init_partial(self, x=0, y=0, w=None, h=None):
        """
        Initialize for partial refresh mode (Mode 2).

        Mode 2 uses RED RAM as "old" image and BW RAM as "new",
        enabling hardware differential updates.
        """
        w = w or self.WIDTH
        h = h or self.HEIGHT

        # Fast path: already in partial mode
        if (self._state.in_partial_mode and
            not self._state.is_sleeping and
            self._state.is_ready):
            self._set_window(x, y, w, h)
            return

        # Transition from full mode (just change border)
        if self._state.is_ready and not self._state.is_sleeping:
            self._spi.write_command(CMD.CMD_BORDER, SEQ.BORDER_PARTIAL)
            self._set_window(x, y, w, h)
            self._state.in_partial_mode = True
            return

        # Full init from sleep/uninitialized
        self._spi.hardware_reset()
        self._state.on_wake()
        self._spi.wait_ready(timeout=SEQ.TIMEOUT_COMMAND)

        # Configure essential registers
        gh = self.HEIGHT - 1
        self._spi.write_command(CMD.CMD_DRIVER_OUTPUT, (gh & 0xFF, gh >> 8, 0x00))
        self._spi.write_command(CMD.CMD_DATA_ENTRY, SEQ.DATA_ENTRY_INC)
        self._spi.write_command(CMD.CMD_BORDER, SEQ.BORDER_PARTIAL)
        self._spi.write_command(CMD.CMD_UPDATE_CTRL1, (0x00, 0x80))
        self._spi.write_command(CMD.CMD_TEMP_SENSOR, SEQ.TEMP_SENSOR_INTERNAL)
        self._spi.write_command(CMD.CMD_SOFT_START, SEQ.SOFT_START_DEFAULT)

        self._set_window(x, y, w, h)
        self._state.on_init_complete()
        self._state.in_partial_mode = True

    def _set_window(self, x=0, y=0, w=None, h=None):
        """Set RAM address window for reading/writing."""
        w = w or self.WIDTH
        h = h or self.HEIGHT
        x_bytes = x >> 3
        x_end = (x + w - 1) >> 3
        y_end = y + h - 1

        self._spi.write_command(CMD.CMD_RAM_X, (x_bytes, x_end))
        self._spi.write_command(CMD.CMD_RAM_Y, (y & 0xFF, y >> 8, y_end & 0xFF, y_end >> 8))
        self._spi.write_command(CMD.CMD_RAM_X_CNT, x_bytes)
        self._spi.write_command(CMD.CMD_RAM_Y_CNT, (y & 0xFF, y >> 8))

    def _update(self, mode: int) -> float:
        """Execute display update sequence."""
        self._spi.write_command(CMD.CMD_UPDATE_CTRL2, mode)
        self._spi.write_command(CMD.CMD_ACTIVATE)

        # Select timeout based on mode
        if mode == SEQ.SEQ_PARTIAL:
            timeout = SEQ.TIMEOUT_PARTIAL
            op_name = "partial refresh"
        elif mode in (SEQ.SEQ_FULL, SEQ.SEQ_CUSTOM_LUT):
            timeout = SEQ.TIMEOUT_FULL
            op_name = "full refresh"
        else:
            timeout = SEQ.TIMEOUT_DEFAULT
            op_name = f"update 0x{mode:02X}"

        return self._spi.wait_ready(timeout=timeout, operation=op_name)

    # =========================================================================
    # Public API
    # =========================================================================

    def init(self, clear: bool = True):
        """Initialize display. Optionally clear to white."""
        self._init_full()
        if clear:
            self.clear()

    def clear(self, color: int = 0xFF):
        """Clear display to solid color with full refresh."""
        self._init_full()
        data = bytes([color]) * self.BUFFER_SIZE

        self._spi.write_command(CMD.CMD_RAM_BLACK, data)
        self._spi.write_command(CMD.CMD_RAM_RED, data)
        self._update(SEQ.SEQ_FULL)

        self._state.on_full_refresh_complete()
        if self._prev_buffer:
            self._prev_buffer[:] = data

        self.sleep()

    def display(
        self,
        data: bytes,
        full: bool = True,
        force_full: bool = False,
        stay_awake: bool = False,
    ) -> float:
        """
        Display an image buffer.

        Args:
            data: Image buffer (4736 bytes, 1 bit per pixel)
            full: If True, use full refresh. If False, partial.
            force_full: Force full refresh even when partial requested.
            stay_awake: Keep display powered after update.

        Returns:
            Refresh time in seconds

        Raises:
            ValueError: If buffer size is incorrect
        """
        if len(data) != self.BUFFER_SIZE:
            raise ValueError(
                f"Buffer must be {self.BUFFER_SIZE} bytes, got {len(data)}"
            )

        if full:
            return self._display_full(data, stay_awake=stay_awake)
        else:
            return self._display_partial(data, force_full=force_full, stay_awake=stay_awake)

    def _display_full(
        self,
        data: bytes,
        lut: bytes | None = None,
        stay_awake: bool = False,
    ) -> float:
        """Full refresh display update."""
        self._init_full()

        if lut is not None:
            self._spi.write_command(CMD.CMD_LUT, lut)

        self._spi.write_command(CMD.CMD_RAM_BLACK, data)
        self._spi.write_command(CMD.CMD_RAM_RED, data)

        mode = SEQ.SEQ_CUSTOM_LUT if lut else SEQ.SEQ_FULL
        t = self._update(mode)

        self._state.on_full_refresh_complete()
        if self._prev_buffer:
            self._prev_buffer[:] = data

        if not stay_awake:
            self.sleep()
        return t

    def _display_partial(
        self,
        data: bytes,
        force_full: bool = False,
        lut: bytes | None = None,
        stay_awake: bool = True,
    ) -> float:
        """Partial refresh display update."""
        # Check if full refresh needed
        if self._state.needs_full_refresh() or force_full:
            return self._display_full(data, lut=lut, stay_awake=stay_awake)

        self._init_partial()
        self._set_window(0, 0, self.WIDTH, self.HEIGHT)

        if lut is not None:
            self._spi.write_command(CMD.CMD_LUT, lut)

        # Write differential data
        if self._prev_buffer:
            self._spi.write_command(CMD.CMD_RAM_RED, self._prev_buffer)
        self._spi.write_command(CMD.CMD_RAM_BLACK, data)

        mode = SEQ.SEQ_CUSTOM_LUT if lut else SEQ.SEQ_PARTIAL
        t = self._update(mode)

        if self._prev_buffer:
            self._prev_buffer[:] = data
        self._state.on_partial_refresh_complete()

        if not stay_awake:
            self.sleep()

        gc.collect()
        return t

    def display_gray(self, black_plane: bytes, red_plane: bytes) -> float:
        """Display a 4-level grayscale image using custom LUT."""
        from .lut import LUT_4GRAY
        return self.display_lut(LUT_4GRAY, black_plane, red_plane)

    def display_lut(
        self,
        lut: bytes,
        black: bytes,
        red: bytes | None = None,
        vgh: int = SEQ.DEFAULT_VGH,
        vsh1: int = SEQ.DEFAULT_VSH1,
        vsh2: int = SEQ.DEFAULT_VSH2,
        vsl: int = SEQ.DEFAULT_VSL,
        vcom: int = SEQ.DEFAULT_VCOM,
    ) -> float:
        """Display with a custom LUT waveform."""
        self._init_full()
        self._set_waveform(lut, vgh, vsh1, vsh2, vsl, vcom)

        self._spi.write_command(CMD.CMD_RAM_BLACK, black)
        self._spi.write_command(CMD.CMD_RAM_RED, red if red else black)

        t = self._update(SEQ.SEQ_CUSTOM_LUT)

        # Custom LUT invalidates basemap
        self._state.has_basemap = False
        gc.collect()
        return t

    def _set_waveform(
        self,
        lut: bytes,
        vgh: int,
        vsh1: int,
        vsh2: int,
        vsl: int,
        vcom: int,
    ):
        """Set complete waveform including voltage levels."""
        self._spi.write_command(CMD.CMD_LUT, lut[:153])
        self._spi.write_command(CMD.CMD_VGH, vgh)
        self._spi.write_command(CMD.CMD_VSH_VSL, (vsh1, vsh2, vsl))
        self._spi.write_command(CMD.CMD_VCOM, vcom)

    def display_region(
        self,
        data: bytes,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> float:
        """Update a rectangular region."""
        return self.display_regions([(data, x, y, w, h)])

    def display_regions(self, regions: list) -> float:
        """Update multiple regions with a single refresh."""
        if not self._state.has_basemap:
            raise RuntimeError("Must do full refresh first")
        if not regions:
            return 0.0

        first = regions[0]
        self._init_partial(first[1], first[2], first[3], first[4])

        stride = self.WIDTH // 8

        for i, (data, x, y, w, h) in enumerate(regions):
            if x & 7 or w & 7:
                raise ValueError(f"Region {i}: x and w must be multiples of 8")

            self._set_window(x, y, w, h)
            x_byte = x // 8
            w_byte = w // 8

            # Write old data for differential update
            if self._prev_buffer:
                old_data = bytearray(w_byte * h)
                for row in range(h):
                    src = (y + row) * stride + x_byte
                    dst = row * w_byte
                    old_data[dst:dst + w_byte] = self._prev_buffer[src:src + w_byte]
                self._spi.write_command(CMD.CMD_RAM_RED, old_data)

                # Update prev buffer
                for row in range(h):
                    dst = (y + row) * stride + x_byte
                    src = row * w_byte
                    self._prev_buffer[dst:dst + w_byte] = data[src:src + w_byte]

            # Reset counters and write new data
            self._spi.write_command(CMD.CMD_RAM_X_CNT, x >> 3)
            self._spi.write_command(CMD.CMD_RAM_Y_CNT, (y & 0xFF, y >> 8))
            self._spi.write_command(CMD.CMD_RAM_BLACK, data)

        t = self._update(SEQ.SEQ_PARTIAL)
        self._state.on_partial_refresh_complete()
        gc.collect()
        return t

    # =========================================================================
    # Power Management
    # =========================================================================

    def sleep(self, retain_ram: bool = True):
        """Enter deep sleep mode."""
        if self._state.is_sleeping:
            return

        self._power_off()
        mode = SEQ.SLEEP_MODE_1 if retain_ram else SEQ.SLEEP_MODE_2
        self._spi.write_command(CMD.CMD_DEEP_SLEEP, mode)
        time.sleep(0.001)
        self._state.on_sleep(retain_ram)

    def wake(self):
        """Wake from deep sleep."""
        if not self._state.is_sleeping:
            return
        self._spi.hardware_reset()
        self._state.on_wake()

    def _power_on(self):
        """Power on analog circuits."""
        if self._state.is_sleeping:
            return
        self._spi.write_command(CMD.CMD_UPDATE_CTRL2, SEQ.SEQ_POWER_ON)
        self._spi.write_command(CMD.CMD_ACTIVATE)
        self._spi.wait_ready(timeout=SEQ.TIMEOUT_POWER)

    def _power_off(self):
        """Power off analog circuits."""
        if self._state.is_sleeping:
            return
        self._spi.write_command(CMD.CMD_UPDATE_CTRL2, SEQ.SEQ_POWER_OFF)
        self._spi.write_command(CMD.CMD_ACTIVATE)
        self._spi.wait_ready(timeout=SEQ.TIMEOUT_POWER)

    # =========================================================================
    # Hardware Features
    # =========================================================================

    def set_invert(self, invert_bw: bool = False, invert_red: bool = False):
        """Enable hardware display inversion."""
        if self._state.is_sleeping:
            self._spi.hardware_reset()
            self._state.on_wake()
            self._spi.wait_ready()

        a = (0x80 if invert_red else 0x00) | (0x08 if invert_bw else 0x00)
        self._spi.write_command(CMD.CMD_UPDATE_CTRL1, (a, 0x80))

    def fast_clear(self, color: int = 0xFF):
        """Hardware-accelerated clear using auto-fill."""
        self._init_full()
        self._auto_fill(color)
        self._update(SEQ.SEQ_FULL)
        self._state.on_full_refresh_complete()
        if self._prev_buffer:
            self._prev_buffer[:] = bytes([color]) * len(self._prev_buffer)
        self.sleep()

    def _auto_fill(self, pattern: int = 0xFF, red_ram: bool = True, bw_ram: bool = True):
        """Use hardware auto-write for solid fills."""
        first_bit = (pattern >> 7) & 0x01
        param = (first_bit << 7) | (0b110 << 4) | 0b101  # Full screen

        if red_ram:
            self._spi.write_command(CMD.CMD_AUTO_WRITE_RED, param)
            self._spi.wait_ready(timeout=SEQ.TIMEOUT_COMMAND)
        if bw_ram:
            self._spi.write_command(CMD.CMD_AUTO_WRITE_BW, param)
            self._spi.wait_ready(timeout=SEQ.TIMEOUT_COMMAND)

    def set_gate_start(self, position: int):
        """Set gate scan start position for hardware scrolling."""
        self._spi.write_command(CMD.CMD_GATE_SCAN_START, (position & 0xFF, (position >> 8) & 0x01))

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def read_temperature(self) -> float:
        """Read temperature from internal sensor (requires MISO)."""
        if not self._spi.has_miso:
            raise RuntimeError("Temperature reading requires MISO pin")

        if self._state.is_sleeping:
            self._spi.hardware_reset()
            self._state.on_wake()

        if self._state.state == DisplayState.UNINITIALIZED:
            self._init_full()

        self._spi.write_command(CMD.CMD_TEMP_SENSOR, SEQ.TEMP_SENSOR_INTERNAL)
        self._spi.write_command(CMD.CMD_UPDATE_CTRL2, SEQ.SEQ_LOAD_TEMP)
        self._spi.write_command(CMD.CMD_ACTIVATE)
        self._spi.wait_ready()

        data = self._spi.read_data(CMD.CMD_TEMP_READ, 2)
        raw = (data[0] << 4) | (data[1] >> 4)

        if raw & 0x800:
            raw = raw - 0x1000
        return raw / 16.0

    def check_temperature(self) -> tuple:
        """Read temperature and check if within operating range."""
        temp = self.read_temperature()
        in_range = SEQ.TEMP_MIN <= temp <= SEQ.TEMP_MAX
        return temp, in_range

    def read_status(self) -> dict:
        """Read diagnostic status bits."""
        if self._state.is_sleeping:
            self._spi.hardware_reset()
            self._state.on_wake()

        if self._state.state == DisplayState.UNINITIALIZED:
            self._init_full()

        self._power_on()

        self._spi.write_command(CMD.CMD_HV_READY, 0x00)
        self._spi.wait_ready()
        self._spi.write_command(CMD.CMD_VCI_DETECT, 0x04)
        self._spi.wait_ready()

        data = self._spi.read_data(CMD.CMD_STATUS, 1)
        raw = data[0]

        return {
            'hv_ready': not bool(raw & 0x20),
            'vci_ok': not bool(raw & 0x10),
            'busy': bool(raw & 0x04),
            'chip_id': raw & 0x03,
            'raw': raw,
        }

    def read_otp_info(self) -> dict:
        """Read OTP information."""
        if self._state.is_sleeping:
            self._spi.hardware_reset()
            self._state.on_wake()

        if self._state.state == DisplayState.UNINITIALIZED:
            self._init_full()

        display_data = self._spi.read_data(CMD.CMD_OTP_DISPLAY, 11)
        user_id = self._spi.read_data(CMD.CMD_OTP_USER_ID, 10)

        return {
            'vcom_otp_sel': display_data[0],
            'vcom_register': display_data[1],
            'display_mode': bytes(display_data[2:7]),
            'waveform_version': bytes(display_data[7:11]),
            'user_id': bytes(user_id),
        }

    def calculate_crc(self) -> int:
        """Calculate CRC of display RAM contents."""
        if self._state.is_sleeping:
            self._spi.hardware_reset()
            self._state.on_wake()

        if self._state.state == DisplayState.UNINITIALIZED:
            self._init_full()

        self._spi.write_command(CMD.CMD_CRC_CALC)
        self._spi.wait_ready()

        data = self._spi.read_data(CMD.CMD_CRC_STATUS, 2)
        return (data[0] << 8) | data[1]

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def state(self) -> DriverState:
        return self._state

    @property
    def is_sleeping(self) -> bool:
        return self._state.is_sleeping

    @property
    def partial_count(self) -> int:
        return self._state.partial_count

    @partial_count.setter
    def partial_count(self, value: int):
        self._state.partial_count = value

    @property
    def partial_threshold(self) -> int:
        return self._state.partial_threshold

    @partial_threshold.setter
    def partial_threshold(self, value: int):
        self._state.partial_threshold = value

    @property
    def has_temperature_sensor(self) -> bool:
        return self._spi.has_miso
