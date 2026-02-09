"""
EPD - E-Paper Display Driver for SSD1680
=========================================

This driver controls the SSD1680 EPD controller used in the Adafruit MagTag
and similar displays (GDEY029T94 - 2.9" 296x128 B/W).

Architecture Overview (from SSD1680 Datasheet)
----------------------------------------------
The SSD1680 has two display RAMs:
  - BW RAM (0x24): Black/White image data (1=white, 0=black)
  - RED RAM (0x26): Red data OR previous frame for differential updates

The controller selects one of 5 LUTs (waveform tables) based on the
combination of bits from both RAMs:

    | RED RAM | BW RAM | LUT Used | Typical Use              |
    |---------|--------|----------|--------------------------|
    |    0    |    0   |   LUT0   | Pixel staying black      |
    |    0    |    1   |   LUT1   | Pixel staying white      |
    |    1    |    0   |   LUT2   | Pixel changing to black  |
    |    1    |    1   |   LUT3   | Pixel changing to white  |

This enables hardware-accelerated differential updates: by writing the
OLD image to RED RAM and NEW image to BW RAM, the controller applies
different waveforms to changing vs unchanged pixels.

Display Modes
-------------
- Mode 1: Standard refresh - full OTP waveform, no RAM ping-pong
- Mode 2: Partial refresh - supports RAM ping-pong for differential updates

The mode is selected via the Display Update Control 2 register (0x22).

Power States
------------
The SSD1680 has several power states:
  - Active: Analog circuits powered, ready for updates
  - Power Off: Analog off, oscillator off, RAM retained
  - Deep Sleep Mode 1 (0x01): Ultra-low power, RAM retained
  - Deep Sleep Mode 2 (0x11): Ultra-low power, RAM lost

Waking from deep sleep requires a hardware reset (RES# pin toggle).
The BUSY pin is undefined during deep sleep.

References
----------
- SSD1680 Datasheet: GDEY029T94_docs/SSD1680.md
- Good Display Sample Code: GDEY029T94_docs/esp32_sample/
"""
import gc
import time
import board
import busio
import digitalio
import displayio
from lut import LUT_4GRAY

# Release built-in display to free SPI bus for direct control
displayio.release_displays()

# =============================================================================
# SSD1680 Command Register Addresses (from Datasheet Section 7)
# =============================================================================

# Panel Configuration
_CMD_DRIVER = 0x01          # Driver Output Control - sets gate count (height)
_CMD_SOFT_START = 0x0C      # Booster Soft Start - timing for charge pump
_CMD_DATA_ENTRY = 0x11      # Data Entry Mode - X/Y increment direction
_CMD_SW_RESET = 0x12        # Software Reset - resets all registers to POR

# Power Control
_CMD_SLEEP = 0x10           # Deep Sleep Mode - 0x01=retain RAM, 0x11=lose RAM

# Temperature & Waveform
_CMD_TEMP_SENSOR = 0x18     # Temperature Sensor Control - 0x80=use internal
_CMD_TEMP_WRITE = 0x1A      # Write to Temperature Register (for temp tricks)
_CMD_TEMP_READ = 0x1B       # Read from Temperature Register (12-bit value)
_CMD_LUT = 0x32             # Write Look-Up Table (153-159 bytes waveform data)

# Diagnostics
_CMD_HV_READY = 0x14        # HV Ready Detection
_CMD_VCI_DETECT = 0x15      # VCI Low Voltage Detection
_CMD_STATUS = 0x2F          # Status Bit Read (HV ready, VCI, chip ID)
_CMD_CRC_CALC = 0x34        # CRC Calculation (triggers CRC compute on RAM)
_CMD_CRC_STATUS = 0x35      # CRC Status Read (16-bit CRC result)

# Display Update Sequence
_CMD_ACTIVATE = 0x20        # Master Activation - triggers update sequence
_CMD_UPDATE_1 = 0x21        # Display Update Control 1 - RAM invert options
_CMD_UPDATE_2 = 0x22        # Display Update Control 2 - update sequence select

# RAM Access
_CMD_RAM_BLACK = 0x24       # Write to BW RAM - new/current image data
_CMD_RAM_RED = 0x26         # Write to RED RAM - old image for differential
_CMD_RAM_READ = 0x27        # Read RAM for Image Detection
_CMD_RAM_READ_OPT = 0x41    # Read RAM Option (select BW or RED RAM to read)

# Border Control
_CMD_BORDER = 0x3C          # Border Waveform Control - edge pixel behavior

# OTP Reading
_CMD_OTP_DISPLAY = 0x2D     # OTP Read for Display Option (VCOM, waveform version)
_CMD_OTP_USER_ID = 0x2E     # User ID Read (10 bytes from OTP)

# Voltage Registers
_CMD_VGH = 0x03             # Gate Driving Voltage (VGH)
_CMD_VSH_VSL = 0x04         # Source Driving Voltage (VSH1, VSH2, VSL)
_CMD_VCOM = 0x2C            # VCOM DC Level Register

# Gate Scan Control
_CMD_GATE_SCAN_START = 0x0F # Gate Scan Start Position (hardware scrolling/offset)

# RAM Address Configuration
_CMD_RAM_X = 0x44           # Set RAM X Address Start/End (in bytes, 0-15)
_CMD_RAM_Y = 0x45           # Set RAM Y Address Start/End (0-295)
_CMD_RAM_X_CNT = 0x4E       # Set RAM X Address Counter (current write position)
_CMD_RAM_Y_CNT = 0x4F       # Set RAM Y Address Counter (current write position)

# Auto Write RAM (hardware pattern fills)
_CMD_AUTO_WRITE_RED = 0x46  # Auto Write RED RAM for Regular Pattern
_CMD_AUTO_WRITE_BW = 0x47   # Auto Write B/W RAM for Regular Pattern

# =============================================================================
# Display Update Sequences (Register 0x22 values)
# =============================================================================
# The Update Control 2 register (0x22) selects which sequence to run when
# Master Activation (0x20) is triggered. The sequence controls:
#   - Clock enable/disable
#   - Analog power enable/disable
#   - Temperature sensor reading
#   - LUT loading (Mode 1 or Mode 2)
#   - Display driving
#   - Power-down sequence
#
# Bit meanings (from datasheet examples):
#   Bit 7: Enable Clock
#   Bit 6: Enable Analog
#   Bit 5: Load Temperature
#   Bit 4: Load LUT / Display Mode select
#   Bit 3: Display Mode 2 select
#   Bit 2-1: Power down control (Disable Analog, Disable OSC)
#   Bit 0: (varies)
#
# Documented sequences all end with power-down (bits 0-2 set).
# Clearing bits 0-1 skips power-down, keeping analog/OSC running.

# Full refresh sequences (Mode 1 - standard waveform)
_UPDATE_FULL = 0xF7         # Clk -> Analog -> Temp -> Mode1 -> Power Off
                            # Used for: Initial display, clearing ghosting
                            # Time: ~1.4s at 25°C
                            #
                            # NOTE: Benchmarks showed that 0xD7 (GxEPD2 fast mode)
                            # is actually SLOWER than 0xF7 on GDEY029T94 panel.
                            # The temperature trick provides no benefit here.

_UPDATE_CUSTOM_LUT = 0xC7   # Clk -> Analog -> Mode1 -> Power Off (no temp read)
                            # Used for: Custom LUT refresh (LUT already loaded)
                            # Time: ~1.4s

# Partial refresh sequences (Mode 2 - differential waveform)
#
# The "stay powered" modes (bits 0-1 cleared) avoid power-off/power-on cycle
# between updates, saving ~340ms per partial. The original 508ms timing was
# due to _init_partial() overhead (HW+SW reset every time), not the update mode.
#
# With optimized _init_partial() (minimal transition):
#   0xFC = Mode2 + temp + STAYS POWERED = ~308ms ✓
#   0xCC = Mode2 no temp + STAYS POWERED = ~308ms (but 1.2s on some displays?)
#
# Standard modes (power off after each update):
#   0xFF = Mode2 + temp + power off = ~648ms (308ms + 340ms power-on)
#   0xCF = Mode2 no temp + power off

_UPDATE_PARTIAL = 0xFC      # Clk -> Analog -> Temp -> Mode2 -> STAYS POWERED
                            # Used for: Partial updates with temp compensation
                            # Benefit: No power-on delay on next update
                            # Time: ~0.3s at 25°C

# NOTE: 0xCC (partial without temp) was tested but only saves ~3ms.
# Not worth the added complexity for minimal gain.

# Power control sequences
_UPDATE_POWER_ON = 0xE0     # Power on analog circuits only
_UPDATE_POWER_OFF = 0x83    # Power off analog circuits only

# Temperature reading sequence
_UPDATE_LOAD_TEMP = 0xB1    # Load temperature value from internal sensor
                            # Used by read_temperature() to get actual panel temp

# =============================================================================
# Deep Sleep Modes (Register 0x10 values)
# =============================================================================
# The sleep command (0x10) controls power-down state.
# Format: A[1:0] selects mode
#   00 = Normal Mode (not sleeping)
#   01 = Deep Sleep Mode 1 (RAM retained)
#   11 = Deep Sleep Mode 2 (RAM lost, lowest power)
# Note: Mode 2 is 0x03 (binary 11), not 0x11!

_SLEEP_MODE_1 = 0x01        # Deep Sleep Mode 1: RAM retained, ~0.5µA
                            # Wake requires hardware reset (RES# pin toggle)
                            # BUSY pin undefined during sleep

_SLEEP_MODE_2 = 0x03        # Deep Sleep Mode 2: RAM lost, lowest power
                            # Binary 11 in A[1:0] bits
                            # Wake requires HW reset + full re-init

# =============================================================================
# Voltage Defaults (for custom LUT waveforms)
# =============================================================================
# These values are written to voltage registers when using custom LUTs.
# The SSD1680 needs explicit voltage settings for custom waveforms,
# as OTP waveforms include their own voltage configuration.
#
# Gate Voltage (0x03): Controls VGH level
# Source Voltage (0x04): Controls VSH1, VSH2, VSL levels
# VCOM (0x2C): Controls common voltage level
#
# Default values match typical GDEY029T94 panel requirements.

_DEFAULT_VGH = 0x17         # Gate High Voltage: 20V (from datasheet table)
                            # Range: 0x00-0x26 maps to 10V-21V

_DEFAULT_VSH1 = 0x41        # Source High Voltage 1: +15V
                            # Used for white-to-black transitions

_DEFAULT_VSH2 = 0xA8        # Source High Voltage 2: +5V
                            # Used for gray levels (4-gray mode)

_DEFAULT_VSL = 0x32         # Source Low Voltage: -15V
                            # Used for black-to-white transitions

_DEFAULT_VCOM = 0x50        # VCOM DC Level: -2.0V
                            # Optimal contrast for this panel

# =============================================================================
# Temperature Sensor Values (Register 0x18)
# =============================================================================
# The internal temperature sensor is enabled with 0x80.
# External sensor or manual temp can also be used.

_TEMP_SENSOR_INTERNAL = 0x80  # Use internal temperature sensor
                              # Sensor result affects OTP LUT selection

# Panel Operating Temperature Range (from GDEY029T94 datasheet)
# IC supports -40 to +85°C but panel is limited to 0-50°C
_TEMP_MIN = 0               # Minimum operating temperature (°C)
_TEMP_MAX = 50              # Maximum operating temperature (°C)

# =============================================================================
# Operation Timeouts (in seconds)
# =============================================================================
# Different operations have different expected durations. Using operation-
# specific timeouts helps detect hangs faster for quick operations while
# allowing enough time for slow operations.

_TIMEOUT_DEFAULT = 10.0     # Default timeout for unknown operations
_TIMEOUT_FULL = 5.0         # Full refresh: ~1.4s typical, 5s max
_TIMEOUT_PARTIAL = 1.0      # Partial refresh: ~0.3s typical, 1s max
_TIMEOUT_COMMAND = 0.5      # Simple commands: SW reset, temp read, etc.
_TIMEOUT_POWER = 0.5        # Power on/off sequences

# =============================================================================
# Booster Soft Start Timing (Register 0x0C)
# =============================================================================
# Controls the charge pump soft-start sequence.
# Format: (Phase A, Phase B, Phase C, Duration)
# Values from Good Display sample code - optimized for GDEY029T94.

_SOFT_START_DEFAULT = (0x8B, 0x9C, 0x96, 0x0F)
                            # Phase A: 0x8B - 10ms strength
                            # Phase B: 0x9C - driving strength
                            # Phase C: 0x96 - driving strength
                            # Duration: 0x0F - timing control

# =============================================================================
# Border Waveform Settings (Register 0x3C)
# =============================================================================
# Controls how the border (edge) pixels behave during refresh.
# A[7:6] selects mode: 00=GS Transition, 01=Fix Level, 10=VCOM, 11=HiZ
#
# For full refresh: GS Transition (0x05) - border follows LUT waveform along
#   with the rest of the display, ensuring uniform refresh.
#
# For partial refresh: VCOM (0x80) - border held at VCOM reference voltage.
#   This is preferred over HiZ (0xC0) because:
#   - HiZ leaves border pixels electrically floating, which can cause drift
#     or visual artifacts during partial updates
#   - VCOM actively holds the border at a stable voltage, preventing edge
#     flickering while only the inner region is updated
#   - Matches Good Display sample code recommendation

_BORDER_FULL = 0x05         # A[7:6]=00 GS Transition, A[2]=1 Follow LUT, A[1:0]=01 LUT1
_BORDER_PARTIAL = 0x80      # A[7:6]=10 VCOM level

# =============================================================================
# Data Entry Mode (Register 0x11)
# =============================================================================
# Controls RAM address auto-increment direction after each byte write.
# Format: 0b00000_AM_ID1_ID0
#   ID[1:0]: 00=Y-,X-  01=Y-,X+  10=Y+,X-  11=Y+,X+
#   AM: 0=X first, then Y; 1=Y first, then X

_DATA_ENTRY_INC = 0x03      # X+, Y+ with X incrementing first
                            # Matches typical image buffer layout

# =============================================================================
# Driver State Flags (internal tracking)
# =============================================================================
# These flags track the EPD's current state to optimize operations
# and avoid invalid command sequences.

_STATE_POWER_ON = 0x01      # Analog circuits are powered (ready for update)
_STATE_HIBERNATING = 0x02   # In deep sleep - BUSY pin undefined, needs HW reset
_STATE_INIT_DONE = 0x04     # Initialization sequence completed
_STATE_BASEMAP = 0x08       # Full refresh done - partial updates now allowed
_STATE_INITIAL = 0x10       # First refresh pending - must be full refresh
_STATE_PARTIAL_MODE = 0x20  # Initialized for partial refresh mode (skip re-init)

class EPD:
    """
    SSD1680 E-Paper Display Driver.

    Controls the GDEY029T94 2.9" 296x128 black/white e-paper display
    via SPI interface. Supports full refresh, partial refresh, region
    updates, and 4-gray mode with custom LUTs.

    Physical vs Logical Coordinates:
        The display panel is 128 (X) x 296 (Y) pixels physically.
        WIDTH/HEIGHT here refer to physical dimensions (RAM layout).
        The Canvas class handles rotation to logical 296x128.

    Differential Updates:
        When use_diff_buffer=True, we maintain a copy of the previous
        frame to write to RED RAM during partial updates. This enables
        hardware-accelerated differential refresh - the SSD1680 applies
        different waveforms to changing vs unchanged pixels, reducing
        ghosting and improving contrast.

    Attributes:
        WIDTH: Physical display width (128 pixels, 16 bytes)
        HEIGHT: Physical display height (296 pixels)
        BUFFER_SIZE: RAM size in bytes (128/8 * 296 = 4736)
    """
    WIDTH = 128              # Physical width = SSD1680 source outputs used
    HEIGHT = 296             # Physical height = SSD1680 gate outputs used
    BUFFER_SIZE = 4736       # (WIDTH // 8) * HEIGHT bytes

    def __init__(self, use_diff_buffer: bool = True):
        """
        Initialize the EPD driver.

        Args:
            use_diff_buffer: If True, allocates 4736 bytes to store the
                previous frame for differential updates. This significantly
                reduces ghosting on partial refreshes by allowing the
                SSD1680 to apply different waveforms to changing pixels.
                Disable only if RAM is critically limited.
        """
        self._cmd_buf = bytearray(1)     # Reusable buffer for commands
        self._data_buf = bytearray(4)    # Reusable buffer for short data
        self._state = _STATE_INITIAL     # Start in "needs full refresh" state
        self._partial_count = 0          # Count partials since last full
        self._partial_threshold = 10     # Auto-full after N partials (GDEY029T94 recommends 5)
        self._prev_buffer = bytearray(self.BUFFER_SIZE) if use_diff_buffer else None
        self._has_miso = False           # Track if MISO is available for reads
        self._init_hw()

    def _init_hw(self):
        """
        Initialize hardware: SPI bus and GPIO pins.

        Pin assignments are from board module (MagTag-specific).
        SPI runs at 20MHz (datasheet Section 12.1 max for writes).
        """
        # Try to use MISO if available (needed for temperature reads)
        miso_pin = getattr(board, 'EPD_MISO', None)
        self._has_miso = miso_pin is not None
        self.spi = busio.SPI(board.EPD_SCK, board.EPD_MOSI, miso_pin)  # type: ignore[attr-defined]
        start = time.monotonic()
        while not self.spi.try_lock():
            if time.monotonic() - start > 1.0:
                raise RuntimeError("SPI lock timeout")
        self.spi.configure(baudrate=20_000_000, phase=0, polarity=0)
        self.spi.unlock()

        # Chip Select - active low
        self.cs = digitalio.DigitalInOut(board.EPD_CS)  # type: ignore[attr-defined]
        self.cs.direction = digitalio.Direction.OUTPUT
        self.cs.value = True  # Deselected

        # Data/Command - low=command, high=data
        self.dc = digitalio.DigitalInOut(board.EPD_DC)  # type: ignore[attr-defined]
        self.dc.direction = digitalio.Direction.OUTPUT
        self.dc.value = True  # Default to data mode

        # Hardware Reset - active low, directly controls RES# pin
        self.rst = digitalio.DigitalInOut(board.EPD_RESET)  # type: ignore[attr-defined]
        self.rst.direction = digitalio.Direction.OUTPUT
        self.rst.value = True  # Not in reset

        # Busy signal - high when display is processing
        # WARNING: Undefined during deep sleep! Check state before reading.
        self.busy = digitalio.DigitalInOut(board.EPD_BUSY)  # type: ignore[attr-defined]
        self.busy.direction = digitalio.Direction.INPUT

    def deinit(self):
        """Release hardware resources. Puts display to sleep first."""
        self.sleep()
        self.spi.deinit()
        self.cs.deinit()
        self.dc.deinit()
        self.rst.deinit()
        self.busy.deinit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.deinit()
        return False

    # =========================================================================
    # Low-Level SPI Communication
    # =========================================================================

    def _write(self, cmd: int, data=None):
        """
        Send a command and optional data to the SSD1680.

        The SPI protocol uses D/C# pin to distinguish:
          - D/C# LOW: Byte is a command
          - D/C# HIGH: Bytes are data for the previous command

        For large data (RAM writes), pass bytes/bytearray directly.
        For small data (registers), pass tuple of ints.

        Args:
            cmd: Command byte (0x00-0xFF)
            data: None, int, tuple of ints, or bytes/bytearray
        """
        # Wait if display is busy before sending new command
        if self.busy.value:
            self._wait()

        while not self.spi.try_lock():
            pass
        try:
            # Send command byte (D/C low)
            self.dc.value = False
            self.cs.value = False
            self._cmd_buf[0] = cmd
            self.spi.write(self._cmd_buf)
            self.cs.value = True

            # Send data bytes if provided (D/C high)
            if data is not None:
                self.dc.value = True
                self.cs.value = False
                if isinstance(data, int):
                    # Single byte
                    self._data_buf[0] = data
                    self.spi.write(memoryview(self._data_buf)[:1])
                elif isinstance(data, (bytes, bytearray, memoryview)):
                    # Large buffer - write directly
                    self.spi.write(data)
                else:
                    # Tuple/list of ints - pack into temp buffer
                    for i, b in enumerate(data):
                        self._data_buf[i] = b
                    self.spi.write(memoryview(self._data_buf)[:len(data)])
                self.cs.value = True
        finally:
            self.spi.unlock()

    def _read(self, cmd: int, length: int = 1) -> bytes:
        """
        Read data from an SSD1680 register.

        Read operations use a slower SPI clock (2.5MHz max per datasheet).
        The first byte read is dummy data and is discarded.

        Args:
            cmd: Command byte for the register to read
            length: Number of data bytes to read (excluding dummy byte)

        Returns:
            bytes: Data read from the register
        """
        if self.busy.value:
            self._wait()

        # Allocate buffer for dummy byte + actual data
        read_buf = bytearray(length + 1)

        while not self.spi.try_lock():
            pass
        try:
            # Reconfigure for read speed (2.5MHz max)
            self.spi.configure(baudrate=2_500_000, phase=0, polarity=0)

            # Send command byte (D/C low)
            self.dc.value = False
            self.cs.value = False
            self._cmd_buf[0] = cmd
            self.spi.write(self._cmd_buf)

            # Read data (D/C high)
            self.dc.value = True
            self.spi.readinto(read_buf)
            self.cs.value = True

            # Restore write speed
            self.spi.configure(baudrate=20_000_000, phase=0, polarity=0)
        finally:
            self.spi.unlock()

        # Skip dummy byte, return actual data
        return bytes(read_buf[1:])

    def _wait(self, timeout: float = _TIMEOUT_DEFAULT, operation: str | None = None,
              sleep_ms: int = 0):
        """
        Wait for the display to finish processing.

        The BUSY pin is HIGH while:
          - Outputting display waveform
          - Programming OTP
          - Communicating with temperature sensor

        WARNING: BUSY is undefined during deep sleep! Always check
        _STATE_HIBERNATING before calling this.

        Args:
            timeout: Maximum wait time in seconds. Use operation-specific
                     constants for better timeout handling:
                     - _TIMEOUT_FULL (5.0s) for full refresh
                     - _TIMEOUT_PARTIAL (1.0s) for partial refresh
                     - _TIMEOUT_COMMAND (0.5s) for simple commands
            operation: Optional operation name for error messages
            sleep_ms: If > 0, sleep this many milliseconds between polls.
                      Reduces CPU usage for battery-powered applications.
                      Use 0 for maximum responsiveness (tight polling).

        Returns:
            float: Time spent waiting (useful for benchmarking)

        Raises:
            RuntimeError: If timeout exceeded
        """
        start = time.monotonic()
        while self.busy.value:
            if time.monotonic() - start > timeout:
                op_str = f" during {operation}" if operation else ""
                raise RuntimeError(f"EPD Timeout{op_str} (>{timeout}s)")
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000)
        return time.monotonic() - start

    def _reset(self, verify: bool = False):
        """
        Hardware reset via RES# pin.

        This is the only way to wake from deep sleep (hibernate).
        After reset, all registers return to POR (power-on reset) values,
        so re-initialization is required.

        Reset timing: 1ms pulse + 1ms recovery (datasheet doesn't specify minimum).

        Args:
            verify: If True, read status register after reset to verify
                    chip ID. Raises RuntimeError if chip doesn't respond
                    or returns unexpected ID.
        """
        self.rst.value = False
        time.sleep(0.001)  # 1ms reset pulse
        self.rst.value = True
        time.sleep(0.001)  # 1ms recovery time
        # Clear hibernating (we just woke up), init done (need re-init), and partial mode
        self._state &= ~(_STATE_HIBERNATING | _STATE_INIT_DONE | _STATE_PARTIAL_MODE)

        if verify:
            # Read status register to verify chip is responding
            # Chip ID should be 0x01 for SSD1680 (bits 1:0 of status)
            try:
                data = self._read(_CMD_STATUS, 1)
                chip_id = data[0] & 0x03
                if chip_id != 0x01:
                    raise RuntimeError(f"Unexpected chip ID: 0x{chip_id:02X} (expected 0x01)")
            except Exception as e:
                raise RuntimeError(f"SSD1680 not responding after reset: {e}")

    # =========================================================================
    # Initialization Modes
    # =========================================================================

    def _init_full(self):
        """
        Initialize for full refresh mode (Mode 1).

        This configures the SSD1680 for a complete display refresh using
        the Mode 1 waveform from OTP. Mode 1 drives all pixels through a
        full transition cycle regardless of current state.

        Register configuration:
          - Driver Output (0x01): Gate count = HEIGHT-1
          - Data Entry (0x11): X+,Y+ increment for standard buffer layout
          - RAM X/Y Range (0x44/45): Full screen
          - Border (0x3C): Use LUT for clean edges
          - Update Control 1 (0x21): Normal RAM output
          - Temp Sensor (0x18): Use internal sensor
          - Soft Start (0x0C): Booster timing for charge pump

        State handling:
          - If hibernating: Hardware reset first (BUSY undefined in sleep)
          - If already initialized: Skip (idempotent)
        """
        # CRITICAL: Must reset BEFORE waiting if hibernating!
        # The BUSY pin is undefined during deep sleep.
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if self._state & _STATE_INIT_DONE:
            return  # Already initialized

        self._wait()
        self._write(_CMD_SW_RESET)  # Software reset clears registers to POR
        self._wait()

        # Configure gate driver for our panel height
        h = self.HEIGHT - 1
        self._write(_CMD_DRIVER, (h & 0xFF, h >> 8, 0x00))

        # Data entry mode: X increment, Y increment, X first
        self._write(_CMD_DATA_ENTRY, _DATA_ENTRY_INC)

        # Set full RAM window
        self._write(_CMD_RAM_X, (0x00, self.WIDTH // 8 - 1))
        self._write(_CMD_RAM_Y, (0x00, 0x00, h & 0xFF, h >> 8))

        # Border waveform: follow LUT for clean full refresh
        self._write(_CMD_BORDER, _BORDER_FULL)

        # Display Update Control 1: Normal RAM operation
        # A[7:4]=0 Red RAM normal, A[3:0]=0 BW RAM normal
        # B[7]=1 Source S8-S167 (centered, required for GDEY029T94 128px panel)
        self._write(_CMD_UPDATE_1, (0x00, 0x80))

        # Use internal temperature sensor
        self._write(_CMD_TEMP_SENSOR, _TEMP_SENSOR_INTERNAL)

        # Booster soft start: charge pump timing
        # Values from Good Display sample code
        self._write(_CMD_SOFT_START, _SOFT_START_DEFAULT)

        # Initialize RAM address counters to (0,0)
        self._write(_CMD_RAM_X_CNT, 0x00)
        self._write(_CMD_RAM_Y_CNT, (0x00, 0x00))

        self._wait()
        # Mark as initialized, clear partial mode flag (we're in full mode now)
        self._state = (self._state | _STATE_INIT_DONE) & ~_STATE_PARTIAL_MODE

    def _init_partial(self, x=0, y=0, w=None, h=None, force: bool = False):
        """
        Initialize for partial refresh mode (Mode 2).

        Mode 2 uses the RED RAM as the "old" image and BW RAM as "new" image,
        enabling hardware differential updates. The SSD1680 selects different
        LUTs based on whether each pixel is changing:
          - OLD=0,NEW=0: LUT0 (stay black)
          - OLD=0,NEW=1: LUT1 (stay white)
          - OLD=1,NEW=0: LUT2 (change to black)
          - OLD=1,NEW=1: LUT3 (change to white)

        Key differences from _init_full:
          - Uses BORDER_PARTIAL (0x80 = VCOM level) for stable border
          - Minimal init: only HW reset if needed, no SW_RESET (per sample code)

        Optimization: If already in partial mode and not hibernating, skips
        the reset sequence entirely. Use force=True to bypass.

        Args:
            x, y, w, h: Optional region to set as RAM window.
                        x must be 8-pixel aligned. Defaults to full screen.
            force: If True, always perform full reset even if already in partial mode.
        """
        # Fast path: already in partial mode, just update window
        if not force and (self._state & _STATE_PARTIAL_MODE) and not (self._state & _STATE_HIBERNATING):
            self._set_window(x, y, w, h)
            return

        # If coming from full mode (INIT_DONE but not PARTIAL_MODE), we don't
        # need a full reset - just change the border register. This matches
        # Good Display sample code which only does HW reset + border for partial.
        if (self._state & _STATE_INIT_DONE) and not (self._state & _STATE_HIBERNATING):
            # Minimal transition: just set border for partial mode
            self._write(_CMD_BORDER, _BORDER_PARTIAL)
            self._set_window(x, y, w, h)
            self._state |= _STATE_PARTIAL_MODE
            return

        # Full init needed: coming from hibernate or uninitialized state
        # Per Good Display sample: HW reset + border + window (NO SW_RESET!)
        self._reset()
        self._wait()

        # After HW reset, we need to reconfigure essential registers
        gate_count = self.HEIGHT - 1
        self._write(_CMD_DRIVER, (gate_count & 0xFF, gate_count >> 8, 0x00))
        self._write(_CMD_DATA_ENTRY, _DATA_ENTRY_INC)

        # Border at VCOM level for partial (stable border, no artifacts)
        self._write(_CMD_BORDER, _BORDER_PARTIAL)

        # Display Update Control 1: Normal RAM, centered source (S8-S167 for GDEY029T94)
        self._write(_CMD_UPDATE_1, (0x00, 0x80))
        self._write(_CMD_TEMP_SENSOR, _TEMP_SENSOR_INTERNAL)
        self._write(_CMD_SOFT_START, _SOFT_START_DEFAULT)

        # Set RAM window for the region
        self._set_window(x, y, w, h)
        self._state |= _STATE_INIT_DONE | _STATE_PARTIAL_MODE

    def _set_window(self, x=0, y=0, w=None, h=None):
        """
        Set the RAM address window for reading/writing.

        The SSD1680 has separate address settings for:
          - X/Y range: Defines the valid address bounds (0x44/0x45)
          - X/Y counter: Current position for next read/write (0x4E/0x4F)

        After setting, subsequent RAM writes will auto-increment within
        this window according to the Data Entry Mode (0x11).

        Args:
            x: X start position in pixels (must be 8-pixel aligned)
            y: Y start position in pixels
            w: Width in pixels (defaults to full width)
            h: Height in pixels (defaults to full height)
        """
        w = w or self.WIDTH
        h = h or self.HEIGHT
        x_bytes = x >> 3          # X is in bytes (8 pixels per byte)
        x_end = (x + w - 1) >> 3
        y_end = y + h - 1

        # RAM X address range (in bytes, 0-15 for 128px wide)
        self._write(_CMD_RAM_X, (x_bytes, x_end))

        # RAM Y address range (in pixels, 0-295)
        # Format: (Y_START_LOW, Y_START_HIGH, Y_END_LOW, Y_END_HIGH)
        self._write(_CMD_RAM_Y, (y & 0xFF, y >> 8, y_end & 0xFF, y_end >> 8))

        # Set counters to start position
        self._write(_CMD_RAM_X_CNT, x_bytes)
        self._write(_CMD_RAM_Y_CNT, (y & 0xFF, y >> 8))

    def _update(self, mode: int) -> float:
        """
        Execute display update sequence.

        Triggers the Master Activation (0x20) which runs the sequence
        specified in Display Update Control 2 (0x22). The BUSY pin
        goes HIGH during the update.

        The update sequence typically:
          1. Enables clock/analog circuits
          2. Optionally reads temperature
          3. Loads LUT (waveform) from OTP based on temp + mode
          4. Drives display through waveform phases
          5. Optionally powers down analog/oscillator

        Power state tracking:
          - Partial modes (0xFC/0xCC): Keep power on for fast follow-up
          - Full/Fast modes: Power off after (sleep between updates)

        Args:
            mode: Update sequence constant (_UPDATE_FULL, _UPDATE_PARTIAL, etc.)

        Returns:
            float: Time in seconds the BUSY pin was HIGH (refresh duration)
        """
        self._write(_CMD_UPDATE_2, mode)
        self._write(_CMD_ACTIVATE)

        # Use operation-specific timeout based on update mode
        if mode == _UPDATE_PARTIAL:
            timeout = _TIMEOUT_PARTIAL
            op_name = "partial refresh"
        elif mode == _UPDATE_CUSTOM_LUT:
            timeout = _TIMEOUT_FULL  # Custom LUT uses full refresh timing
            op_name = "custom LUT refresh"
        elif mode == _UPDATE_FULL:
            timeout = _TIMEOUT_FULL
            op_name = "full refresh"
        elif mode in (_UPDATE_POWER_ON, _UPDATE_POWER_OFF):
            timeout = _TIMEOUT_POWER
            op_name = "power control"
        else:
            timeout = _TIMEOUT_DEFAULT
            op_name = f"update 0x{mode:02X}"

        t = self._wait(timeout=timeout, operation=op_name)

        # Track power state for optimization
        # Partial modes stay powered for fast consecutive updates
        if mode == _UPDATE_PARTIAL:
            self._state |= _STATE_POWER_ON
        else:
            self._state &= ~_STATE_POWER_ON

        return t

    # =========================================================================
    # Public API
    # =========================================================================

    def init(self, clear: bool = True):
        """
        Initialize the display for use.

        Should be called once after power-on or wake from deep sleep.
        Optionally performs a clearing full refresh.

        Args:
            clear: If True, fills display with white and refreshes.
                   Recommended for first use to establish known state.
        """
        self._init_full()
        if clear:
            self.clear()

    def clear(self, color: int = 0xFF):
        """
        Clear display to a solid color with full refresh.

        Writes the same byte to all of BW and RED RAM, then triggers
        a full update. This establishes the basemap for partial updates.

        Args:
            color: Fill byte. 0xFF=white (all pixels off),
                   0x00=black (all pixels on)
        """
        self._init_full()
        data = bytes([color]) * self.BUFFER_SIZE

        # Write to both RAMs (RED=previous, BW=current, both same = no change)
        self._write(_CMD_RAM_BLACK, data)
        self._write(_CMD_RAM_RED, data)
        self._update(_UPDATE_FULL)

        # Basemap established - partials now allowed
        self._state |= _STATE_BASEMAP
        if self._prev_buffer:
            self._prev_buffer[:] = data

        self.sleep()

    def display(self, data: bytes, full: bool = True,
                force_full: bool = False, lut: bytes|None = None,
                stay_awake: bool = False) -> float:
        """
        Display an image buffer.

        Main entry point for showing images. Delegates to _display_full
        or _display_partial based on parameters.

        Args:
            data: Image buffer (4736 bytes, 1 bit per pixel, 1=white 0=black)
            full: If True, use full refresh (Mode 1). If False, partial (Mode 2).
            force_full: If True with full=False, force full refresh this time.
                        Useful to periodically clear ghosting.
            lut: Custom LUT bytes to use instead of OTP waveform.
                 For special effects or 4-gray mode.
            stay_awake: If True, keep display powered after update instead of
                        entering deep sleep. Saves ~40ms wake time on next update.
                        WARNING: Significantly increases power draw (mA vs µA) as
                        the booster, regulator, and oscillator remain active.
                        Only use for rapid consecutive updates, then call sleep()
                        when done. For battery-powered devices like MagTag, always
                        sleep between infrequent updates.

        Returns:
            float: Refresh time in seconds
        """
        if full:
            return self._display_full(data, lut, stay_awake)
        else:
            return self._display_partial(data, force_full, lut, stay_awake)

    def _display_full(self, data: bytes, lut: bytes|None = None,
                      stay_awake: bool = False) -> float:
        """
        Full refresh display update (Mode 1).

        Drives all pixels through complete waveform regardless of current
        state. Eliminates ghosting but takes longer (~1.4s).

        After completion:
          - Basemap flag set (partials now allowed)
          - Partial count reset to 0
          - Previous buffer updated with current data
          - Display put to sleep unless stay_awake=True

        Args:
            data: Image buffer (4736 bytes)
            lut: Custom LUT for special display modes (4-gray, custom waveforms)
            stay_awake: If True, skip sleep() after update. Keeps display
                        powered for faster follow-up operations.

        Returns:
            float: Refresh time in seconds
        """
        self._init_full()

        # Load custom LUT if provided
        if lut is not None:
            self._write(_CMD_LUT, lut)

        # Write image to both RAM planes
        # For full refresh, both planes get same data (no differential)
        self._write(_CMD_RAM_BLACK, data)
        self._write(_CMD_RAM_RED, data)

        # Select update mode
        # Custom LUT needs _UPDATE_CUSTOM_LUT (0xC7) to skip OTP reload
        mode = _UPDATE_CUSTOM_LUT if lut is not None else _UPDATE_FULL
        t = self._update(mode)

        # Update state: basemap established, initial refresh done
        self._state = (self._state | _STATE_BASEMAP) & ~_STATE_INITIAL
        self._partial_count = 0

        # Sync differential buffer for next partial update
        if self._prev_buffer:
            self._prev_buffer[:] = data

        if not stay_awake:
            self.sleep()
        return t

    def _display_partial(self, data: bytes, force_full: bool = False,
                         lut: bytes|None = None, stay_awake: bool = True) -> float:
        """
        Partial refresh display update (Mode 2).

        Uses differential update: OLD image in RED RAM, NEW in BW RAM.
        The SSD1680 applies different waveforms to changing vs unchanged
        pixels, resulting in:
          - Faster refresh (~0.3s vs 1.5s)
          - Less flashing (unchanged pixels don't flash)
          - Some ghosting (accumulates over many partials)

        Requirements:
          - Basemap must be established (full refresh done first)
          - Differential buffer should be enabled for best quality

        Auto-full logic:
          - First refresh: Must be full
          - No basemap: Must be full
          - force_full=True: Force full this time
          - partial_threshold reached: Auto full refresh

        Args:
            data: Image buffer (4736 bytes)
            force_full: Force full refresh instead of partial
            lut: Custom LUT for partial update (advanced use)
            stay_awake: If True (default), keep display powered after update
                        for fast consecutive partials. If False, sleep after.

        Returns:
            float: Refresh time in seconds
        """
        # Check if we need a full refresh instead
        needs_full = (self._state & (_STATE_INITIAL | _STATE_BASEMAP)) != _STATE_BASEMAP
        threshold_hit = (
            self._partial_threshold > 0 and
            self._partial_count >= self._partial_threshold
        )

        if needs_full or force_full or threshold_hit:
            # Full refresh clears ghosting; next partial will re-init for partial mode
            return self._display_full(data, lut=lut, stay_awake=stay_awake)

        # Need partial init if hibernating or not in partial mode
        # After a full refresh, INIT_DONE is set but PARTIAL_MODE is not,
        # so we must re-init to set partial-specific registers (border, etc.)
        if (self._state & _STATE_HIBERNATING) or not (self._state & _STATE_PARTIAL_MODE):
            self._init_partial()

        # Set full screen window (we're updating entire buffer)
        self._set_window(0, 0, self.WIDTH, self.HEIGHT)

        # Load custom LUT if provided
        if lut is not None:
            self._write(_CMD_LUT, lut)

        # Write OLD image to RED RAM for differential comparison
        # This is the key to hardware-accelerated partial updates
        if self._prev_buffer:
            self._write(_CMD_RAM_RED, self._prev_buffer)

        # Write NEW image to BW RAM
        self._write(_CMD_RAM_BLACK, data)

        # Use partial mode (stays powered for fast consecutive updates)
        # Custom LUT requires _UPDATE_CUSTOM_LUT to skip OTP reload
        mode = _UPDATE_CUSTOM_LUT if lut else _UPDATE_PARTIAL
        t = self._update(mode)

        # Update differential buffer for next partial
        if self._prev_buffer:
            self._prev_buffer[:] = data

        self._partial_count += 1

        if not stay_awake:
            self.sleep()

        gc.collect()
        return t

    def display_gray(self, black_plane: bytes, red_plane: bytes) -> float:
        """
        Display a 4-level grayscale image.

        Uses the LUT_4GRAY waveform which interprets the two RAM planes
        as 2-bit gray values:
          - RED=0, BW=0: Black
          - RED=0, BW=1: Dark Gray
          - RED=1, BW=0: Light Gray
          - RED=1, BW=1: White

        The black_plane and red_plane should be generated by splitting
        a 2-bit buffer with FrameBuffer.to_planes().

        Args:
            black_plane: Data for BW RAM (4736 bytes)
            red_plane: Data for RED RAM (4736 bytes)

        Returns:
            float: Refresh time in seconds
        """
        return self.display_lut(LUT_4GRAY, black_plane, red_plane)

    def display_lut(self, lut: bytes, black: bytes, red: bytes|None = None,
                    mode: int = _UPDATE_CUSTOM_LUT, vgh: int = _DEFAULT_VGH,
                    vsh1: int = _DEFAULT_VSH1, vsh2: int = _DEFAULT_VSH2,
                    vsl: int = _DEFAULT_VSL, vcom: int = _DEFAULT_VCOM) -> float:
        """
        Display with a custom Look-Up Table (waveform).

        The LUT defines the voltage sequence applied to each pixel
        during refresh. Custom LUTs enable:
          - Grayscale modes (4-gray, 16-gray with dithering)
          - Faster refresh (shorter waveforms)
          - Special effects (fade, animation)

        LUT format (Command 0x32 writes 153 bytes):
          - Bytes 0-59: VS (voltage source) for 5 LUTs × 12 groups
          - Bytes 60-143: TP/SR/RP timing (12 groups × 7 bytes)
          - Bytes 144-149: FR frame rate (6 bytes, 2 groups per byte)
          - Bytes 150-152: XON gate scan selection (3 bytes)

        Voltage registers are also configured to ensure consistent behavior
        with custom LUTs (OTP waveforms include their own voltage settings,
        but custom LUTs need explicit configuration).

        After custom LUT display, basemap is cleared (need full refresh
        before partial updates work correctly).

        Args:
            lut: LUT data (153 bytes)
            black: Data for BW RAM (4736 bytes)
            red: Data for RED RAM (defaults to black if None)
            mode: Update mode (default _UPDATE_CUSTOM_LUT to use the custom LUT)
            vgh: Gate high voltage (default _DEFAULT_VGH = 0x17 = 20V)
            vsh1: Source high voltage 1 (default _DEFAULT_VSH1 = 0x41 = +15V)
            vsh2: Source high voltage 2 (default _DEFAULT_VSH2 = 0xA8 = +5V)
            vsl: Source low voltage (default _DEFAULT_VSL = 0x32 = -15V)
            vcom: VCOM DC level (default _DEFAULT_VCOM = 0x50 = -2V)

        Returns:
            float: Refresh time in seconds
        """
        self._init_full()
        self.set_waveform(lut, vgh, vsh1, vsh2, vsl, vcom)
        self._write(_CMD_RAM_BLACK, black)
        self._write(_CMD_RAM_RED, red if red else black)

        t = self._update(mode)
        # Custom LUT invalidates basemap (partial LUT won't work right)
        self._state &= ~_STATE_BASEMAP
        gc.collect()
        return t

    def set_waveform(self, lut: bytes, vgh: int = _DEFAULT_VGH,
                     vsh1: int = _DEFAULT_VSH1, vsh2: int = _DEFAULT_VSH2,
                     vsl: int = _DEFAULT_VSL, vcom: int = _DEFAULT_VCOM):
        """
        Set complete waveform including voltage levels.

        The SSD1680 waveform consists of 159 bytes total:
          - 153 bytes via LUT register (0x32): VS, timing, FR, XON
          - 1 byte via Gate Voltage (0x03): VGH
          - 3 bytes via Source Voltage (0x04): VSH1, VSH2, VSL
          - 1 byte via VCOM (0x2C): VCOM DC level

        This method writes all components for a complete waveform setup.
        Use this when you need precise control over driving voltages,
        such as for custom grayscale modes or optimized refresh.

        Args:
            lut: LUT data (153 bytes from command 0x32)
            vgh: Gate high voltage (default 0x17 = 20V)
                 See datasheet Table for 0x03 values.
            vsh1: Source high voltage 1 (default 0x41 = 15V)
            vsh2: Source high voltage 2 (default 0xA8 = 5V)
            vsl: Source low voltage (default 0x32 = -15V)
            vcom: VCOM DC level (default 0x50 = -2V)
                  See datasheet Table for 0x2C values.

        Example:
            # Set custom 4-gray waveform with adjusted voltages
            epd.set_waveform(LUT_4GRAY, vsh1=0x3C, vsl=0x28, vcom=0x44)
        """
        self._write(_CMD_LUT, lut[:153])
        self._write(_CMD_VGH, vgh)
        self._write(_CMD_VSH_VSL, (vsh1, vsh2, vsl))
        self._write(_CMD_VCOM, vcom)

    def display_region(self, data: bytes, x: int, y: int, w: int, h: int) -> float:
        """
        Update only a rectangular region of the display.

        More efficient than full-buffer partial when updating small areas
        (icons, counters, status indicators).

        Constraints:
          - x and w must be multiples of 8 (byte-aligned)
          - Basemap must be established first

        Args:
            data: Region buffer (w/8 * h bytes)
            x: X position (must be 8-pixel aligned)
            y: Y position
            w: Width (must be 8-pixel aligned)
            h: Height

        Returns:
            float: Refresh time in seconds
        """
        return self.display_regions([(data, x, y, w, h)])

    def display_regions(self, regions: list) -> float:
        """
        Update multiple rectangular regions with a single refresh.

        Batches several region updates into one display refresh, saving
        the ~300ms refresh time per region.

        Each region is written to both RAM planes:
          - RED RAM: Old data (from _prev_buffer) for differential
          - BW RAM: New data

        Constraints:
          - All regions must be 8-pixel aligned (x and w)
          - Basemap must be established first

        Args:
            regions: List of (data, x, y, w, h) tuples

        Returns:
            float: Refresh time in seconds

        Raises:
            RuntimeError: If basemap not established
            ValueError: If region coordinates not 8-pixel aligned
        """
        if not (self._state & _STATE_BASEMAP):
            raise RuntimeError("Must call display() with full=True first")
        if not regions:
            return 0.0

        # Need partial init if hibernating or not in partial mode
        if (self._state & _STATE_HIBERNATING) or not (self._state & _STATE_PARTIAL_MODE):
            self._init_partial(regions[0][1], regions[0][2], regions[0][3], regions[0][4])

        stride = self.WIDTH // 8  # Bytes per row in full buffer

        for i, (data, x, y, w, h) in enumerate(regions):
            # Validate 8-pixel alignment
            if x & 7 or w & 7:
                raise ValueError(f"Region {i}: x and w must be multiples of 8")

            # Set RAM window for this region
            self._set_window(x, y, w, h)

            # Differential update: write OLD data to RED RAM
            if self._prev_buffer:
                x_byte = x // 8
                w_byte = w // 8
                old_data = bytearray(w_byte * h)

                # Extract old region from previous buffer
                for row in range(h):
                    src_idx = (y + row) * stride + x_byte
                    dst_idx = row * w_byte
                    old_data[dst_idx : dst_idx + w_byte] = self._prev_buffer[src_idx : src_idx + w_byte]

                self._write(_CMD_RAM_RED, old_data)

                # Update previous buffer with new region data
                for row in range(h):
                    dst_idx = (y + row) * stride + x_byte
                    src_idx = row * w_byte
                    self._prev_buffer[dst_idx : dst_idx + w_byte] = data[src_idx : src_idx + w_byte]

            # Always reset address counters before writing BW RAM
            # This ensures correct positioning even if RED RAM write advanced
            # the counters, or if prev_buffer is None
            self._write(_CMD_RAM_X_CNT, x >> 3)
            self._write(_CMD_RAM_Y_CNT, (y & 0xFF, y >> 8))

            # Write new region data to BW RAM
            self._write(_CMD_RAM_BLACK, data)

        # Single refresh for all regions
        t = self._update(_UPDATE_PARTIAL)
        self._partial_count += 1
        gc.collect()
        return t

    # =========================================================================
    # Temperature & Diagnostics
    # =========================================================================

    @property
    def has_temperature_sensor(self) -> bool:
        """
        Check if temperature reading is available.

        Returns True if MISO pin is connected (required for SPI reads).
        The MagTag does not have MISO connected to the EPD.
        """
        return self._has_miso

    def read_temperature(self) -> float:
        """
        Read temperature from the internal sensor.

        The SSD1680 has a built-in temperature sensor with ±2°C accuracy
        from -25°C to 50°C. The display must be awake to read temperature.

        The GDEY029T94 panel has a narrower operating range (0-50°C) than
        the IC (-40 to +85°C). This method returns the raw reading but
        check_temperature() can validate against panel limits.

        Temperature format (12-bit binary):
          - Bit 11 = 0: Positive, value = raw / 16
          - Bit 11 = 1: Negative, value = -(2's complement) / 16

        Returns:
            float: Temperature in degrees Celsius

        Example:
            >>> epd.init(clear=False)
            >>> temp = epd.read_temperature()
            >>> print(f"Panel temp: {temp:.1f}°C")

        Raises:
            RuntimeError: If MISO pin is not available (hardware limitation).
        """
        if not self._has_miso:
            raise RuntimeError(
                "Temperature reading requires MISO pin. "
                "MagTag EPD does not have MISO connected."
            )

        # Ensure display is awake and initialized
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if not (self._state & _STATE_INIT_DONE):
            self._init_full()

        # Enable internal temperature sensor
        self._write(_CMD_TEMP_SENSOR, _TEMP_SENSOR_INTERNAL)

        # Trigger temperature read sequence
        self._write(_CMD_UPDATE_2, _UPDATE_LOAD_TEMP)
        self._write(_CMD_ACTIVATE)
        self._wait()

        # Read 2 bytes from temperature register
        # Format: [A11-A4], [A3-A0, 0, 0, 0, 0]
        data = self._read(_CMD_TEMP_READ, 2)
        raw = (data[0] << 4) | (data[1] >> 4)

        # Convert 12-bit value to temperature
        if raw & 0x800:  # Negative (bit 11 set)
            raw = raw - 0x1000  # 2's complement
        return raw / 16.0

    def check_temperature(self) -> tuple[float, bool]:
        """
        Read temperature and check if within panel operating range.

        The GDEY029T94 panel operates safely between 0°C and 50°C.
        Outside this range, display quality may degrade or damage may occur.

        Returns:
            tuple: (temperature_celsius, is_within_range)

        Raises:
            RuntimeError: If MISO pin is not available (hardware limitation).

        Example:
            >>> if epd.has_temperature_sensor:
            ...     temp, ok = epd.check_temperature()
            ...     if not ok:
            ...         print(f"WARNING: {temp}°C outside 0-50°C range!")
        """
        temp = self.read_temperature()
        in_range = _TEMP_MIN <= temp <= _TEMP_MAX
        return temp, in_range

    def set_invert(self, invert_bw: bool = False, invert_red: bool = False):
        """
        Enable or disable hardware display inversion.

        This uses the Display Update Control 1 register (0x21) to invert
        RAM content during display output - no buffer modification needed.
        Useful for:
          - Dark mode / night mode toggle
          - Selection highlighting
          - Visual effects

        The inversion is applied during the next display update and
        persists until changed.

        Note: The display must be awake (not in deep sleep) to set this
        register. This method will wake the display if needed.

        Args:
            invert_bw: If True, invert BW RAM (black <-> white)
            invert_red: If True, invert RED RAM (for differential modes)

        Example:
            >>> epd.set_invert(invert_bw=True)  # Enable dark mode
            >>> epd.display(buffer, full=False)
            >>> epd.set_invert(invert_bw=False)  # Back to normal
        """
        # Ensure display is awake - BUSY pin is undefined in deep sleep
        if self._state & _STATE_HIBERNATING:
            self._reset()
            self._wait()  # Wait for busy to stabilize after wake

        # A[7:4]: Red RAM option (0x00=normal, 0x80=inverse)
        # A[3:0]: BW RAM option (0x00=normal, 0x08=inverse)
        # B[7]: Source output mode (1=S8-S167, required for GDEY029T94)
        a = (0x80 if invert_red else 0x00) | (0x08 if invert_bw else 0x00)
        self._write(_CMD_UPDATE_1, (a, 0x80))

    def read_status(self) -> dict:
        """
        Read status bits from the SSD1680.

        Returns diagnostic information including:
          - HV Ready: Whether high voltage circuits are ready
          - VCI OK: Whether supply voltage is above threshold
          - Busy: Current busy state
          - Chip ID: Should be 0x01 for SSD1680

        Note: HV Ready and VCI flags require running detection commands
        (0x14, 0x15) first to be valid. This method runs them automatically.

        Returns:
            dict: Status information
                {
                    'hv_ready': bool,    # True if HV circuits ready
                    'vci_ok': bool,      # True if VCI voltage normal
                    'busy': bool,        # True if currently busy
                    'chip_id': int,      # Chip ID (0x01 for SSD1680)
                    'raw': int           # Raw status byte
                }

        Example:
            >>> status = epd.read_status()
            >>> if not status['vci_ok']:
            ...     print("WARNING: Low voltage detected!")
        """
        # Ensure display is awake
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if not (self._state & _STATE_INIT_DONE):
            self._init_full()

        # Power on analog circuits for detection
        self.power_on()

        # Run HV Ready detection (0x14)
        # A[6:4]=0 for 10ms cool down, A[2:0]=0 for 1-shot detection
        self._write(_CMD_HV_READY, 0x00)
        self._wait()

        # Run VCI detection (0x15)
        # A[2:0]=4 for 2.3V threshold (default)
        self._write(_CMD_VCI_DETECT, 0x04)
        self._wait()

        # Read status register
        data = self._read(_CMD_STATUS, 1)
        raw = data[0]

        return {
            'hv_ready': not bool(raw & 0x20),  # Bit 5: 0=ready, 1=not ready
            'vci_ok': not bool(raw & 0x10),    # Bit 4: 0=normal, 1=low
            'busy': bool(raw & 0x04),          # Bit 2: busy flag
            'chip_id': raw & 0x03,             # Bits 1:0: chip ID
            'raw': raw
        }

    def calculate_crc(self) -> int:
        """
        Calculate CRC of display RAM contents.

        The SSD1680 computes a 16-bit CRC over the current RAM contents.
        This can be used to verify RAM integrity or detect if the display
        content has changed.

        Use cases:
          - Verify RAM write completed correctly
          - Detect display corruption
          - Check if content needs update (compare CRCs)

        The CRC covers the full RAM window as defined by registers 0x44/0x45.

        Returns:
            int: 16-bit CRC value

        Example:
            >>> epd.display(buffer, full=True)
            >>> crc1 = epd.calculate_crc()
            >>> # Later...
            >>> crc2 = epd.calculate_crc()
            >>> if crc1 != crc2:
            ...     print("Display content changed!")
        """
        # Ensure display is awake
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if not (self._state & _STATE_INIT_DONE):
            self._init_full()

        # Trigger CRC calculation (BUSY goes high during compute)
        self._write(_CMD_CRC_CALC)
        self._wait()

        # Read 16-bit CRC result
        data = self._read(_CMD_CRC_STATUS, 2)
        return (data[0] << 8) | data[1]

    def read_ram(self, x: int = 0, y: int = 0, length: int = 1,
                 red_ram: bool = False) -> bytes:
        """
        Read display RAM contents.

        Reads back pixel data from the display RAM. Useful for:
          - Verifying RAM writes
          - Implementing read-modify-write operations
          - Debugging display issues

        Note: The first byte read is dummy data (SPI protocol).
        This method handles that automatically.

        Args:
            x: X start position in pixels (8-pixel aligned)
            y: Y start position in pixels
            length: Number of bytes to read
            red_ram: If True, read RED RAM (0x26). If False, read BW RAM (0x24).

        Returns:
            bytes: RAM data read

        Example:
            >>> # Read first 16 bytes of BW RAM
            >>> data = epd.read_ram(x=0, y=0, length=16)
            >>> print(data.hex())
        """
        # Ensure display is awake
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if not (self._state & _STATE_INIT_DONE):
            self._init_full()

        # Select which RAM to read (0=BW/0x24, 1=RED/0x26)
        self._write(_CMD_RAM_READ_OPT, 0x01 if red_ram else 0x00)

        # Set address counters
        self._write(_CMD_RAM_X_CNT, x >> 3)
        self._write(_CMD_RAM_Y_CNT, (y & 0xFF, y >> 8))

        # Read RAM (first byte is dummy)
        return self._read(_CMD_RAM_READ, length)

    def read_otp_info(self) -> dict:
        """
        Read OTP (One-Time Programmable) information.

        Returns factory-programmed information from the SSD1680 OTP memory:
          - VCOM setting from OTP
          - Display mode configuration
          - Waveform version (4 bytes)
          - User ID (10 bytes)

        Useful for:
          - Identifying display/driver versions
          - Debugging waveform issues
          - Panel identification in multi-display systems

        Returns:
            dict: OTP information
                {
                    'vcom_otp_sel': int,      # VCOM OTP selection byte
                    'vcom_register': int,     # VCOM register value
                    'display_mode': bytes,    # 5-byte display mode config
                    'waveform_version': bytes,# 4-byte waveform version
                    'user_id': bytes          # 10-byte user ID
                }

        Example:
            >>> info = epd.read_otp_info()
            >>> print(f"Waveform: {info['waveform_version'].hex()}")
            >>> print(f"User ID: {info['user_id'].hex()}")
        """
        # Ensure display is awake
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if not (self._state & _STATE_INIT_DONE):
            self._init_full()

        # Read Display Option (11 bytes: VCOM sel, VCOM reg, 5 display, 4 waveform)
        display_data = self._read(_CMD_OTP_DISPLAY, 11)

        # Read User ID (10 bytes)
        user_id = self._read(_CMD_OTP_USER_ID, 10)

        return {
            'vcom_otp_sel': display_data[0],
            'vcom_register': display_data[1],
            'display_mode': bytes(display_data[2:7]),
            'waveform_version': bytes(display_data[7:11]),
            'user_id': bytes(user_id)
        }

    # =========================================================================
    # Hardware Acceleration
    # =========================================================================

    def set_gate_start(self, position: int):
        """
        Set gate scan start position for hardware scrolling/offset.

        This command offsets where the display starts reading from RAM,
        enabling hardware-accelerated vertical scrolling without rewriting
        the RAM contents. The display wraps around at the end.

        Use cases:
          - Smooth vertical scrolling (terminal, log viewer)
          - Status bar that stays fixed while content scrolls
          - Efficient "page flip" between pre-rendered screens

        The effect is immediate on the next display refresh.

        Args:
            position: Gate start position (0-295 for 296-line display).
                      Content at RAM row 0 will appear at gate 'position'.

        Example:
            >>> # Scroll display down by 50 pixels (content moves up)
            >>> epd.set_gate_start(50)
            >>> epd.display(buffer, full=False)

        Note:
            This is a display offset, not a RAM offset. Writing to RAM
            row 0 will display at gate 'position'. To implement smooth
            scrolling, you would increment this value over time.
        """
        # 9-bit value: lower 8 bits in first byte, bit 8 in second byte
        self._write(_CMD_GATE_SCAN_START, (position & 0xFF, (position >> 8) & 0x01))

    def auto_fill(self, pattern: int = 0xFF, red_ram: bool = True,
                  bw_ram: bool = True) -> float:
        """
        Hardware-accelerated solid fill of display RAM.

        Uses the SSD1680's auto-write feature to fill RAM with a solid color
        without sending 4736 bytes over SPI. Significantly faster for clears.

        Supported patterns:
          - 0x00: All black (all pixels on)
          - 0xFF: All white (all pixels off)

        LIMITATION: This implementation uses maximum step sizes (296x176) which
        fills the entire screen with a single value (bit 7 of pattern). This
        means only solid fills are supported. True checkerboard patterns would
        require smaller step sizes (e.g., 8x8) and alternating first-step values,
        which is not currently implemented.

        The SSD1680 auto-write command (0x46/0x47) uses:
          - A[7]: First step value (0 or 1)
          - A[6:4]: Step height (110b = 296 pixels = full screen)
          - A[2:0]: Step width (101b = 176 pixels = full screen)

        Args:
            pattern: Fill value. Only bit 7 is used:
                     0x00-0x7F = black (bit 7 = 0)
                     0x80-0xFF = white (bit 7 = 1)
            red_ram: If True, fill RED RAM (for differential refresh)
            bw_ram: If True, fill BW RAM (main image)

        Returns:
            float: Time spent waiting for fill operation

        Example:
            >>> # Fast clear to white (instead of sending 4736 bytes)
            >>> epd.auto_fill(0xFF)

            >>> # Fast clear to black
            >>> epd.auto_fill(0x00)
        """
        # Ensure display is awake
        if self._state & _STATE_HIBERNATING:
            self._reset()
        if not (self._state & _STATE_INIT_DONE):
            self._init_full()

        # Build parameter byte:
        # A[7]: First step value (0 or 1 = pattern[7] effectively)
        # A[6:4]: Step Height (110 = 296 for full height)
        # A[2:0]: Step Width (101 = 176 for full width)
        # With max step sizes, entire RAM gets first step value

        # For solid fill, we want all pixels the same value.
        # A[7] = bit 7 of pattern (0 for 0x00/0x55, 1 for 0xFF/0xAA)
        first_bit = (pattern >> 7) & 0x01
        # Height=296 (110b), Width=176 (101b) = full screen single step
        param = (first_bit << 7) | (0b110 << 4) | (0b101)

        t = 0.0
        if red_ram:
            self._write(_CMD_AUTO_WRITE_RED, param)
            t += self._wait()

        if bw_ram:
            self._write(_CMD_AUTO_WRITE_BW, param)
            t += self._wait()

        return t

    def set_source_centered(self, centered: bool = False):
        """
        Set source output range for display centering.

        The SSD1680 has 176 source outputs (S0-S175), but smaller panels
        may only use a subset. This command switches between:
          - Full range: S0-S175 (default)
          - Centered: S8-S167 (160 sources, centered in panel)

        For the GDEY029T94 (128 pixels wide = 128/8 = 16 bytes), this
        has no effect since we use even fewer sources. However, it may
        be useful for other panel configurations.

        Args:
            centered: If True, use S8-S167. If False, use S0-S175.

        Note:
            This modifies the Display Update Control 1 register (0x21)
            byte B[7]. Other bits in this register control RAM inversion
            (set via set_invert method).
        """
        # Read current inversion state (we don't want to lose it)
        # Since we can't read this register, we'll set byte B only
        # A byte is set by set_invert, B[7] controls source range
        # B[7]=1: S8-S167 (centered, correct for GDEY029T94 128px panel)
        # B[7]=0: S0-S175 (full 176 sources, causes offset on 128px panels)
        b = 0x80 if centered else 0x00
        # Note: This overwrites any inversion setting. User should call
        # set_invert after this if they need inversion.
        self._write(_CMD_UPDATE_1, (0x00, b))

    def fast_clear(self, color: int = 0xFF):
        """
        Fast display clear using hardware auto-fill.

        Combines auto_fill and display refresh for a quick clear operation.
        Faster than sending 4736 bytes over SPI for each RAM plane.

        Args:
            color: Clear color (0xFF=white, 0x00=black)

        Example:
            >>> epd.fast_clear()  # Quick white clear
            >>> epd.fast_clear(0x00)  # Quick black clear
        """
        self._init_full()
        self.auto_fill(color, red_ram=True, bw_ram=True)
        self._update(_UPDATE_FULL)
        self._state |= _STATE_BASEMAP
        self._partial_count = 0
        if self._prev_buffer:
            self._prev_buffer[:] = bytes([color]) * len(self._prev_buffer)
        self.sleep()

    # =========================================================================
    # Power Management
    # =========================================================================

    def power_on(self):
        """
        Power on the analog circuits.

        Turns on booster, regulator and oscillator. Required before
        display updates if previously powered off.

        In normal operation, _update() handles power automatically.
        Use this for manual power control or diagnostics.

        No-op if already powered or hibernating (need reset instead).
        """
        if self._state & _STATE_HIBERNATING:
            return  # Must use init() to wake from hibernate
        if not (self._state & _STATE_POWER_ON):
            self._write(_CMD_UPDATE_2, _UPDATE_POWER_ON)
            self._write(_CMD_ACTIVATE)
            self._wait()
            self._state |= _STATE_POWER_ON

    def power_off(self):
        """
        Power off the analog circuits.

        Disables booster, regulator and oscillator to save power.
        RAM is retained. Faster to resume than deep sleep.

        Called automatically after full refresh. For partial refresh,
        power is kept on for fast consecutive updates.

        No-op if already off or hibernating.
        """
        if self._state & _STATE_HIBERNATING:
            return  # Already off
        if self._state & _STATE_POWER_ON:
            self._write(_CMD_UPDATE_2, _UPDATE_POWER_OFF)
            self._write(_CMD_ACTIVATE)
            self._wait()
            self._state &= ~_STATE_POWER_ON

    def sleep(self, retain_ram: bool = True):
        """
        Enter deep sleep mode (hibernate).

        Minimum power consumption (~0.5µA). Display image is retained
        on the panel (e-paper is bistable).

        Deep Sleep modes:
          - Mode 1 (_SLEEP_MODE_1 = 0x01): RAM retained, faster wake
          - Mode 2 (_SLEEP_MODE_2 = 0x03): RAM lost, lowest power

        After sleep, a hardware reset (toggle RES# pin) is required
        to wake the display. The BUSY pin is undefined during sleep.

        Args:
            retain_ram: If True, use Mode 1 (RAM kept). If False, Mode 2.

        Note:
            If retain_ram=False, basemap flag is cleared (need full
            refresh before partials work).

        Datasheet Reference (Command 0x10):
            A[1:0] = 00: Normal Mode
            A[1:0] = 01: Deep Sleep Mode 1 (RAM retained)
            A[1:0] = 11: Deep Sleep Mode 2 (RAM lost)
        """
        if self._state & _STATE_HIBERNATING:
            return  # Already sleeping
        self.power_off()
        self._write(_CMD_SLEEP, _SLEEP_MODE_1 if retain_ram else _SLEEP_MODE_2)
        time.sleep(0.001)  # 1ms stabilization (command executes immediately)
        # Update state: hibernating, power off, not initialized
        self._state = (self._state | _STATE_HIBERNATING) & ~(_STATE_POWER_ON | _STATE_INIT_DONE)
        if not retain_ram:
            self._state &= ~_STATE_BASEMAP

    @property
    def is_awake(self) -> bool:
        """Check if display is powered (not in deep sleep)."""
        return bool(self._state & _STATE_POWER_ON)

    @property
    def is_hibernating(self) -> bool:
        """Check if display is in deep sleep mode."""
        return bool(self._state & _STATE_HIBERNATING)

    @property
    def partial_count(self) -> int:
        """Number of partial refreshes since last full refresh."""
        return self._partial_count

    @partial_count.setter
    def partial_count(self, value: int):
        """Reset or adjust partial refresh counter."""
        self._partial_count = value

    @property
    def partial_threshold(self) -> int:
        """Number of partials before auto-full refresh (0 = disabled)."""
        return self._partial_threshold

    @partial_threshold.setter
    def partial_threshold(self, value: int):
        """Set auto-full refresh threshold. 0 disables auto-full."""
        self._partial_threshold = value
