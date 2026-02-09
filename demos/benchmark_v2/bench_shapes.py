"""
DrawBuffer Shapes Benchmarks (v2)
=================================
Tests drawing primitives from DrawBuffer: lines, rectangles,
circles, triangles, and bitmap blitting.

In v2, shapes are methods on DrawBuffer (not standalone functions).
"""

import random
from utils import print_header, print_metric, print_separator, print_subheader, avg_timed

# Seed for reproducible random tests
random.seed(42)


def run(canvas) -> None:
    """Run shapes benchmarks."""
    fb = canvas._fb

    bench_lines(fb)
    bench_rectangles(fb)
    bench_circles(fb)
    bench_triangles(fb)
    bench_rounded_rect(fb)
    bench_blit(fb)


def bench_lines(fb) -> None:
    """Benchmark diagonal line drawing (Bresenham + Cohen-Sutherland clipping)."""
    print_header("SHAPES: LINE (Bresenham + Clipping)")

    from framebuffer import BLACK

    fb.clear()

    print("v2 uses Cohen-Sutherland clipping before Bresenham.")
    print()

    # Short diagonal
    elapsed = avg_timed(lambda: fb.line(0, 0, 50, 30, BLACK), 50)
    print_metric("line(50x30 diagonal)", elapsed)

    # Medium diagonal
    elapsed = avg_timed(lambda: fb.line(0, 0, 100, 60, BLACK), 50)
    print_metric("line(100x60 diagonal)", elapsed)

    # Full screen diagonal
    elapsed = avg_timed(lambda: fb.line(0, 0, fb.width - 1, fb.height - 1, BLACK), 20)
    print_metric(f"line({fb.width}x{fb.height} full)", elapsed)

    # Steep vs shallow
    print_separator()
    print_subheader("Steep vs shallow lines")

    elapsed = avg_timed(lambda: fb.line(0, 0, 100, 20, BLACK), 50)
    print_metric("line(100x20 shallow)", elapsed)

    elapsed = avg_timed(lambda: fb.line(0, 0, 20, 100, BLACK), 50)
    print_metric("line(20x100 steep)", elapsed)

    # Clipped lines (partially off-screen)
    print_separator()
    print_subheader("Clipped lines (off-screen)")

    elapsed = avg_timed(lambda: fb.line(-50, -50, 100, 100, BLACK), 50)
    print_metric("line(-50,-50 to 100,100)", elapsed)

    elapsed = avg_timed(lambda: fb.line(0, 0, fb.width + 100, fb.height + 100, BLACK), 20)
    print_metric("line(extends past bounds)", elapsed)

    fb.clear()
    print_separator()


def bench_rectangles(fb) -> None:
    """Benchmark rectangle drawing."""
    print_header("SHAPES: RECTANGLES")

    from framebuffer import BLACK

    fb.clear()

    print_subheader("Outline rectangles (4 lines)")

    elapsed = avg_timed(lambda: fb.rect(10, 10, 20, 20, BLACK), 100)
    print_metric("rect(20x20)", elapsed)

    elapsed = avg_timed(lambda: fb.rect(10, 10, 50, 50, BLACK), 100)
    print_metric("rect(50x50)", elapsed)

    elapsed = avg_timed(lambda: fb.rect(10, 10, 100, 80, BLACK), 50)
    print_metric("rect(100x80)", elapsed)

    print_separator()
    print_subheader("Filled rectangles (scanline hlines)")

    elapsed = avg_timed(lambda: fb.fill_rect(10, 10, 20, 20, BLACK), 50)
    print_metric("fill_rect(20x20)", elapsed)

    elapsed = avg_timed(lambda: fb.fill_rect(10, 10, 50, 50, BLACK), 20)
    print_metric("fill_rect(50x50)", elapsed)

    elapsed = avg_timed(lambda: fb.fill_rect(10, 10, 100, 80, BLACK), 10)
    print_metric("fill_rect(100x80)", elapsed)

    fb.clear()
    print_separator()


def bench_circles(fb) -> None:
    """Benchmark circle drawing (Bresenham in v2)."""
    print_header("SHAPES: CIRCLES (Bresenham)")

    from framebuffer import BLACK

    fb.clear()
    cx, cy = fb.width // 2, fb.height // 2

    print("v2 uses Bresenham's circle algorithm (integer only, no sqrt).")
    print()

    print_subheader("Outline circles")

    elapsed = avg_timed(lambda: fb.circle(cx, cy, 10, BLACK), 100)
    print_metric("circle(r=10)", elapsed)

    elapsed = avg_timed(lambda: fb.circle(cx, cy, 30, BLACK), 50)
    print_metric("circle(r=30)", elapsed)

    elapsed = avg_timed(lambda: fb.circle(cx, cy, 50, BLACK), 20)
    print_metric("circle(r=50)", elapsed)

    print_separator()
    print_subheader("Filled circles (Bresenham + vlines)")

    elapsed = avg_timed(lambda: fb.fill_circle(cx, cy, 10, BLACK), 50)
    print_metric("fill_circle(r=10)", elapsed)

    elapsed = avg_timed(lambda: fb.fill_circle(cx, cy, 30, BLACK), 20)
    print_metric("fill_circle(r=30)", elapsed)

    elapsed = avg_timed(lambda: fb.fill_circle(cx, cy, 50, BLACK), 10)
    print_metric("fill_circle(r=50)", elapsed)

    fb.clear()
    print_separator()


def bench_triangles(fb) -> None:
    """Benchmark triangle drawing."""
    print_header("SHAPES: TRIANGLES")

    from framebuffer import BLACK

    fb.clear()

    print_subheader("Outline triangles (3 lines)")

    # Small triangle
    elapsed = avg_timed(lambda: fb.triangle(10, 10, 40, 50, 60, 20, BLACK), 50)
    print_metric("triangle(small)", elapsed)

    # Large triangle
    elapsed = avg_timed(lambda: fb.triangle(10, 10, 150, 100, 200, 30, BLACK), 20)
    print_metric("triangle(large)", elapsed)

    print_separator()
    print_subheader("Filled triangles (scanline)")

    elapsed = avg_timed(lambda: fb.fill_triangle(10, 10, 40, 50, 60, 20, BLACK), 20)
    print_metric("fill_triangle(small)", elapsed)

    elapsed = avg_timed(lambda: fb.fill_triangle(10, 10, 150, 100, 200, 30, BLACK), 10)
    print_metric("fill_triangle(large)", elapsed)

    fb.clear()
    print_separator()


def bench_rounded_rect(fb) -> None:
    """Benchmark rounded rectangle drawing."""
    print_header("SHAPES: ROUNDED RECTANGLES")

    from framebuffer import BLACK

    fb.clear()

    elapsed = avg_timed(lambda: fb.rounded_rect(10, 10, 60, 40, 5, BLACK), 50)
    print_metric("rounded_rect(60x40, r=5)", elapsed)

    elapsed = avg_timed(lambda: fb.rounded_rect(10, 10, 100, 60, 10, BLACK), 20)
    print_metric("rounded_rect(100x60, r=10)", elapsed)

    elapsed = avg_timed(lambda: fb.rounded_rect(10, 10, 150, 80, 15, BLACK), 20)
    print_metric("rounded_rect(150x80, r=15)", elapsed)

    fb.clear()
    print_separator()


def bench_blit(fb) -> None:
    """Benchmark bitmap blitting."""
    print_header("SHAPES: BLIT")

    from framebuffer import BLACK

    fb.clear()

    # Create realistic test patterns (checkerboard - 50% fill)
    def make_checkerboard(w, h):
        """Create checkerboard pattern bitmap."""
        row_bytes = (w + 7) // 8
        data = bytearray(row_bytes * h)
        for row in range(h):
            pattern = 0xAA if row % 2 == 0 else 0x55
            for col in range(row_bytes):
                data[row * row_bytes + col] = pattern
        return bytes(data)

    bitmap_16 = make_checkerboard(16, 16)   # 32 bytes, 128 pixels to draw
    bitmap_32 = make_checkerboard(32, 32)   # 128 bytes, 512 pixels to draw
    bitmap_64 = make_checkerboard(64, 64)   # 512 bytes, 2048 pixels to draw

    print("Note: Using checkerboard pattern (50% pixel density).")
    print()

    elapsed = avg_timed(lambda: fb.blit(bitmap_16, 0, 0, 16, 16, BLACK), 50)
    print_metric("blit(16x16) 128 pixels", elapsed)

    elapsed = avg_timed(lambda: fb.blit(bitmap_32, 0, 0, 32, 32, BLACK), 20)
    print_metric("blit(32x32) 512 pixels", elapsed)

    elapsed = avg_timed(lambda: fb.blit(bitmap_64, 0, 0, 64, 64, BLACK), 10)
    print_metric("blit(64x64) 2048 pixels", elapsed)

    # Compare with equivalent pixel() calls for context
    print_separator()
    print_subheader("Blit vs manual pixel drawing (64x64)")

    # Pre-compute coordinates for fair comparison
    coords = [(x, y) for y in range(64) for x in range(64) if (x + y) % 2 == 0]

    def manual_pixels():
        for x, y in coords:
            fb.pixel_fast(x, y, BLACK)

    elapsed_blit = avg_timed(lambda: fb.blit(bitmap_64, 0, 0, 64, 64, BLACK), 5)
    elapsed_manual = avg_timed(manual_pixels, 5)

    print_metric("blit(64x64)", elapsed_blit)
    print_metric("manual pixel_fast() x2048", elapsed_manual)

    fb.clear()
    print_separator()
