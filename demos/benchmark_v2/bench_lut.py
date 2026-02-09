"""
Custom LUT Benchmarks
=====================
Specialized benchmarks for testing custom Look-Up Tables (waveforms)
on the SSD1680 e-paper display.

Tests:
  - VS (Voltage Source) patterns: Do pixels transition correctly?
  - Timing: How fast are custom LUTs vs standard refresh?
  - Ghosting: Do rapid updates leave artifacts?
  - Recovery: Can standard refresh clear ghosting?

Usage:
  Import and call run(canvas, buttons) from the benchmark menu,
  or run standalone for focused LUT development.
"""

import gc
import time
from utils import print_header, print_metric, print_separator, print_subheader, timed


def run(canvas, buttons=None) -> None:
    """Run custom LUT benchmarks.

    Args:
        canvas: Canvas instance
        buttons: Optional Buttons instance for interactive mode
    """
    bench_custom_lut(canvas, buttons)


def bench_custom_lut(canvas, buttons=None) -> None:
    """Custom LUT benchmarks with detailed transition testing.

    Tests each custom LUT through multiple phases:
      1. Baseline: Establish known starting state
      2. B→Pattern: Test black-to-white transitions
      3. W→Pattern: Test white-to-black transitions
      4. Rapid toggle: Stress test for ghosting
      5. Recovery: Verify standard refresh clears ghosting

    Args:
        canvas: Canvas instance
        buttons: Optional Buttons instance for interactive mode
    """
    print_header("CUSTOM LUT BENCHMARK")

    from framebuffer import BLACK, WHITE

    # Import custom LUTs
    try:
        from lut import LUT_LOW_FLASH, LUT_TURBO, LUT_BALANCED
    except ImportError:
        print("ERROR: Custom LUTs not found in lut.py")
        print_separator()
        return

    # Define LUTs to test - order by expected speed
    LUTS = [
        ("STANDARD", None),      # None = use full_refresh()
        ("TURBO", LUT_TURBO),    # Fastest custom LUT
        ("BALANCED", LUT_BALANCED),
        ("LOW_FLASH", LUT_LOW_FLASH),  # Slowest, smoothest
    ]

    results = {}
    errors = {}

    def wait(msg="continue"):
        """Wait for button or brief pause."""
        if buttons:
            print(f"  [Press any button to {msg}]")
            from buttons import Buttons
            buttons.wait([Buttons.A, Buttons.B, Buttons.C, Buttons.D])
        else:
            time.sleep(0.5)

    def draw_test_pattern(label):
        """Draw test pattern showing all 4 LUT transitions.

        When using display_lut() with same buffer to both RAMs:
          - pixel=0 → R=0, BW=0 → LUT0 → should be BLACK
          - pixel=1 → R=1, BW=1 → LUT3 → should be WHITE

        Pattern includes:
          - Solid black areas (test LUT0)
          - Solid white areas (test LUT3)
          - Checkerboard (fine detail test)
          - Text (readability test)
        """
        canvas.clear(WHITE)

        # Header
        canvas.text(label, canvas.width // 2, 8, BLACK, align="center")

        # Large solid areas
        canvas.fill_rect(5, 30, 50, 50, BLACK)   # Should be solid black
        canvas.text("BLACK", 30, 85, BLACK, align="center")

        canvas.rect(65, 30, 50, 50, BLACK)       # Outline only - interior white
        canvas.text("WHITE", 90, 85, BLACK, align="center")

        # Checkerboard (tests fine pixel transitions)
        for row in range(5):
            for col in range(5):
                if (row + col) % 2 == 0:
                    canvas.fill_rect(5 + col*10, 100 + row*10, 10, 10, BLACK)

        # Vertical bars (tests horizontal transitions)
        for i in range(8):
            if i % 2 == 0:
                canvas.fill_rect(65 + i*6, 100, 6, 50, BLACK)

        # Text at different sizes
        canvas.text("AaBb123", canvas.width - 10, 30, BLACK, align="right")

    def refresh_with_lut(lut_data):
        """Refresh display with given LUT or standard refresh."""
        if lut_data is None:
            return canvas.full_refresh()
        else:
            return canvas.custom_refresh(lut_data)

    def safe_refresh(name, lut_data):
        """Refresh with error handling, returns (time, error)."""
        try:
            _, elapsed = timed(refresh_with_lut, lut_data)
            return elapsed, None
        except RuntimeError as e:
            error_msg = str(e)
            print(f"  ERROR: {name} failed - {error_msg}")
            return None, error_msg

    # =========================================================================
    # Phase 1: Quick single-LUT test mode (for development)
    # =========================================================================
    # Uncomment to test just one LUT:
    # LUTS = [("TURBO", LUT_TURBO)]

    # =========================================================================
    # Phase 2: Establish baseline
    # =========================================================================
    print_subheader("Phase 1: Establish Baseline")
    print("Standard full refresh to known state...")

    canvas.clear(WHITE)
    canvas.full_refresh()
    time.sleep(0.3)

    wait("start LUT tests")

    # =========================================================================
    # Phase 3: Test each LUT with pattern
    # =========================================================================
    print_subheader("Phase 2: Pattern Test (all LUTs)")
    print()

    for name, lut_data in LUTS:
        # Draw pattern
        draw_test_pattern(name)

        # Refresh and measure
        elapsed, error = safe_refresh(name, lut_data)

        if error:
            errors[name] = error
            results[name] = None
            # Recovery: try standard refresh
            print(f"  Recovering with standard refresh...")
            canvas.full_refresh()
        else:
            results[name] = elapsed
            print_metric(name, elapsed)

        wait("test next LUT")

    # =========================================================================
    # Phase 4: Rapid toggle test (skip failed LUTs)
    # =========================================================================
    print_subheader("Phase 3: Rapid Toggle (stress test)")
    print()

    working_luts = [(n, l) for n, l in LUTS[1:] if n not in errors]

    if not working_luts:
        print("  No custom LUTs working, skipping rapid test")
    else:
        for name, lut_data in working_luts:
            times = []
            toggle_errors = 0

            for i in range(3):
                # Alternate patterns
                canvas.clear(WHITE if i % 2 == 0 else BLACK)
                canvas.fill_rect(20, 20, 100, 80, BLACK if i % 2 == 0 else WHITE)
                canvas.text(f"#{i+1}", 70, 110, BLACK if i % 2 == 0 else WHITE, align="center")

                elapsed, error = safe_refresh(name, lut_data)
                if error:
                    toggle_errors += 1
                    canvas.full_refresh()  # Recovery
                else:
                    times.append(elapsed)

            if times:
                avg = sum(times) / len(times)
                results[f"{name}_avg"] = avg
                suffix = f" ({toggle_errors} errors)" if toggle_errors else ""
                print_metric(f"{name} avg (3x){suffix}", avg)
            else:
                print(f"  {name}: All 3 cycles failed")

    wait("see recovery test")

    # =========================================================================
    # Phase 5: Recovery test
    # =========================================================================
    print_subheader("Phase 4: Recovery")
    print("Standard refresh to clear any ghosting...")

    canvas.clear(WHITE)
    canvas.text("RECOVERY", canvas.width // 2, 50, BLACK, align="center")
    canvas.fill_rect(30, 80, 60, 40, BLACK)
    canvas.fill_rect(110, 80, 60, 40, BLACK)
    _, elapsed = timed(canvas.full_refresh)
    print_metric("full_refresh()", elapsed)

    # =========================================================================
    # Summary
    # =========================================================================
    print_subheader("SUMMARY")
    print()

    std_time = results.get("STANDARD", 1.0)

    print("  LUT           Time      vs Std   Status")
    print("  -----------   -------   ------   ------")

    for name, _ in LUTS:
        t = results.get(name)
        if t is None:
            print(f"  {name:11s}   FAILED            {errors.get(name, 'unknown')}")
        else:
            pct = int(t / std_time * 100) if std_time else 0
            avg = results.get(f"{name}_avg")
            avg_str = f"(avg {avg*1000:.0f}ms)" if avg else ""
            print(f"  {name:11s}   {t*1000:5.0f}ms    {pct:3d}%     OK {avg_str}")

    print()
    print("VISUAL CHECK:")
    print("  [ ] Black areas are solid black (no gray)")
    print("  [ ] White areas are clean white (no gray)")
    print("  [ ] Checkerboard pattern is crisp")
    print("  [ ] Text is readable")

    if errors:
        print()
        print("ERRORS:")
        for name, err in errors.items():
            print(f"  {name}: {err}")

    canvas.sleep()
    gc.collect()
    print_separator()


# =============================================================================
# Standalone mode
# =============================================================================
if __name__ == "__main__":
    print("Run from benchmark menu or import and call run(canvas, buttons)")
