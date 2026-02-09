"""
FrameBuffer Primitives Benchmarks (v2)
======================================
Tests core FrameBuffer operations: clear, pixel, lines, invert.
Adapted for lib_v2 API (color as int, DrawBuffer class).
"""

import random
from utils import print_header, print_metric, print_separator, print_subheader, avg_timed

# Seed for reproducible random tests
random.seed(42)


def run(canvas) -> None:
    """Run framebuffer primitives benchmarks."""
    fb = canvas._fb

    bench_clear(fb)
    bench_invert(fb)
    bench_pixels(fb)
    bench_pixel_fast(fb)
    bench_hlines(fb)
    bench_vlines(fb)


def bench_clear(fb) -> None:
    """Benchmark buffer clear operation."""
    print_header("PRIMITIVES: CLEAR")

    from framebuffer import WHITE, BLACK

    elapsed = avg_timed(fb.clear, 50)
    print_metric("clear() [white]", elapsed)

    elapsed = avg_timed(lambda: fb.clear(BLACK), 50)
    print_metric("clear(BLACK)", elapsed)

    fb.clear()
    print_separator()


def bench_invert(fb) -> None:
    """Benchmark buffer inversion (dark mode toggle)."""
    print_header("PRIMITIVES: INVERT")

    from framebuffer import BLACK

    # Fill half the screen for realistic invert test
    fb.clear()
    for y in range(64):
        fb.hline(0, y, fb.width, BLACK)

    # 50 iterations = even number, buffer returns to original state
    elapsed = avg_timed(fb.invert, 50)
    print_metric("invert() full buffer", elapsed)

    fb.clear()
    print_separator()


def bench_pixels(fb) -> None:
    """Benchmark standard pixel() with bounds checking."""
    print_header("PRIMITIVES: PIXEL (bounds-checked)")

    from framebuffer import BLACK

    fb.clear()

    # Pre-generate random coordinates
    coords_100 = [(random.randint(0, fb.width - 1), random.randint(0, fb.height - 1))
                  for _ in range(100)]
    coords_1000 = [(random.randint(0, fb.width - 1), random.randint(0, fb.height - 1))
                   for _ in range(1000)]

    def draw_pixels(coords):
        for x, y in coords:
            fb.pixel(x, y, BLACK)

    elapsed = avg_timed(draw_pixels, 10, coords_100)
    print_metric("pixel() x100", elapsed)

    elapsed = avg_timed(draw_pixels, 5, coords_1000)
    print_metric("pixel() x1000", elapsed)

    # Read pixels
    def read_pixels(coords):
        for x, y in coords:
            fb.get_pixel(x, y)

    elapsed = avg_timed(read_pixels, 10, coords_100)
    print_metric("get_pixel() x100", elapsed)

    fb.clear()
    print_separator()


def bench_pixel_fast(fb) -> None:
    """Benchmark pixel_fast() without bounds checking."""
    print_header("PRIMITIVES: PIXEL_FAST (no bounds check)")

    from framebuffer import BLACK

    fb.clear()

    # Pre-generate coordinates (guaranteed in-bounds)
    coords_100 = [(random.randint(0, fb.width - 1), random.randint(0, fb.height - 1))
                  for _ in range(100)]
    coords_1000 = [(random.randint(0, fb.width - 1), random.randint(0, fb.height - 1))
                   for _ in range(1000)]

    def draw_pixels_fast(coords):
        for x, y in coords:
            fb.pixel_fast(x, y, BLACK)

    elapsed = avg_timed(draw_pixels_fast, 10, coords_100)
    print_metric("pixel_fast() x100", elapsed)

    elapsed = avg_timed(draw_pixels_fast, 5, coords_1000)
    print_metric("pixel_fast() x1000", elapsed)

    # Compare overhead
    print_separator()
    print_subheader("Comparison: pixel() vs pixel_fast()")

    def pixel_1000():
        for x, y in coords_1000:
            fb.pixel(x, y, BLACK)

    def pixel_fast_1000():
        for x, y in coords_1000:
            fb.pixel_fast(x, y, BLACK)

    elapsed_checked = avg_timed(pixel_1000, 3)
    elapsed_fast = avg_timed(pixel_fast_1000, 3)

    print_metric("pixel() x1000", elapsed_checked)
    print_metric("pixel_fast() x1000", elapsed_fast)
    if elapsed_checked > 0:
        speedup = (elapsed_checked - elapsed_fast) / elapsed_checked * 100
        print_metric("Speedup", f"{speedup:.1f}", "%")

    fb.clear()
    print_separator()


def bench_hlines(fb) -> None:
    """Benchmark horizontal line drawing (byte-optimized)."""
    print_header("PRIMITIVES: HLINE (byte-optimized)")

    from framebuffer import BLACK

    fb.clear()

    # Various lengths to show byte-alignment benefits
    elapsed = avg_timed(lambda: fb.hline(0, 64, 8, BLACK), 100)
    print_metric("hline(8px) [1 byte]", elapsed)

    elapsed = avg_timed(lambda: fb.hline(0, 64, 16, BLACK), 100)
    print_metric("hline(16px) [2 bytes]", elapsed)

    elapsed = avg_timed(lambda: fb.hline(0, 64, 64, BLACK), 100)
    print_metric("hline(64px) [8 bytes]", elapsed)

    elapsed = avg_timed(lambda: fb.hline(0, 64, fb.width, BLACK), 50)
    print_metric(f"hline({fb.width}px) [full]", elapsed)

    # Misaligned (not byte-boundary start)
    elapsed = avg_timed(lambda: fb.hline(3, 64, 64, BLACK), 100)
    print_metric("hline(64px, x=3) [misaligned]", elapsed)

    fb.clear()
    print_separator()


def bench_vlines(fb) -> None:
    """Benchmark vertical line drawing."""
    print_header("PRIMITIVES: VLINE")

    from framebuffer import BLACK

    fb.clear()

    elapsed = avg_timed(lambda: fb.vline(148, 0, 16, BLACK), 100)
    print_metric("vline(16px)", elapsed)

    elapsed = avg_timed(lambda: fb.vline(148, 0, 64, BLACK), 100)
    print_metric("vline(64px)", elapsed)

    elapsed = avg_timed(lambda: fb.vline(148, 0, fb.height, BLACK), 50)
    print_metric(f"vline({fb.height}px) [full]", elapsed)

    fb.clear()
    print_separator()
