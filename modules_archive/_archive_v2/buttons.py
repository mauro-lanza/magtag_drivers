"""
Buttons - MagTag Button Handler
===============================
Robust wrapper over CircuitPython's keypad module.

Features:
- Event-based handling (press/release)
- Live state tracking (is_pressed)
- Configurable debounce
- Safe resource management

Usage:
    btns = Buttons()

    # 1. Event Loop (Best for menus)
    while True:
        btn = btns.read()
        if btn == Buttons.A:
            print("Pressed A")

    # 2. Live State (Best for games/continuous)
    btns.update() # Must call periodically
    if btns.is_pressed(Buttons.B):
        print("Holding B")
"""

import board
import keypad

class Buttons:
    """
    Handler for MagTag's 4 buttons using keypad module.
    """

    A = 0
    B = 1
    C = 2
    D = 3

    def __init__(self, debounce_interval: float = 0.05):
        """
        Initialize buttons.

        Args:
            debounce_interval: Debounce time in seconds (default 0.05s)
        """
        self._pins = (board.BUTTON_A, board.BUTTON_B, board.BUTTON_C, board.BUTTON_D)
        self._keys = keypad.Keys(
            self._pins,
            value_when_pressed=False,
            pull=True,
            interval=debounce_interval
        )
        # Track logical state for is_pressed()
        self._state = [False] * 4

    def deinit(self):
        """Release button pins safely."""
        if self._keys:
            self._keys.deinit()
            self._keys = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.deinit()
        return False

    def update(self):
        """
        Process pending events to update internal state.
        Call this if you use is_pressed(), otherwise not strictly needed.
        """
        event = self._keys.events.get()
        while event:
            if event.key_number < 4:
                self._state[event.key_number] = event.pressed
            event = self._keys.events.get()

    def read(self) -> int | None:
        """
        Return the next button press event (Non-blocking).
        Also updates internal state.

        Returns:
            Button index (0-3) or None.
        """
        event = self._keys.events.get()
        if event:
            # Sync state
            if event.key_number < 4:
                self._state[event.key_number] = event.pressed

            if event.pressed:
                return event.key_number
        return None

    def is_pressed(self, button: int) -> bool:
        """
        Check if a button is currently held down.
        Requires calling update() or read() frequently to be accurate.
        """
        return self._state[button]

    def wait(self, buttons: list = None) -> int:
        """
        Blocking wait for a specific button press.

        Args:
            buttons: List of button indices to wait for (default: any).
        """
        # Clear old events to ensure we wait for a *new* press
        self._keys.events.clear()

        while True:
            event = self._keys.events.get()
            if event and event.pressed:
                if buttons is None or event.key_number in buttons:
                    self._state[event.key_number] = True
                    return event.key_number

    def clear(self):
        """Clear event queue."""
        self._keys.events.clear()
