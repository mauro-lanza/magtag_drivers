"""
Driver Demo - EPD Refresh Modes
===============================
Demonstrates full, partial, fast, and region refresh modes with timing benchmarks.
Measures both total time and actual display refresh time (BUSY duration).

Also demonstrates GxEPD2-aligned power management:
  - is_power_on(): Panel driving voltages state
  - is_hibernating(): Deep sleep state (requires reset to wake)
  - is_init_done(): Display initialization state
  - Automatic wake from hibernate on display_* calls
"""

import time
import shapes


def run(canvas, btns=None):
    """Run driver refresh mode demonstration."""
    epd = canvas.epd
    fb = canvas._fb

    print("\n--- Driver Demo: Refresh Modes ---")
    print("Measuring: Total time / BUSY time (actual refresh)")

    # Store timing results for summary
    timings = {}

    # Test 1: Full refresh benchmark
    print("\nFull refresh benchmark (4 iterations)...")
    total_times = []
    refresh_times = []
    for i in range(4):
        fb.clear(black=(i % 2 == 0))
        shapes.fill_rect(fb, 50, 30, 200, 68, black=(i % 2 == 1))
        start = time.monotonic()
        refresh_t = epd.display_full(fb.buffer)
        total_t = time.monotonic() - start
        total_times.append(total_t)
        refresh_times.append(refresh_t)
        print(f"  Run {i + 1}: {total_t:.2f}s total, {refresh_t:.2f}s refresh")

    avg_total = sum(total_times) / len(total_times)
    avg_refresh = sum(refresh_times) / len(refresh_times)
    timings['full'] = (avg_total, avg_refresh)
    print(f"  Average: {avg_total:.2f}s total, {avg_refresh:.2f}s refresh")

    # Test 2: Partial refresh benchmark
    print("\nPartial refresh benchmark (9 iterations)...")
    fb.clear()
    epd.display_full(fb.buffer)

    total_times = []
    refresh_times = []
    for i in range(9):
        fb.clear()
        x = 20 + (i % 3) * 90
        shapes.fill_rect(fb, x, 30, 70, 68, black=True)
        start = time.monotonic()
        refresh_t = epd.display_partial(fb.buffer)
        total_t = time.monotonic() - start
        total_times.append(total_t)
        refresh_times.append(refresh_t)
        print(f"  Run {i + 1}: {total_t:.2f}s total, {refresh_t:.2f}s refresh")

    avg_total = sum(total_times) / len(total_times)
    avg_refresh = sum(refresh_times) / len(refresh_times)
    timings['partial'] = (avg_total, avg_refresh)
    print(f"  Average: {avg_total:.2f}s total, {avg_refresh:.2f}s refresh")

    # Test 3: Region partial refresh benchmark
    print("\nRegion partial refresh benchmark (9 iterations)...")
    fb.clear()
    shapes.rect(fb, 10, 10, fb.width - 20, fb.height - 20)  # Frame border
    shapes.fill_rect(fb, 16, 32, 72, 64)  # Static box on left (same size as update region)
    epd.display_full(fb.buffer)

    # Update region on the right side (x must be multiple of 8)
    region_x, region_y, region_w, region_h = 208, 32, 72, 64

    total_times = []
    refresh_times = []
    for i in range(9):
        shapes.fill_rect(fb, region_x, region_y, region_w, region_h, black=False)  # Clear region
        if i % 2 == 0:
            shapes.fill_rect(fb, region_x + 8, region_y + 8, region_w - 16, region_h - 16)  # Filled
        else:
            shapes.rect(fb, region_x + 8, region_y + 8, region_w - 16, region_h - 16)  # Outline
            shapes.line(fb, region_x + 8, region_y + 8, region_x + region_w - 8, region_y + region_h - 8)

        start = time.monotonic()
        refresh_t = canvas.update_region(region_x, region_y, region_w, region_h)
        total_t = time.monotonic() - start
        total_times.append(total_t)
        refresh_times.append(refresh_t)
        print(f"  Run {i + 1}: {total_t:.2f}s total, {refresh_t:.2f}s refresh")

    avg_total = sum(total_times) / len(total_times)
    avg_refresh = sum(refresh_times) / len(refresh_times)
    timings['region'] = (avg_total, avg_refresh)
    print(f"  Average: {avg_total:.2f}s total, {avg_refresh:.2f}s refresh")

    # Test 4: Multi-region batch refresh benchmark
    print("\nMulti-region batch refresh benchmark (4 iterations)...")
    fb.clear()
    shapes.rect(fb, 10, 10, fb.width - 20, fb.height - 20)
    epd.display_full(fb.buffer)

    # Three regions across the screen, vertically centered
    # All x values and widths must be multiples of 8
    regions = [
        (16, 32, 72, 64),    # Left region
        (112, 32, 72, 64),   # Center region
        (208, 32, 72, 64),   # Right region
    ]

    total_times = []
    refresh_times = []
    for i in range(4):
        for rx, ry, rw, rh in regions:
            shapes.fill_rect(fb, rx, ry, rw, rh, black=False)  # Clear region
            if i % 2 == 0:
                shapes.fill_rect(fb, rx + 8, ry + 8, rw - 16, rh - 16)  # Filled box
            else:
                shapes.rect(fb, rx + 8, ry + 8, rw - 16, rh - 16)  # Outline
                shapes.line(fb, rx + 8, ry + 8, rx + rw - 8, ry + rh - 8)  # Diagonal

        start = time.monotonic()
        refresh_t = canvas.update_regions(regions)
        total_t = time.monotonic() - start
        total_times.append(total_t)
        refresh_times.append(refresh_t)
        print(f"  Run {i + 1}: {total_t:.2f}s total, {refresh_t:.2f}s refresh (3 regions)")

    avg_total = sum(total_times) / len(total_times)
    avg_refresh = sum(refresh_times) / len(refresh_times)
    timings['multi'] = (avg_total, avg_refresh)
    print(f"  Average: {avg_total:.2f}s total, {avg_refresh:.2f}s refresh")

    # Test 5: Fast refresh benchmark
    print("\nFast refresh benchmark (4 iterations)...")
    total_times = []
    refresh_times = []
    for i in range(4):
        fb.clear(black=(i % 2 == 0))
        # 8 stripes of 18px with 19px gaps = 8*37 = 296px exactly
        for x in range(0, fb.width, 37):
            shapes.fill_rect(fb, x, 0, 18, fb.height, black=(i % 2 == 1))
        start = time.monotonic()
        refresh_t = epd.display_full(fb.buffer, fast=True)
        total_t = time.monotonic() - start
        total_times.append(total_t)
        refresh_times.append(refresh_t)
        print(f"  Run {i + 1}: {total_t:.2f}s total, {refresh_t:.2f}s refresh")

    avg_total = sum(total_times) / len(total_times)
    avg_refresh = sum(refresh_times) / len(refresh_times)
    timings['fast'] = (avg_total, avg_refresh)
    print(f"  Average: {avg_total:.2f}s total, {avg_refresh:.2f}s refresh")

    # Test 6: Power control test
    print("\nPower control test...")

    fb.clear()
    shapes.fill_rect(fb, 100, 40, 96, 48)
    epd.display_full(fb.buffer)
    print(f"  After full refresh: power={'ON' if epd.is_power_on() else 'OFF'}, hibernating={epd.is_hibernating()}")

    shapes.fill_rect(fb, 50, 40, 48, 48)
    epd.display_partial(fb.buffer)
    print(f"  After partial refresh: power={'ON' if epd.is_power_on() else 'OFF'}, init_done={epd.is_init_done()}")

    start = time.monotonic()
    epd.power_off()
    power_off_time = time.monotonic() - start
    print(f"  Power off: {power_off_time:.3f}s, now power={'ON' if epd.is_power_on() else 'OFF'}")

    start = time.monotonic()
    epd.power_on()
    power_on_time = time.monotonic() - start
    print(f"  Power on:  {power_on_time:.3f}s, now power={'ON' if epd.is_power_on() else 'OFF'}")

    # Test sleep/hibernate cycle
    print("\n  Sleep/wake cycle:")
    epd.sleep()
    print(f"    After sleep: hibernating={epd.is_hibernating()}, init_done={epd.is_init_done()}")

    fb.clear()
    shapes.fill_rect(fb, 150, 40, 48, 48)
    epd.display_partial(fb.buffer)  # Should auto-wake and do full refresh (first after hibernate)
    print(f"    After partial (woke from hibernate): hibernating={epd.is_hibernating()}, init_done={epd.is_init_done()}")

    timings['power_off'] = power_off_time
    timings['power_on'] = power_on_time

    # Summary screen
    canvas.clear()
    canvas.text("REFRESH BENCHMARKS", canvas.width // 2, 2, align="center")
    canvas.hline(10, 16, canvas.width - 20)

    canvas.text("Mode", 10, 20)
    canvas.text("Total", 150, 20)
    canvas.text("Busy", 220, 20)

    y = 36
    for label, key in [("Full:", 'full'),
                       ("Partial:", 'partial'),
                       ("Region:", 'region'),
                       ("Multi (3x):", 'multi'),
                       ("Fast:", 'fast')]:
        total_t, refresh_t = timings[key]
        canvas.text(label, 10, y)
        canvas.text(f"{total_t:.2f}s", 150, y)
        canvas.text(f"{refresh_t:.2f}s", 220, y)
        y += 16

    canvas.hline(10, y + 2, canvas.width - 20)
    canvas.text("Press any button", canvas.width // 2, y + 8, align="center")
    canvas.update("full")

    print("\n--- Benchmark Results ---")
    print("              Total    Refresh (BUSY)")
    for name, key in [("Full", 'full'), ("Partial", 'partial'),
                      ("Region", 'region'), ("Multi 3x", 'multi'), ("Fast", 'fast')]:
        total_t, refresh_t = timings[key]
        print(f"  {name:10} {total_t:.2f}s    {refresh_t:.2f}s")
    print(f"\n  Power on:      {timings['power_on']:.3f}s")
    print(f"  Power off:     {timings['power_off']:.3f}s")
    print("\nPress any button to return...")

    if btns:
        btns.wait()
