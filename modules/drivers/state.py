"""
DisplayState - State Management for EPD Drivers
================================================
Clean state machine implementation replacing bitflag approach.

Benefits over bitflags:
- Self-documenting state names
- Type-safe transitions
- Easier debugging (print state.name vs hex value)
- IDE autocomplete support
"""

try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False


class DisplayState:
    """
    Display driver state enumeration.

    States represent the display's operational mode and capabilities.
    Transitions between states are managed by the driver.

    State Diagram:
        UNINITIALIZED --> READY (after init)
        READY --> UPDATING (during refresh)
        UPDATING --> READY (refresh complete)
        READY --> SLEEPING (after sleep())
        SLEEPING --> READY (after wake/reset)
    """
    UNINITIALIZED = 0  # Power-on state, needs initialization
    READY = 1          # Initialized and idle, can accept commands
    UPDATING = 2       # Refresh in progress, BUSY pin high
    SLEEPING = 3       # Deep sleep mode, BUSY undefined

    _names = {
        0: "UNINITIALIZED",
        1: "READY",
        2: "UPDATING",
        3: "SLEEPING",
    }

    @classmethod
    def name(cls, state: int) -> str:
        """Get human-readable state name."""
        return cls._names.get(state, f"UNKNOWN({state})")


class RefreshMode:
    """
    Refresh mode enumeration.

    Determines the waveform and power behavior during display updates.
    """
    FULL = 0     # Complete refresh, all pixels through full waveform
    PARTIAL = 1  # Differential refresh, only changed pixels driven
    FAST = 2     # Fast refresh with reduced quality (if supported)
    GRAY = 3     # Grayscale mode using custom LUT


class DriverState:
    """
    Complete driver state container.

    Encapsulates all state information needed by the display driver.
    Using a class instead of dataclass for CircuitPython compatibility.

    Attributes:
        state: Current DisplayState
        has_basemap: True if full refresh completed (partials now allowed)
        partial_count: Number of partial refreshes since last full
        partial_threshold: Auto-full after this many partials (0=disabled)
        in_partial_mode: True if hardware configured for partial updates
        is_initial: True if first refresh pending (must be full)
    """

    def __init__(
        self,
        state: int = DisplayState.UNINITIALIZED,
        has_basemap: bool = False,
        partial_count: int = 0,
        partial_threshold: int = 10,
        in_partial_mode: bool = False,
        is_initial: bool = True,
    ):
        self.state = state
        self.has_basemap = has_basemap
        self.partial_count = partial_count
        self.partial_threshold = partial_threshold
        self.in_partial_mode = in_partial_mode
        self.is_initial = is_initial

    def reset(self):
        """Reset to initial state (after hardware reset)."""
        self.state = DisplayState.UNINITIALIZED
        self.in_partial_mode = False
        # Note: has_basemap and is_initial preserved (RAM may be retained)

    def on_init_complete(self):
        """Transition after successful initialization."""
        self.state = DisplayState.READY

    def on_full_refresh_complete(self):
        """Transition after full refresh."""
        self.state = DisplayState.READY
        self.has_basemap = True
        self.is_initial = False
        self.partial_count = 0
        self.in_partial_mode = False

    def on_partial_refresh_complete(self):
        """Transition after partial refresh."""
        self.state = DisplayState.READY
        self.partial_count += 1

    def on_sleep(self, retain_ram: bool = True):
        """Transition to sleep state."""
        self.state = DisplayState.SLEEPING
        self.in_partial_mode = False
        if not retain_ram:
            self.has_basemap = False

    def on_wake(self):
        """Transition from sleep (after hardware reset)."""
        self.state = DisplayState.UNINITIALIZED
        self.in_partial_mode = False

    def needs_full_refresh(self) -> bool:
        """Check if full refresh is required."""
        return (
            self.is_initial or
            not self.has_basemap or
            (self.partial_threshold > 0 and
             self.partial_count >= self.partial_threshold)
        )

    def can_partial_refresh(self) -> bool:
        """Check if partial refresh is allowed."""
        return self.has_basemap and not self.is_initial

    @property
    def is_sleeping(self) -> bool:
        return self.state == DisplayState.SLEEPING

    @property
    def is_ready(self) -> bool:
        return self.state == DisplayState.READY

    @property
    def is_updating(self) -> bool:
        return self.state == DisplayState.UPDATING

    def __repr__(self) -> str:
        return (
            f"DriverState("
            f"state={DisplayState.name(self.state)}, "
            f"basemap={self.has_basemap}, "
            f"partial={self.partial_count}/{self.partial_threshold}, "
            f"initial={self.is_initial})"
        )
