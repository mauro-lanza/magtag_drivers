"""
End-to-End Workflow Benchmarks (v2)
===================================
Tests realistic usage patterns that combine drawing and display updates.
Adapted for v2 API.
"""

from utils import (
    print_header, print_metric, print_separator,
    timed, ensure_basemap
)


def run(canvas) -> None:
    """Run workflow benchmarks."""
    ensure_basemap(canvas)

    bench_info_screen(canvas)
    bench_flashcard(canvas)
    bench_counter_animation(canvas)
    bench_menu_scroll(canvas)


def bench_info_screen(canvas) -> None:
    """Benchmark drawing a typical information screen."""
    print_header("WORKFLOW: INFO SCREEN")

    from framebuffer import BLACK

    print("Simulates a status display: title, box, multiple text lines, icon.")
    print()

    def draw_and_update():
        canvas.clear()
        canvas.text("System Status", canvas.width // 2, 8, BLACK, align="center")
        canvas.hline(10, 22, canvas.width - 20, BLACK)
        canvas.rect(15, 30, canvas.width - 30, 70, BLACK)
        canvas.text("CPU: 45%", 25, 40, BLACK)
        canvas.text("RAM: 128KB free", 25, 55, BLACK)
        canvas.text("Uptime: 3h 42m", 25, 70, BLACK)
        canvas.fill_circle(canvas.width - 35, 85, 12, BLACK)
        canvas.partial_refresh()

    ensure_basemap(canvas)
    _, elapsed = timed(draw_and_update)
    print_metric("Draw + partial update", elapsed)

    # Breakdown: drawing only
    def draw_only():
        canvas.clear()
        canvas.text("System Status", canvas.width // 2, 8, BLACK, align="center")
        canvas.hline(10, 22, canvas.width - 20, BLACK)
        canvas.rect(15, 30, canvas.width - 30, 70, BLACK)
        canvas.text("CPU: 45%", 25, 40, BLACK)
        canvas.text("RAM: 128KB free", 25, 55, BLACK)
        canvas.text("Uptime: 3h 42m", 25, 70, BLACK)
        canvas.fill_circle(canvas.width - 35, 85, 12, BLACK)

    _, draw_time = timed(draw_only)
    print_metric("  Drawing only", draw_time)
    print_metric("  Display refresh", elapsed - draw_time)

    print_separator()


def bench_flashcard(canvas) -> None:
    """Benchmark flashcard-style content replacement."""
    print_header("WORKFLOW: FLASHCARD")

    from framebuffer import BLACK, WHITE

    print("Simulates clearing a content area and drawing new text (Anki-style).")
    print()

    # Initial card
    canvas.clear()
    canvas.rect(10, 10, canvas.width - 20, canvas.height - 20, BLACK)
    canvas.text("Question:", 20, 20, BLACK)
    canvas.text("What is the capital", 30, 45, BLACK)
    canvas.text("of France?", 30, 60, BLACK)
    ensure_basemap(canvas)

    # Flip to answer
    def flip_card():
        canvas.fill_rect(15, 35, canvas.width - 30, 60, WHITE)  # Clear content
        canvas.text("Answer:", 20, 40, BLACK)
        canvas.text("Paris", canvas.width // 2, 65, BLACK, align="center", scale=2)
        canvas.partial_refresh()

    _, elapsed = timed(flip_card)
    print_metric("Card flip (partial)", elapsed)

    # Next card (full redraw)
    def next_card():
        canvas.clear()
        canvas.rect(10, 10, canvas.width - 20, canvas.height - 20, BLACK)
        canvas.text("Question:", 20, 20, BLACK)
        canvas.text("What is 2 + 2?", 30, 50, BLACK)
        canvas.partial_refresh()

    _, elapsed = timed(next_card)
    print_metric("Next card (full redraw)", elapsed)

    print_separator()


def bench_counter_animation(canvas) -> None:
    """Benchmark region-based counter updates."""
    print_header("WORKFLOW: COUNTER ANIMATION")

    from framebuffer import BLACK, WHITE

    print("Uses update_region() for efficient small-area updates.")
    print("Common pattern for clocks, timers, counters.")
    print()

    # Setup: draw static frame
    canvas.clear()
    canvas.text("Counter Demo", 10, 10, BLACK)
    canvas.rect(90, 45, 80, 40, BLACK)
    ensure_basemap(canvas)

    # Update counter region
    times = []
    for i in range(5):
        canvas.fill_rect(96, 48, 72, 32, WHITE)  # Clear
        canvas.text(f"{i:03d}", 105, 52, BLACK, scale=2)
        _, elapsed = timed(canvas.update_region, 88, 40, 80, 48)  # 8-aligned
        times.append(elapsed)

    print_metric("Region updates (5x)", sum(times))
    print_metric("  Average", sum(times) / 5)
    print_metric("  Min", min(times))
    print_metric("  Max", max(times))

    print_separator()


def bench_menu_scroll(canvas) -> None:
    """Benchmark menu scrolling with partial updates."""
    print_header("WORKFLOW: MENU SCROLL")

    from framebuffer import BLACK, WHITE

    print("Simulates scrolling through a menu list.")
    print()

    menu_items = [
        "Settings",
        "WiFi Config",
        "Display Options",
        "Power Management",
        "About",
    ]

    def draw_menu(selected):
        canvas.clear()
        canvas.text("Menu", canvas.width // 2, 5, BLACK, align="center")
        canvas.hline(10, 18, canvas.width - 20, BLACK)
        for i, item in enumerate(menu_items):
            y = 25 + i * 18
            if i == selected:
                canvas.fill_rect(10, y - 2, canvas.width - 20, 16, BLACK)
                canvas.text(f"> {item}", 15, y, WHITE)
            else:
                canvas.text(f"  {item}", 15, y, BLACK)

    # Initial draw
    draw_menu(0)
    ensure_basemap(canvas)

    # Scroll down through menu
    times = []
    for i in range(1, 5):
        draw_menu(i)
        _, elapsed = timed(canvas.partial_refresh)
        times.append(elapsed)

    print_metric("Menu scrolls (4x)", sum(times))
    print_metric("  Average", sum(times) / 4)

    # Clean up
    canvas.sleep()

    print_separator()
