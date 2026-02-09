"""
Benchmark Utilities (v2)
========================
Shared timing and output functions for lib_v2 benchmarks.
"""

import gc
import time

BENCHMARK_VERSION = "2.0.0-v2"


def mem_free() -> int:
    """Get free memory in bytes."""
    gc.collect()
    return gc.mem_free()


def timed(func, *args, **kwargs):
    """Run function and return (result, elapsed_ms)."""
    gc.collect()
    start = time.monotonic_ns()
    result = func(*args, **kwargs)
    elapsed = (time.monotonic_ns() - start) / 1_000_000
    return result, elapsed


def avg_timed(func, iterations, *args, **kwargs):
    """Run function N times and return average time in ms."""
    gc.collect()
    total = 0
    for _ in range(iterations):
        start = time.monotonic_ns()
        func(*args, **kwargs)
        total += time.monotonic_ns() - start
    return total / iterations / 1_000_000


def print_header(title: str) -> None:
    """Print section header."""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_metric(name: str, value: float | int | str, unit: str = "ms") -> None:
    """Print a metric in consistent format."""
    if isinstance(value, float):
        print(f"  {name:<40} {value:>10.2f} {unit}")
    else:
        print(f"  {name:<40} {value:>10} {unit}")


def print_separator() -> None:
    print("-" * 60)


def print_subheader(text: str) -> None:
    """Print a sub-section header."""
    print(f"  {text}:")


def ensure_basemap(canvas) -> None:
    """Ensure basemap is established for partial updates."""
    canvas.clear()
    canvas.full_refresh()
