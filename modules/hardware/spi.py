"""
SPIDevice - Low-Level SPI Communication for EPD Controllers
============================================================
Handles all direct hardware interaction: SPI bus, GPIO pins, timing.

This class encapsulates:
- SPI bus configuration and transactions
- GPIO pin management (CS, DC, RST, BUSY)
- Hardware reset sequences
- Busy-wait polling with timeout

Separating this from the display driver allows:
- Easier testing (mock the SPIDevice)
- Cleaner driver code (focus on display logic)
- Potential reuse for other SPI devices
"""
import time

try:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from digitalio import DigitalInOut
        from busio import SPI
except ImportError:
    pass


class SPIDevice:
    """
    Low-level SPI communication handler for EPD controllers.

    Manages the SPI bus and control pins (CS, DC, RST, BUSY) for
    e-paper display communication. Provides methods for sending
    commands/data and waiting for the display to become ready.

    Attributes:
        DEFAULT_WRITE_BAUDRATE: SPI speed for write operations (20MHz)
        DEFAULT_READ_BAUDRATE: SPI speed for read operations (2.5MHz)
        DEFAULT_TIMEOUT: Default busy-wait timeout in seconds
    """
    DEFAULT_WRITE_BAUDRATE = 20_000_000
    DEFAULT_READ_BAUDRATE = 2_500_000
    DEFAULT_TIMEOUT = 10.0

    def __init__(
        self,
        spi: "SPI",
        cs: "DigitalInOut",
        dc: "DigitalInOut",
        rst: "DigitalInOut",
        busy: "DigitalInOut",
        write_baudrate: int = DEFAULT_WRITE_BAUDRATE,
        read_baudrate: int = DEFAULT_READ_BAUDRATE,
    ):
        """
        Initialize the SPI device.

        Args:
            spi: Configured SPI bus instance
            cs: Chip Select pin (active low)
            dc: Data/Command pin (low=command, high=data)
            rst: Reset pin (active low)
            busy: Busy status pin (high when busy)
            write_baudrate: SPI clock speed for writes
            read_baudrate: SPI clock speed for reads (slower per datasheet)
        """
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.busy = busy
        self._write_baudrate = write_baudrate
        self._read_baudrate = read_baudrate

        # Pre-allocated buffers to avoid repeated allocations
        self._cmd_buf = bytearray(1)
        self._data_buf = bytearray(4)

    @classmethod
    def from_board(
        cls,
        sck_pin=None,
        mosi_pin=None,
        miso_pin=None,
        cs_pin=None,
        dc_pin=None,
        rst_pin=None,
        busy_pin=None,
    ) -> "SPIDevice":
        """
        Create SPIDevice using board pin definitions.

        Convenience factory that initializes all hardware from board module.
        Uses MagTag EPD pins by default if not specified.

        Args:
            sck_pin: SPI clock pin (default: board.EPD_SCK)
            mosi_pin: SPI MOSI pin (default: board.EPD_MOSI)
            miso_pin: SPI MISO pin (default: board.EPD_MISO if available)
            cs_pin: Chip select pin (default: board.EPD_CS)
            dc_pin: Data/command pin (default: board.EPD_DC)
            rst_pin: Reset pin (default: board.EPD_RESET)
            busy_pin: Busy pin (default: board.EPD_BUSY)

        Returns:
            Configured SPIDevice instance
        """
        import board
        import busio
        import digitalio

        # Use board defaults for MagTag
        sck_pin = sck_pin or board.EPD_SCK
        mosi_pin = mosi_pin or board.EPD_MOSI
        miso_pin = miso_pin or getattr(board, 'EPD_MISO', None)
        cs_pin = cs_pin or board.EPD_CS
        dc_pin = dc_pin or board.EPD_DC
        rst_pin = rst_pin or board.EPD_RESET
        busy_pin = busy_pin or board.EPD_BUSY

        # Initialize SPI bus
        spi = busio.SPI(sck_pin, mosi_pin, miso_pin)
        start = time.monotonic()
        while not spi.try_lock():
            if time.monotonic() - start > 1.0:
                raise RuntimeError("SPI lock timeout during initialization")
        spi.configure(baudrate=cls.DEFAULT_WRITE_BAUDRATE, phase=0, polarity=0)
        spi.unlock()

        # Initialize GPIO pins
        cs = digitalio.DigitalInOut(cs_pin)
        cs.direction = digitalio.Direction.OUTPUT
        cs.value = True  # Deselected (active low)

        dc = digitalio.DigitalInOut(dc_pin)
        dc.direction = digitalio.Direction.OUTPUT
        dc.value = True  # Default to data mode

        rst = digitalio.DigitalInOut(rst_pin)
        rst.direction = digitalio.Direction.OUTPUT
        rst.value = True  # Not in reset

        busy = digitalio.DigitalInOut(busy_pin)
        busy.direction = digitalio.Direction.INPUT

        return cls(spi, cs, dc, rst, busy)

    def deinit(self):
        """Release all hardware resources."""
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

    @property
    def has_miso(self) -> bool:
        """Check if MISO pin is available for read operations."""
        # If MISO wasn't configured, the SPI bus won't support reads
        # This is a limitation of the MagTag hardware
        try:
            return self.spi._miso is not None
        except AttributeError:
            return False

    def write_command(self, cmd: int, data=None):
        """
        Send a command and optional data to the display.

        The SPI protocol uses the D/C pin to distinguish:
          - D/C LOW: Byte is a command
          - D/C HIGH: Bytes are data for the previous command

        Args:
            cmd: Command byte (0x00-0xFF)
            data: None, int, tuple of ints, or bytes/bytearray
        """
        # Wait if display is busy before sending new command
        if self.busy.value:
            self.wait_ready()

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
                    self._data_buf[0] = data
                    self.spi.write(memoryview(self._data_buf)[:1])
                elif isinstance(data, (bytes, bytearray, memoryview)):
                    self.spi.write(data)
                else:
                    # Tuple/list of ints
                    for i, b in enumerate(data):
                        self._data_buf[i] = b
                    self.spi.write(memoryview(self._data_buf)[:len(data)])
                self.cs.value = True
        finally:
            self.spi.unlock()

    def read_data(self, cmd: int, length: int = 1) -> bytes:
        """
        Read data from a display register.

        Read operations use a slower SPI clock (2.5MHz max per datasheet).
        The first byte read is dummy data and is discarded.

        Args:
            cmd: Command byte for the register to read
            length: Number of data bytes to read (excluding dummy byte)

        Returns:
            bytes: Data read from the register

        Raises:
            RuntimeError: If MISO is not available
        """
        if not self.has_miso:
            raise RuntimeError("Read operations require MISO pin")

        if self.busy.value:
            self.wait_ready()

        # Allocate buffer for dummy byte + actual data
        read_buf = bytearray(length + 1)

        while not self.spi.try_lock():
            pass
        try:
            # Reconfigure for read speed
            self.spi.configure(baudrate=self._read_baudrate, phase=0, polarity=0)

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
            self.spi.configure(baudrate=self._write_baudrate, phase=0, polarity=0)
        finally:
            self.spi.unlock()

        # Skip dummy byte, return actual data
        return bytes(read_buf[1:])

    def hardware_reset(self, pulse_ms: float = 1.0, recovery_ms: float = 1.0):
        """
        Perform hardware reset via RST pin.

        This is the only way to wake from deep sleep. After reset,
        all registers return to power-on-reset (POR) values.

        Args:
            pulse_ms: Reset pulse duration in milliseconds
            recovery_ms: Recovery time after reset in milliseconds
        """
        self.rst.value = False
        time.sleep(pulse_ms / 1000)
        self.rst.value = True
        time.sleep(recovery_ms / 1000)

    def wait_ready(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval_ms: int = 0,
        operation: str | None = None,
    ) -> float:
        """
        Wait for the display to finish processing (BUSY goes low).

        The BUSY pin is HIGH while:
          - Outputting display waveform
          - Programming OTP
          - Communicating with temperature sensor

        Args:
            timeout: Maximum wait time in seconds
            poll_interval_ms: Milliseconds between polls (0 = tight loop)
            operation: Optional operation name for error messages

        Returns:
            Time spent waiting in seconds

        Raises:
            RuntimeError: If timeout exceeded
        """
        start = time.monotonic()
        while self.busy.value:
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                op_str = f" during {operation}" if operation else ""
                raise RuntimeError(f"EPD timeout{op_str} (>{timeout}s)")
            if poll_interval_ms > 0:
                time.sleep(poll_interval_ms / 1000)
        return time.monotonic() - start

    @property
    def is_busy(self) -> bool:
        """Check if display is currently busy."""
        return self.busy.value
