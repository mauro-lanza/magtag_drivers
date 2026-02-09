"""
Benchmark Suite Menu (v2)
=========================
Interactive menu for running individual or all benchmarks.
Adapted for lib_v2 API.

Navigation:
  A: Move cursor up
  B: Move cursor down
  D: Select / run benchmark

Headless mode (via serial):
  Send 'r' after boot to auto-run all benchmarks

Run via serial for full output capture:
    tio /dev/cu.usbmodem* --log --log-file logs/bench_v2_$(date +%Y%m%d_%H%M%S).log
"""

import time
import gc
import supervisor

# =============================================================================
# Boot Benchmarks - measure import costs and init timing
# =============================================================================
print()
print("=" * 60)
print("  BOOT BENCHMARKS (lib_v2)")
print("=" * 60)

gc.collect()
_mem_start = gc.mem_free()
print(f"  Free RAM at boot:              {_mem_start:>10} bytes")

# Import Canvas (includes EPD, DrawBuffer, TextRenderer)
gc.collect()
_mem_before = gc.mem_free()
_t0 = time.monotonic_ns()
from canvas import Canvas
_t1 = time.monotonic_ns()
gc.collect()
_mem_after = gc.mem_free()
print(f"  canvas import:                 {(_t1-_t0)/1e6:>10.2f} ms  |  {_mem_before - _mem_after:>6} bytes")

# Import Buttons
gc.collect()
_mem_before = gc.mem_free()
_t0 = time.monotonic_ns()
from buttons import Buttons
_t1 = time.monotonic_ns()
gc.collect()
_mem_after = gc.mem_free()
print(f"  buttons import:                {(_t1-_t0)/1e6:>10.2f} ms  |  {_mem_before - _mem_after:>6} bytes")

# Import framebuffer for color constants
gc.collect()
_mem_before = gc.mem_free()
_t0 = time.monotonic_ns()
from framebuffer import BLACK, WHITE
_t1 = time.monotonic_ns()
gc.collect()
_mem_after = gc.mem_free()
print(f"  framebuffer import:            {(_t1-_t0)/1e6:>10.2f} ms  |  {_mem_before - _mem_after:>6} bytes")

# Import utils
gc.collect()
_mem_before = gc.mem_free()
_t0 = time.monotonic_ns()
from utils import BENCHMARK_VERSION, mem_free, print_header, print_metric
_t1 = time.monotonic_ns()
gc.collect()
_mem_after = gc.mem_free()
print(f"  utils import:                  {(_t1-_t0)/1e6:>10.2f} ms  |  {_mem_before - _mem_after:>6} bytes")

print("-" * 60)
gc.collect()
_mem_after_imports = gc.mem_free()
print(f"  Total import cost:                           |  {_mem_start - _mem_after_imports:>6} bytes")
print(f"  Free RAM after imports:        {_mem_after_imports:>10} bytes")
print("=" * 60)
print()

# Benchmark modules to load on demand
BENCHMARKS = [
    ("Run All Benchmarks", "all", None),
    ("EPD Driver", "bench_epd", "run"),
    ("GxEPD2 Comparison", "bench_gxepd2_comparison", "run"),
    # ("Custom LUTs", "bench_lut", "run"),
    # ("Primitives (buffer ops)", "bench_primitives", "run"),
    # ("Shapes (DrawBuffer)", "bench_shapes", "run"),
    # ("Text Rendering", "bench_text", "run"),
    # ("Buffer Conversions (v2)", "bench_conversions", "run"),
    # ("Workflows (end-to-end)", "bench_workflows", "run"),
]

# Serial command characters for headless mode
SERIAL_CMD_RUN_ALL = ord('r')
SERIAL_CMD_QUIT = ord('q')

# Display constants
MENU_START_Y = 20
LINE_HEIGHT = 18
VISIBLE_ITEMS = 5


class BenchmarkMenu:
    """Scrollable menu for benchmark selection."""

    def __init__(self, canvas, btns):
        self.canvas = canvas
        self.btns = btns
        self.items = BENCHMARKS
        self.cursor = 0
        self.scroll_offset = 0

    def draw(self):
        """Draw the menu screen and update display."""
        self._draw_content()
        self.canvas.partial_refresh()

    def draw_to_buffer(self):
        """Draw the menu to buffer without updating display."""
        self._draw_content()

    def _draw_content(self):
        """Draw menu content to the framebuffer."""
        self.canvas.clear()

        # Title
        self.canvas.text("Benchmark Suite v2", self.canvas.width // 2, 2, BLACK, align="center")
        self.canvas.hline(10, 16, self.canvas.width - 20, BLACK)

        # Menu items
        visible_count = min(len(self.items), VISIBLE_ITEMS)
        for i in range(visible_count):
            item_idx = self.scroll_offset + i
            if item_idx >= len(self.items):
                break

            y = MENU_START_Y + i * LINE_HEIGHT
            name = self.items[item_idx][0]

            if item_idx == self.cursor:
                self.canvas.text(f"> {name}", 15, y, BLACK)
            else:
                self.canvas.text(f"  {name}", 15, y, BLACK)

        # Footer
        self.canvas.hline(10, self.canvas.height - 18, self.canvas.width - 20, BLACK)
        self.canvas.text("[A]Up [B]Down [D]Run",
                        self.canvas.width // 2, self.canvas.height - 14, BLACK, align="center")

    def move_up(self):
        if self.cursor > 0:
            self.cursor -= 1
            if self.cursor < self.scroll_offset:
                self.scroll_offset = self.cursor

    def move_down(self):
        if self.cursor < len(self.items) - 1:
            self.cursor += 1
            if self.cursor >= self.scroll_offset + VISIBLE_ITEMS:
                self.scroll_offset = self.cursor - VISIBLE_ITEMS + 1

    def get_selected(self):
        return self.items[self.cursor]

    def wait_for_selection(self):
        """Wait for user input. Returns selected item on D."""
        while True:
            btn = self.btns.wait([Buttons.A, Buttons.B, Buttons.D])

            if btn == Buttons.A:
                self.move_up()
                self.draw()
            elif btn == Buttons.B:
                self.move_down()
                self.draw()
            elif btn == Buttons.D:
                return self.get_selected()


def run_single_benchmark(name, module_name, func_name, canvas, buttons=None):
    """Run a single benchmark module.

    Args:
        name: Display name of benchmark
        module_name: Python module to import
        func_name: Function name to call
        canvas: Canvas instance
        buttons: Optional Buttons instance for interactive mode
    """
    print()
    print("*" * 60)
    print(f"  Running: {name}")
    print("*" * 60)

    try:
        module = __import__(module_name)
        run_func = getattr(module, func_name)
        # Pass buttons for interactive benchmarks
        if module_name in ("bench_epd", "bench_lut") and buttons:
            run_func(canvas, buttons)
        else:
            run_func(canvas)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exception(e)


def run_all_benchmarks(canvas):
    """Run all benchmarks in sequence."""
    print()
    print("*" * 60)
    print("  lib_v2 Benchmark Suite")
    print(f"  Version: {BENCHMARK_VERSION}")
    print("  " + "=" * 40)
    print(f"  Free RAM: {mem_free()} bytes")
    print("*" * 60)

    start_time = time.monotonic()

    # Run each benchmark (skip "Run All" entry)
    for name, module_name, func_name in BENCHMARKS[1:]:
        if module_name and func_name:
            run_single_benchmark(name, module_name, func_name, canvas)
            gc.collect()

    # Memory diagnostics
    print_header("MEMORY DIAGNOSTICS")
    gc.collect()
    print_metric("Free RAM", mem_free(), "bytes")

    # Buffer sizes
    fb = canvas._fb
    print_metric("Framebuffer size", len(canvas.buffer), "bytes")
    print_metric("Framebuffer depth", fb.depth, "bpp")
    print_metric("Display dimensions", f"{fb._phys_w}x{fb._phys_h}", "px")
    print_metric("Logical dimensions", f"{canvas.width}x{canvas.height}", "px")
    print_metric("Rotation", fb.rotation, "deg")

    # Summary
    total_time = time.monotonic() - start_time
    print_header("SUMMARY")
    print_metric("Total benchmark time", total_time, "sec")
    print_metric("Final free RAM", mem_free(), "bytes")

    print()
    print("*" * 60)
    print("  Benchmark Complete")
    print("*" * 60)
    print()


def show_running_screen(canvas, name):
    """Show 'Running...' screen."""
    canvas.clear()
    canvas.text("Running:", canvas.width // 2, 30, BLACK, align="center")
    canvas.text(name, canvas.width // 2, 52, BLACK, align="center")
    canvas.text("See serial output", canvas.width // 2, 90, BLACK, align="center")
    canvas.full_refresh()


def show_complete_screen(canvas, btns, headless=False):
    """Show completion screen and wait for button (unless headless)."""
    canvas.clear()
    canvas.text("Benchmark Complete", canvas.width // 2, 30, BLACK, align="center")
    canvas.text("See serial output", canvas.width // 2, 52, BLACK, align="center")
    if not headless:
        canvas.text("[D] Return to menu", canvas.width // 2, 90, BLACK, align="center")
    canvas.partial_refresh()
    canvas.sleep()  # Done with display for now
    if not headless:
        btns.wait([Buttons.D])


def check_serial_command():
    """Check for serial command input (non-blocking)."""
    if supervisor.runtime.serial_bytes_available:
        import sys
        cmd = sys.stdin.read(1)
        if cmd:
            return ord(cmd)
    return None


def drain_serial():
    """Drain any pending serial input."""
    while supervisor.runtime.serial_bytes_available:
        import sys
        sys.stdin.read(1)


def _bench_init(label, func):
    """Benchmark an initialization function, returning its result."""
    gc.collect()
    mem_before = gc.mem_free()
    t0 = time.monotonic_ns()
    result = func()
    t1 = time.monotonic_ns()
    gc.collect()
    mem_after = gc.mem_free()
    print(f"  {label:<24} {(t1-t0)/1e6:>10.2f} ms  |  {mem_before - mem_after:>6} bytes")
    return result


def main():
    """Main entry point."""
    print(f"Benchmark Suite v{BENCHMARK_VERSION}")
    print("Initializing hardware...")

    # ==========================================================================
    # Hardware initialization benchmarks
    # ==========================================================================
    canvas = _bench_init("Canvas() creation:", lambda: Canvas(rotation=270))
    btns = _bench_init("Buttons() creation:", Buttons)

    # Load default font
    _bench_init("load_font():", lambda: canvas.load_font("/lib/fonts/cozette.bf2"))

    # Initial display
    canvas.clear()
    t0 = time.monotonic_ns()
    canvas.full_refresh()
    t1 = time.monotonic_ns()
    print(f"  Initial full refresh:          {(t1-t0)/1e6:>10.2f} ms")

    print("-" * 60)
    gc.collect()
    print(f"  Free RAM ready for menu:       {gc.mem_free():>10} bytes")
    print("=" * 60)
    print()

    # Drain any buffered serial input from reboot
    drain_serial()

    menu = BenchmarkMenu(canvas, btns)

    while True:
        menu.draw()

        # Check for serial command before waiting for buttons
        cmd = check_serial_command()
        if cmd == SERIAL_CMD_RUN_ALL:
            print("[SERIAL] Received 'r' - running all benchmarks (headless mode)")
            show_running_screen(canvas, "All Benchmarks")
            run_all_benchmarks(canvas)
            show_complete_screen(canvas, btns, headless=True)
            print("[SERIAL] Headless run complete. Exiting.")
            return
        elif cmd == SERIAL_CMD_QUIT:
            print("[SERIAL] Received 'q' - exiting")
            return

        # Normal interactive mode
        name, module_name, func_name = menu.wait_for_selection()

        if module_name == "all":
            show_running_screen(canvas, "All Benchmarks")
            run_all_benchmarks(canvas)
        elif module_name and func_name:
            show_running_screen(canvas, name)
            # Pass buttons for interactive mode (EPD benchmarks can pause between tests)
            run_single_benchmark(name, module_name, func_name, canvas, btns)
        else:
            continue

        # Common post-benchmark flow
        show_complete_screen(canvas, btns)
        # Re-establish basemap with menu already drawn
        menu.draw_to_buffer()
        canvas.full_refresh()


# Entry point
main()
