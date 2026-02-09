"""
Main Menu for MagTag E-Paper Demos
==================================
Navigation:
  A: Move cursor up
  B: Move cursor down
  D: Select / run demo

Demos return to this menu when complete.
"""

import time
_BOOT_START = time.monotonic()  # Capture as early as possible

from epd_driver import EPD
from canvas import Canvas
from buttons import Buttons

# Demo registry: (name, module_name, run_function_name)
# Each demo should have a run(canvas, btns) or run(canvas) function
# Use None for module_name to indicate a special action (like toggle)
DEMOS = [
    ("Invert: OFF", None, "toggle_invert"),  # Special toggle action
    ("Driver Demo", "demo_driver", "run"),
    ("Canvas Demo", "demo_canvas", "run"),
]

# Display constants (tuned for 13px cozette font)
MENU_START_Y = 32
LINE_HEIGHT = 18
VISIBLE_ITEMS = 4  # Max items visible at once


class Menu:
    """Scrollable menu with cursor."""

    def __init__(self, canvas, btns, items):
        self.canvas = canvas
        self.btns = btns
        self.items = items
        self.cursor = 0
        self.scroll_offset = 0

    def draw(self, verbose=False):
        """Draw the menu screen. If verbose=True, print timing breakdown."""
        if verbose:
            t0 = time.monotonic()

        self.canvas.clear()

        if verbose:
            t1 = time.monotonic()

        # Title
        self.canvas.text("MagTag Demos", self.canvas.width // 2, 6, align="center")

        if verbose:
            t2 = time.monotonic()

        self.canvas.hline(10, 22, self.canvas.width - 20)

        # Menu items
        visible_count = min(len(self.items), VISIBLE_ITEMS)
        for i in range(visible_count):
            item_idx = self.scroll_offset + i
            if item_idx >= len(self.items):
                break

            y = MENU_START_Y + i * LINE_HEIGHT
            name = self.items[item_idx][0]

            # Cursor indicator
            if item_idx == self.cursor:
                self.canvas.text(f"> {name}", 15, y)
            else:
                self.canvas.text(f"  {name}", 15, y)

        # Scroll indicators
        if self.scroll_offset > 0:
            self.canvas.text("^", self.canvas.width - 15, MENU_START_Y - 5)
        if self.scroll_offset + VISIBLE_ITEMS < len(self.items):
            self.canvas.text("v", self.canvas.width - 15,
                           MENU_START_Y + (visible_count - 1) * LINE_HEIGHT + 5)

        # Footer with controls
        self.canvas.hline(10, self.canvas.height - 18, self.canvas.width - 20)
        self.canvas.text("[A]Up [B]Down [D]Select",
                        self.canvas.width // 2, self.canvas.height - 14, align="center")

        if verbose:
            t3 = time.monotonic()

        self.canvas.update("partial")

        if verbose:
            t4 = time.monotonic()
            print(f"\n  [Menu draw breakdown]")
            print(f"    FB clear:       {(t1 - t0)*1000:6.0f}ms")
            print(f"    First text:     {(t2 - t1)*1000:6.0f}ms  (font load)")
            print(f"    Rest of draw:   {(t3 - t2)*1000:6.0f}ms")
            print(f"    EPD refresh:    {(t4 - t3)*1000:6.0f}ms")

    def move_up(self):
        """Move cursor up."""
        if self.cursor > 0:
            self.cursor -= 1
            # Scroll if needed
            if self.cursor < self.scroll_offset:
                self.scroll_offset = self.cursor

    def move_down(self):
        """Move cursor down."""
        if self.cursor < len(self.items) - 1:
            self.cursor += 1
            # Scroll if needed
            if self.cursor >= self.scroll_offset + VISIBLE_ITEMS:
                self.scroll_offset = self.cursor - VISIBLE_ITEMS + 1

    def get_selected(self):
        """Return the currently selected item."""
        return self.items[self.cursor]

    def wait_for_selection(self):
        """Wait for user input. Returns selected item on D, or None for navigation."""
        while True:
            btn = self.btns.wait([Buttons.A, Buttons.B, Buttons.D])

            if btn == Buttons.A:  # Up
                self.move_up()
                self.draw()
            elif btn == Buttons.B:  # Down
                self.move_down()
                self.draw()
            elif btn == Buttons.D:  # Select
                return self.get_selected()


def run_demo(name, module_name, func_name, canvas, btns):
    """Import and run a demo."""
    print(f"\n{'=' * 40}")
    print(f"Running: {name}")
    print(f"{'=' * 40}")

    try:
        module = __import__(module_name)
        run_func = getattr(module, func_name)

        # Try with btns first, fall back to canvas only
        try:
            run_func(canvas, btns)
        except TypeError:
            run_func(canvas)

    except Exception as e:
        print(f"Error: {e}")
        canvas.clear()
        canvas.text("ERROR", canvas.width // 2, 40, align="center")
        canvas.text(str(e)[:40], canvas.width // 2, 60, align="center")
        canvas.update("full")
        btns.wait()


def toggle_invert(canvas, menu):
    """Toggle the framebuffer's inverted property and update menu item."""
    fb = canvas._fb
    fb.invert()  # Toggle in-place
    state = "ON" if fb.is_inverted else "OFF"
    print(f"Inverted mode: {state}")

    # Update the menu item text
    for i, item in enumerate(menu.items):
        if item[2] == "toggle_invert":
            menu.items[i] = (f"Invert: {state}", None, "toggle_invert")
            break


def main():
    """Main entry point."""
    t0 = _BOOT_START
    print("\n" + "=" * 40)
    print("MagTag Demo Menu")
    print("=" * 40)

    # Initialize hardware (skip clear for fast boot - ~1.4s faster!)
    # First menu draw will do a full refresh anyway via display_partial's auto-detection
    t1 = time.monotonic()
    epd = EPD()
    epd.init(clear=False)
    t2 = time.monotonic()
    canvas = Canvas(epd, rotation=270)
    btns = Buttons()
    t3 = time.monotonic()

    print(f"Display: {canvas.width}x{canvas.height}")
    print("Controls: [A]=Up [B]=Down [D]=Select")

    menu = Menu(canvas, btns, list(DEMOS))  # Copy list so we can modify it

    # First menu draw with verbose timing breakdown
    t4 = time.monotonic()
    menu.draw(verbose=True)
    t5 = time.monotonic()

    # Print startup timing breakdown
    print(f"\n--- Startup Timing ---")
    print(f"  Imports:      {(t1 - t0)*1000:6.0f}ms")
    print(f"  EPD init:     {(t2 - t1)*1000:6.0f}ms")
    print(f"  Canvas/Btns:  {(t3 - t2)*1000:6.0f}ms")
    print(f"  Menu draw:    {(t5 - t4)*1000:6.0f}ms")
    print(f"  TOTAL:        {(t5 - t0)*1000:6.0f}ms")
    print(f"----------------------")

    # Main loop
    while True:
        name, module_name, func_name = menu.wait_for_selection()

        if module_name is None:
            # Special action (not a demo)
            if func_name == "toggle_invert":
                toggle_invert(canvas, menu)
                menu.draw()  # Redraw after toggle
        else:
            # Run selected demo
            run_demo(name, module_name, func_name, canvas, btns)
            print("\nReturning to menu...")
            epd.init(clear=False)  # Re-init EPD in case demo put it to sleep
            menu.draw()  # Redraw menu after returning from demo


if __name__ == "__main__":
    main()
