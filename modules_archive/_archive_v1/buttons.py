"""
MagTag Button Handler
=====================
Thin wrapper over CircuitPython's keypad module for MagTag buttons.

Usage:
    from buttons import Buttons

    btns = Buttons()
    while True:
        pressed = btns.read()  # Returns index 0-3 or None
        if pressed == btns.A:
            print("Button A!")

    # Or use as context manager
    with Buttons() as btns:
        pressed = btns.wait()
"""
try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False
import board
import keypad

_PINS = (board.BUTTON_A, board.BUTTON_B, board.BUTTON_C, board.BUTTON_D)  # type: ignore[attr-defined]


class Buttons:
    """Handler for MagTag's 4 buttons using keypad module."""

    A: int = 0
    B: int = 1
    C: int = 2
    D: int = 3

    def __init__(self) -> None:
        self._keys = keypad.Keys(_PINS, value_when_pressed=False, pull=True)

    def __enter__(self) -> "Buttons":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit - ensure cleanup."""
        self.deinit()
        return False

    def deinit(self) -> None:
        """Release button pins."""
        self._keys.deinit()

    def read(self) -> int | None:
        """Non-blocking read. Returns index (0-3) on press, None otherwise."""
        event = self._keys.events.get()
        return event.key_number if event and event.pressed else None

    def wait(self, buttons: list[int] | None = None) -> int:
        """Blocking wait for button press. Returns index 0-3."""
        self._keys.events.clear()
        while True:
            event = self._keys.events.get()
            if event and event.pressed:
                if buttons is None or event.key_number in buttons:
                    return event.key_number
