"""
Buffer Conversion Benchmarks (v2)
=================================
Tests v2-specific optimizations: LUT-based to_mono(), to_planes().
These are new in v2 and critical for 4-gray performance.
"""

import gc
from utils import print_header, print_metric, print_separator, print_subheader, avg_timed, timed


def run(canvas) -> None:
    """Run buffer conversion benchmarks."""
    bench_to_mono_1bit(canvas)
    bench_to_mono_2bit()
    bench_to_planes()
    bench_lut_initialization()


def bench_to_mono_1bit(canvas) -> None:
    """Benchmark to_mono() on 1-bit buffer (passthrough)."""
    print_header("CONVERSIONS: to_mono() [1-bit]")

    fb = canvas._fb

    print("For 1-bit buffers, to_mono() is a simple buffer copy.")
    print()

    # Fill with pattern
    from framebuffer import BLACK
    fb.clear()
    for y in range(0, fb.height, 2):
        fb.hline(0, y, fb.width, BLACK)

    elapsed = avg_timed(fb.to_mono, 20)
    print_metric("to_mono() [1-bit passthrough]", elapsed)

    fb.clear()
    print_separator()


def bench_to_mono_2bit() -> None:
    """Benchmark to_mono() on 2-bit buffer (LUT conversion)."""
    print_header("CONVERSIONS: to_mono() [2-bit LUT]")

    from draw import DrawBuffer
    from framebuffer import BLACK, DARK_GRAY, LIGHT_GRAY, WHITE

    print("For 2-bit buffers, to_mono() uses a 256-byte LUT for fast conversion.")
    print()

    fb = DrawBuffer(128, 296, depth=2, rotation=90)

    # Fill with gradient pattern
    fb.clear()
    fb.fill_rect(0, 0, fb.width // 4, fb.height, BLACK)
    fb.fill_rect(fb.width // 4, 0, fb.width // 4, fb.height, DARK_GRAY)
    fb.fill_rect(fb.width // 2, 0, fb.width // 4, fb.height, LIGHT_GRAY)
    fb.fill_rect(3 * fb.width // 4, 0, fb.width // 4, fb.height, WHITE)

    # First call triggers LUT initialization
    gc.collect()
    _, first_elapsed = timed(fb.to_mono)
    print_metric("to_mono() [first, includes LUT init]", first_elapsed)

    # Subsequent calls use cached LUT
    elapsed = avg_timed(fb.to_mono, 10)
    print_metric("to_mono() [cached LUT]", elapsed)

    print_separator()


def bench_to_planes() -> None:
    """Benchmark to_planes() for 4-gray mode."""
    print_header("CONVERSIONS: to_planes() [2-bit LUT]")

    from draw import DrawBuffer
    from framebuffer import BLACK, DARK_GRAY, LIGHT_GRAY, WHITE

    print("to_planes() splits 2-bit buffer into two 1-bit planes for 4-gray EPD.")
    print()

    fb = DrawBuffer(128, 296, depth=2, rotation=90)

    # Fill with all 4 gray levels
    fb.clear()
    fb.fill_rect(0, 0, fb.width // 4, fb.height, BLACK)
    fb.fill_rect(fb.width // 4, 0, fb.width // 4, fb.height, DARK_GRAY)
    fb.fill_rect(fb.width // 2, 0, fb.width // 4, fb.height, LIGHT_GRAY)
    fb.fill_rect(3 * fb.width // 4, 0, fb.width // 4, fb.height, WHITE)

    # First call may trigger LUT init
    gc.collect()
    _, first_elapsed = timed(fb.to_planes)
    print_metric("to_planes() [first call]", first_elapsed)

    # Subsequent calls
    elapsed = avg_timed(fb.to_planes, 10)
    print_metric("to_planes() [cached LUT]", elapsed)

    # Verify output sizes
    black, red = fb.to_planes()
    print_metric("Black plane size", len(black), "bytes")
    print_metric("Red plane size", len(red), "bytes")

    print_separator()


def bench_lut_initialization() -> None:
    """Benchmark lazy LUT initialization."""
    print_header("CONVERSIONS: LUT INITIALIZATION")

    print("v2 uses lazy LUT initialization to save ~768 bytes until first use.")
    print()

    # Force reimport to reset LUT state (if possible)
    import framebuffer

    # Save original LUTs
    orig_lut_mono = framebuffer._LUT_MONO
    orig_lut_black = framebuffer._LUT_BLACK
    orig_lut_red = framebuffer._LUT_RED

    # Reset LUTs
    framebuffer._LUT_MONO = None
    framebuffer._LUT_BLACK = None
    framebuffer._LUT_RED = None

    gc.collect()
    mem_before = gc.mem_free()
    _, elapsed = timed(framebuffer._init_luts)
    gc.collect()
    mem_after = gc.mem_free()

    print_metric("_init_luts() time", elapsed)
    print_metric("LUT memory cost", mem_before - mem_after, "bytes")

    # Restore all LUTs
    framebuffer._LUT_MONO = orig_lut_mono
    framebuffer._LUT_BLACK = orig_lut_black
    framebuffer._LUT_RED = orig_lut_red

    print_separator()
