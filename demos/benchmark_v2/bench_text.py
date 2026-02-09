"""
Text Rendering Benchmarks (v2)
==============================
Tests font loading, glyph caching, text drawing, and measurement.
Adapted for v2 API: simplified text API, font patching via add_font().

Note: v2 removed word wrapping and text_box, so those benchmarks are omitted.
"""

import gc
from utils import (
    print_header, print_metric, print_separator, print_subheader,
    timed, avg_timed
)


def run(canvas) -> None:
    """Run text rendering benchmarks."""
    bench_font_loading(canvas)
    bench_text_cold_cache(canvas)
    bench_text_warm_cache(canvas)
    bench_text_scaled(canvas)
    bench_text_measurement(canvas)
    bench_text_alignment(canvas)
    bench_font_patching(canvas)
    bench_preload_glyphs(canvas)


def bench_font_loading(canvas) -> None:
    """Benchmark font loading operations."""
    print_header("TEXT: FONT LOADING")

    default_font = "/lib/fonts/cozette.bf2"

    # Standard font
    gc.collect()
    _, elapsed = timed(canvas.load_font, default_font)
    print_metric("load_font(cozette.bf2)", elapsed)

    # Reload same font (measures file I/O + parsing)
    gc.collect()
    _, elapsed = timed(canvas.load_font, default_font)
    print_metric("load_font() [reload same]", elapsed)

    print_separator()


def bench_text_cold_cache(canvas) -> None:
    """Benchmark text drawing with cold (empty) glyph cache."""
    print_header("TEXT: COLD CACHE")

    from framebuffer import BLACK

    default_font = "/lib/fonts/cozette.bf2"
    tr = canvas._text

    print("Cache cleared before each test - measures file I/O for glyph loading.")
    print()

    # Short string - 5 unique glyphs
    canvas.load_font(default_font)
    tr._cache.clear()
    tr._cache_size = 0
    canvas.clear()
    _, elapsed = timed(canvas.text, "Hello", 10, 10, BLACK)
    print_metric("'Hello' (5 glyphs)", elapsed)

    # Pangram - many unique letters
    tr._cache.clear()
    tr._cache_size = 0
    canvas.clear()
    _, elapsed = timed(canvas.text, "The quick brown fox", 10, 30, BLACK)
    print_metric("'The quick brown fox' (16 unique)", elapsed)

    # Numbers and punctuation
    tr._cache.clear()
    tr._cache_size = 0
    canvas.clear()
    _, elapsed = timed(canvas.text, "12:34:56 PM - 2024/01/14", 10, 50, BLACK)
    print_metric("datetime string (15 unique)", elapsed)

    print_separator()


def bench_text_warm_cache(canvas) -> None:
    """Benchmark text drawing with warm (populated) glyph cache."""
    print_header("TEXT: WARM CACHE")

    from framebuffer import BLACK

    print("Same glyphs rendered repeatedly - measures pure rendering speed.")
    print()

    # Warm cache
    canvas.clear()
    canvas.text("Hello", 10, 10, BLACK)
    canvas.text("The quick brown fox", 10, 30, BLACK)

    elapsed = avg_timed(lambda: canvas.text("Hello", 10, 50, BLACK), 50)
    print_metric("'Hello' (cached)", elapsed)

    elapsed = avg_timed(lambda: canvas.text("The quick brown fox", 10, 70, BLACK), 20)
    print_metric("'The quick brown fox' (cached)", elapsed)

    # Repeated character (worst case for proportional width lookup)
    canvas.text("WWWWWWWWWW", 10, 90, BLACK)
    elapsed = avg_timed(lambda: canvas.text("WWWWWWWWWW", 10, 90, BLACK), 50)
    print_metric("'WWWWWWWWWW' (10 same chars)", elapsed)

    canvas.clear()
    print_separator()


def bench_text_scaled(canvas) -> None:
    """Benchmark scaled text rendering."""
    print_header("TEXT: SCALED RENDERING")

    from framebuffer import BLACK

    print("Scaled text renders each pixel as a filled rectangle.")
    print()

    canvas.clear()

    # Ensure glyphs are cached
    canvas.text("Test", 0, 0, BLACK)

    elapsed = avg_timed(lambda: canvas.text("Test", 10, 10, BLACK, scale=1), 50)
    print_metric("'Test' scale=1 (baseline)", elapsed)

    elapsed = avg_timed(lambda: canvas.text("Test", 10, 30, BLACK, scale=2), 20)
    print_metric("'Test' scale=2", elapsed)

    elapsed = avg_timed(lambda: canvas.text("Test", 10, 60, BLACK, scale=3), 10)
    print_metric("'Test' scale=3", elapsed)

    elapsed = avg_timed(lambda: canvas.text("Test", 10, 100, BLACK, scale=4), 10)
    print_metric("'Test' scale=4", elapsed)

    canvas.clear()
    print_separator()


def bench_text_measurement(canvas) -> None:
    """Benchmark text measurement (no drawing)."""
    print_header("TEXT: MEASUREMENT")

    print("Measurement only - no pixel drawing, just width calculation.")
    print()

    elapsed = avg_timed(lambda: canvas.measure_text("Hello"), 200)
    print_metric("measure_text('Hello')", elapsed)

    elapsed = avg_timed(lambda: canvas.measure_text("The quick brown fox jumps"), 100)
    print_metric("measure_text(25 chars)", elapsed)

    elapsed = avg_timed(lambda: canvas.measure_text("A" * 50), 50)
    print_metric("measure_text(50 chars)", elapsed)

    print_separator()


def bench_text_alignment(canvas) -> None:
    """Benchmark text alignment options."""
    print_header("TEXT: ALIGNMENT")

    from framebuffer import BLACK

    canvas.clear()

    # Ensure glyphs are cached
    canvas.text("Centered Text", 0, 0, BLACK, align="center")

    elapsed = avg_timed(lambda: canvas.text("Left", 10, 10, BLACK, align="left"), 50)
    print_metric("align='left'", elapsed)

    elapsed = avg_timed(lambda: canvas.text("Center", canvas.width // 2, 30, BLACK, align="center"), 50)
    print_metric("align='center'", elapsed)

    elapsed = avg_timed(lambda: canvas.text("Right", canvas.width - 10, 50, BLACK, align="right"), 50)
    print_metric("align='right'", elapsed)

    canvas.clear()
    print_separator()


def bench_font_patching(canvas) -> None:
    """Benchmark v2's font patching feature (add_font)."""
    print_header("TEXT: FONT PATCHING (v2 feature)")

    default_font = "/lib/fonts/cozette.bf2"

    print("Font patching allows layering multiple fonts (e.g., icons on top of text).")
    print()

    # Load base font
    gc.collect()
    _, elapsed = timed(canvas.load_font, default_font)
    print_metric("load_font() [base]", elapsed)

    # Add a patch font (same font for benchmark, real use would be icons)
    gc.collect()
    _, elapsed = timed(canvas.add_font, default_font)
    print_metric("add_font() [patch]", elapsed)

    # Glyph lookup with 2 fonts loaded
    from framebuffer import BLACK
    canvas.text("Test", 0, 0, BLACK)  # Warm cache

    elapsed = avg_timed(lambda: canvas.text("Test", 10, 10, BLACK), 50)
    print_metric("text() [2 fonts loaded]", elapsed)

    # Reset to single font
    canvas.load_font(default_font)

    print_separator()


def bench_preload_glyphs(canvas) -> None:
    """Benchmark explicit glyph preloading (v2 feature)."""
    print_header("TEXT: PRELOAD_GLYPHS (v2 feature)")

    default_font = "/lib/fonts/cozette.bf2"
    tr = canvas._text

    print("preload_glyphs() allows pre-warming the cache to avoid rendering lag.")
    print()

    # Clear cache
    canvas.load_font(default_font)
    tr._cache.clear()
    tr._cache_size = 0

    # Preload common characters
    gc.collect()
    _, elapsed = timed(tr.preload_glyphs, "0123456789:APM ")
    print_metric("preload_glyphs('0-9:APM ')", elapsed)

    # Preload alphabet
    tr._cache.clear()
    tr._cache_size = 0
    gc.collect()
    _, elapsed = timed(tr.preload_glyphs, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    print_metric("preload_glyphs(A-Za-z)", elapsed)

    print_separator()
