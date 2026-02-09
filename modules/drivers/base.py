"""
DisplayDriver - Abstract Base for EPD Drivers
==============================================
Defines the interface that all display drivers must implement.

This allows Canvas and other high-level code to work with any
display without knowing the specific controller details.

Note: Using duck typing instead of ABC for CircuitPython compatibility.
"""

try:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from .state import DriverState
except ImportError:
    pass


class DisplayDriver:
    """
    Abstract base class for e-paper display drivers.

    Subclasses must implement all methods marked as "abstract".
    This enables display-agnostic high-level code.

    Properties:
        WIDTH: Physical display width in pixels
        HEIGHT: Physical display height in pixels
        BUFFER_SIZE: Required buffer size in bytes
        state: Current DriverState
    """

    # Subclasses must define these
    WIDTH: int = 0
    HEIGHT: int = 0
    BUFFER_SIZE: int = 0

    def init(self, clear: bool = True):
        """
        Initialize the display for use.

        Should be called once after power-on or wake from deep sleep.

        Args:
            clear: If True, clear display to white after init
        """
        raise NotImplementedError

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
            data: Image buffer (BUFFER_SIZE bytes, 1 bit per pixel)
            full: If True, use full refresh. If False, partial refresh.
            force_full: If True with full=False, force full refresh.
            stay_awake: Keep display powered after update.

        Returns:
            Refresh time in seconds
        """
        raise NotImplementedError

    def display_gray(self, black_plane: bytes, red_plane: bytes) -> float:
        """
        Display a 4-level grayscale image.

        Args:
            black_plane: Data for BW RAM
            red_plane: Data for RED RAM

        Returns:
            Refresh time in seconds
        """
        raise NotImplementedError

    def display_lut(
        self,
        lut: bytes,
        black: bytes,
        red: bytes | None = None,
        **kwargs
    ) -> float:
        """
        Display with a custom LUT waveform.

        Args:
            lut: Custom LUT data (153 bytes for SSD1680)
            black: Data for BW RAM
            red: Data for RED RAM (optional)
            **kwargs: Driver-specific options (e.g., voltage levels)

        Returns:
            Refresh time in seconds
        """
        raise NotImplementedError

    def display_region(
        self,
        data: bytes,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> float:
        """
        Update a rectangular region of the display.

        Args:
            data: Region buffer (w/8 * h bytes)
            x: X position (must be 8-pixel aligned)
            y: Y position
            w: Width (must be 8-pixel aligned)
            h: Height

        Returns:
            Refresh time in seconds
        """
        raise NotImplementedError

    def display_regions(self, regions: list) -> float:
        """
        Update multiple regions with a single refresh.

        Args:
            regions: List of (data, x, y, w, h) tuples

        Returns:
            Refresh time in seconds
        """
        raise NotImplementedError

    def clear(self, color: int = 0xFF):
        """
        Clear display to a solid color.

        Args:
            color: Fill byte (0xFF=white, 0x00=black)
        """
        raise NotImplementedError

    def sleep(self, retain_ram: bool = True):
        """
        Enter deep sleep mode.

        Args:
            retain_ram: If True, RAM contents preserved
        """
        raise NotImplementedError

    def wake(self):
        """Wake from deep sleep (performs hardware reset)."""
        raise NotImplementedError

    def deinit(self):
        """Release hardware resources."""
        raise NotImplementedError

    # Optional methods (may raise NotImplementedError if not supported)

    def set_invert(self, invert_bw: bool = False, invert_red: bool = False):
        """Enable hardware display inversion."""
        raise NotImplementedError

    def read_temperature(self) -> float:
        """Read internal temperature sensor (requires MISO)."""
        raise NotImplementedError

    def check_temperature(self) -> tuple:
        """
        Read temperature and check if within operating range.

        Returns:
            Tuple of (temperature: float, in_range: bool)
        """
        raise NotImplementedError

    def read_status(self) -> dict:
        """Read diagnostic status bits."""
        raise NotImplementedError

    def fast_clear(self, color: int = 0xFF):
        """Hardware-accelerated clear using auto-fill."""
        raise NotImplementedError

    # Properties

    @property
    def state(self) -> "DriverState":
        """Current driver state."""
        raise NotImplementedError

    @property
    def is_sleeping(self) -> bool:
        """Check if display is in deep sleep."""
        raise NotImplementedError

    @property
    def partial_count(self) -> int:
        """Number of partial refreshes since last full."""
        raise NotImplementedError

    @partial_count.setter
    def partial_count(self, value: int):
        raise NotImplementedError

    @property
    def partial_threshold(self) -> int:
        """Auto-full threshold (0=disabled)."""
        raise NotImplementedError

    @partial_threshold.setter
    def partial_threshold(self, value: int):
        raise NotImplementedError
