"""
EPD Driver Benchmarks (v2)
==========================
Tests EPD hardware operations: initialization, refresh modes, region updates,
power management, 4-gray mode, and v2-specific features.

v2 Features Tested:
  - fast_clear(): Hardware-accelerated display clear
  - read_temperature() / check_temperature(): Internal sensor access
  - update_fast_safe(): Temperature-aware fast refresh
  - update_regions(): Batch region updates
  - invert_display(): Hardware display inversion

GxEPD2 Comparison Tests:
  - Update sequence values (0xF7 vs 0xD7)
  - Temperature trick approaches
  - Soft Start register effects
  - Border waveform settings
  - RAM write patterns (differential vs sync-after)

Adapted for lib_v2 API (Canvas-centric, display() with full/fast params).
"""

import gc
import time
from utils import (
    print_header, print_metric, print_separator, print_subheader,
    timed, ensure_basemap
)


def run(canvas, buttons=None) -> None:
    """Run EPD driver benchmarks.

    Args:
        canvas: Canvas instance
        buttons: Optional Buttons instance for interactive mode
    """
    bench_refresh_modes(canvas)
    bench_fast_clear(canvas)
    bench_temperature(canvas)
    bench_partial_consistency(canvas)
    bench_partial_cached_temp(canvas)
    bench_region_updates(canvas)
    bench_batch_region_updates(canvas)
    bench_4gray(canvas)
    bench_power_states(canvas)
    bench_hardware_inversion(canvas)

    # GxEPD2 comparison benchmarks
    bench_gxepd2_update_sequences(canvas)
    bench_gxepd2_temp_trick(canvas)
    bench_gxepd2_soft_start(canvas)
    bench_gxepd2_border_waveform(canvas)
    bench_gxepd2_ram_patterns(canvas)
    bench_gxepd2_full_comparison(canvas)


def bench_refresh_modes(canvas) -> None:
    """Benchmark display refresh modes."""
    print_header("EPD: REFRESH MODES")

    from framebuffer import BLACK

    print("Tests explicit refresh methods:")
    print("  full_refresh() - always sleeps after")
    print("  partial_refresh() - stays awake for fast consecutive updates")
    print()

    # Prepare test pattern
    canvas.clear()
    canvas.fill_rect(10, 10, 100, 50, BLACK)
    canvas.text("Benchmark", 50, 70, BLACK)

    # Full refresh (standard)
    _, elapsed = timed(canvas.full_refresh)
    print_metric("full_refresh()", elapsed)

    # Partial refresh - stays awake
    ensure_basemap(canvas)
    canvas.fill_rect(10, 70, 50, 30, BLACK)
    _, elapsed = timed(canvas.partial_refresh)
    print_metric("partial_refresh()", elapsed)

    # Second partial (already awake - fastest)
    canvas.fill_rect(70, 70, 50, 30, BLACK)
    _, elapsed = timed(canvas.partial_refresh)
    print_metric("partial_refresh() [consecutive]", elapsed)

    # Cleanup: sleep before next test
    canvas.sleep()

    print_separator()




def bench_fast_clear(canvas) -> None:
    """Benchmark hardware-accelerated display clear (v2 feature)."""
    print_header("EPD: FAST_CLEAR (v2 feature)")

    from framebuffer import WHITE, BLACK

    print("fast_clear() uses EPD's auto-fill feature to clear both RAM and display")
    print("without sending 4736 bytes over SPI. Much faster than clear() + update().")
    print()

    # Benchmark fast_clear to white
    _, elapsed = timed(canvas.fast_clear, WHITE)
    print_metric("fast_clear(WHITE)", elapsed)

    # Benchmark fast_clear to black
    _, elapsed = timed(canvas.fast_clear, BLACK)
    print_metric("fast_clear(BLACK)", elapsed)

    # Compare with traditional clear + update
    def traditional_clear():
        canvas.clear(WHITE)
        canvas.full_refresh()

    _, elapsed_traditional = timed(traditional_clear)
    print_metric("clear() + full_refresh() [traditional]", elapsed_traditional)

    print_separator()


def bench_temperature(canvas) -> None:
    """Benchmark temperature sensor operations (v2 feature)."""
    print_header("EPD: TEMPERATURE SENSOR (v2 feature)")

    print("SSD1680 has a built-in temperature sensor (±2°C accuracy).")
    print("Temperature affects waveform selection and enables safe fast mode.")
    print()

    # First read (may need wake from sleep)
    _, elapsed = timed(canvas.read_temperature)
    print_metric("read_temperature() [cold]", elapsed)

    # Subsequent reads (already awake)
    _, elapsed = timed(canvas.read_temperature)
    print_metric("read_temperature() [warm]", elapsed)

    # Check temperature with range validation
    result, elapsed = timed(canvas.check_temperature)
    temp, in_range = result
    print_metric("check_temperature()", elapsed)
    print_metric("  Actual temperature", f"{temp:.1f}", "°C")
    print_metric("  In safe range (0-50°C)", "Yes" if in_range else "No", "")

    print_separator()


def bench_partial_consistency(canvas) -> None:
    """Benchmark partial refresh consistency across multiple updates."""
    print_header("EPD: PARTIAL CONSISTENCY")

    from framebuffer import BLACK

    print("Consecutive partial_refresh() calls - display stays powered.")
    print()

    canvas.clear()
    ensure_basemap(canvas)

    times = []
    for i in range(5):
        canvas.fill_rect(10 + i * 25, 10, 20, 20, BLACK)
        _, elapsed = timed(canvas.partial_refresh)
        times.append(elapsed)
        print_metric(f"  partial #{i + 1}", elapsed)

    # Clean up - sleep after partial batch
    canvas.sleep()

    print_separator()
    print_metric("Average", sum(times) / len(times))
    print_metric("Min", min(times))
    print_metric("Max", max(times))
    print_metric("Variance", max(times) - min(times))

    print_separator()


def bench_partial_cached_temp(canvas) -> None:
    """Benchmark partial_refresh() vs wake-from-sleep overhead."""
    print_header("EPD: PARTIAL vs WAKE OVERHEAD")

    from framebuffer import BLACK

    print("Compares consecutive partials vs partials after sleep.")
    print("partial_refresh() stays awake - call sleep() when done.")
    print()

    # Test 1: Consecutive partials (display stays powered)
    print_subheader("Consecutive partial_refresh() calls")
    canvas.clear()
    ensure_basemap(canvas)

    times_awake = []
    for i in range(3):
        canvas.fill_rect(10 + i * 30, 50, 25, 25, BLACK)
        _, elapsed = timed(canvas.partial_refresh)
        times_awake.append(elapsed)
        print_metric(f"  partial #{i + 1}", elapsed)

    avg_awake = sum(times_awake) / len(times_awake)
    print_metric("Average (consecutive)", avg_awake)

    # Put display to sleep before next test
    canvas.sleep()

    # Test 2: Partial after sleep (must wake each time via deprecated API)
    print_separator()
    print_subheader("Partial after sleep (deprecated API)")
    canvas.clear()
    ensure_basemap(canvas)

    times_sleep = []
    for i in range(3):
        canvas.fill_rect(10 + i * 30, 80, 25, 25, BLACK)
        # Use deprecated update() to demonstrate wake overhead
        _, elapsed = timed(canvas.update, full=False, stay_awake=False)
        times_sleep.append(elapsed)
        print_metric(f"  partial #{i + 1}", elapsed)

    avg_sleep = sum(times_sleep) / len(times_sleep)
    print_metric("Average (sleep after each)", avg_sleep)

    # Comparison
    print_separator()
    print_subheader("Summary")
    print_metric("Consecutive avg", avg_awake)
    print_metric("Sleep-between avg", avg_sleep)
    if avg_sleep > 0:
        overhead = avg_sleep - avg_awake
        percent = (overhead / avg_sleep) * 100
        print_metric("Wake overhead per update", overhead)
        print_metric("Speedup", f"{percent:.1f}", "%")

    print()
    print("Use partial_refresh() + sleep() for fast updates with power savings.")
    print("Recommendation: Use default (stay_awake=True for partial).")
    print("Call sleep() when done with batch of updates to save power.")

    print_separator()


def bench_region_updates(canvas) -> None:
    """Benchmark region-based partial updates."""
    print_header("EPD: REGION UPDATES")

    from framebuffer import BLACK

    print("Region updates refresh only a rectangular area.")
    print("Coordinates must be 8-pixel aligned.")
    print()

    canvas.clear()
    ensure_basemap(canvas)

    # Various region sizes
    regions = [
        (0, 0, 32, 32, "32x32 (small icon)"),
        (0, 0, 64, 32, "64x32 (status bar)"),
        (0, 0, 128, 64, "128x64 (quarter screen)"),
    ]

    for x, y, w, h, desc in regions:
        try:
            # Clear and draw fresh pattern for each region
            canvas.clear()
            canvas.fill_rect(x + 2, y + 2, w - 4, h - 4, BLACK)
            ensure_basemap(canvas)

            # Use canvas method (handles rotation)
            _, elapsed = timed(canvas.update_region, x, y, w, h)
            print_metric(f"update_region({desc})", elapsed)
        except Exception as e:
            print_metric(f"update_region({desc})", f"ERROR: {e}", "")

    # Test misaligned region (should raise error)
    print_separator()
    print_subheader("Misaligned region (error expected)")
    try:
        canvas.update_region(3, 0, 32, 32)  # x=3 not 8-aligned
        print_metric("update_region(x=3)", "NO ERROR (unexpected)", "")
    except ValueError:
        print_metric("update_region(x=3)", "ValueError (expected)", "")

    print_separator()


def bench_batch_region_updates(canvas) -> None:
    """Benchmark batch region updates (v2 feature)."""
    print_header("EPD: BATCH REGION UPDATES (v2 feature)")

    from framebuffer import BLACK

    print("update_regions() batches multiple region updates into one refresh.")
    print("More efficient than individual update_region() calls.")
    print()

    canvas.clear()
    ensure_basemap(canvas)

    # Draw multiple icons/elements
    canvas.fill_rect(10, 10, 24, 24, BLACK)   # Icon 1
    canvas.fill_rect(50, 10, 24, 24, BLACK)   # Icon 2
    canvas.fill_rect(90, 10, 24, 24, BLACK)   # Icon 3

    # Individual updates (baseline)
    print_subheader("Individual region updates (baseline)")
    total_individual = 0
    for i, (x, y) in enumerate([(8, 8), (48, 8), (88, 8)]):
        canvas.fill_rect(x + 2, y + 2, 20, 20, BLACK)
        _, elapsed = timed(canvas.update_region, x, y, 32, 32)
        total_individual += elapsed
        print_metric(f"  Region {i + 1}", elapsed)
    print_metric("Total (individual)", total_individual)

    # Re-establish basemap
    canvas.clear()
    ensure_basemap(canvas)

    # Batch update
    print_separator()
    print_subheader("Batch region update")
    canvas.fill_rect(10, 10, 24, 24, BLACK)
    canvas.fill_rect(50, 10, 24, 24, BLACK)
    canvas.fill_rect(90, 10, 24, 24, BLACK)

    regions = [(8, 8, 32, 32), (48, 8, 32, 32), (88, 8, 32, 32)]
    _, elapsed_batch = timed(canvas.update_regions, regions)
    print_metric("Total (batch)", elapsed_batch)

    # Comparison
    print_separator()
    if total_individual > 0:
        savings = total_individual - elapsed_batch
        speedup = (savings / total_individual) * 100
        print_metric("Time saved", savings)
        print_metric("Speedup", f"{speedup:.1f}", "%")

    print_separator()


def bench_4gray(canvas) -> None:
    """Benchmark 4-gray mode (v2 native 2-bit support)."""
    print_header("EPD: 4-GRAY MODE")

    print("v2 supports native 2-bit buffers with LUT-based plane conversion.")
    print("Note: This requires creating a depth=2 buffer.")
    print()

    from draw import DrawBuffer
    from framebuffer import BLACK, DARK_GRAY, LIGHT_GRAY, WHITE

    # Create 2-bit buffer
    gc.collect()
    mem_before = gc.mem_free()
    fb_gray = DrawBuffer(128, 296, depth=2, rotation=90)
    gc.collect()
    mem_after = gc.mem_free()
    print_metric("DrawBuffer(depth=2) creation", mem_before - mem_after, "bytes")

    # Draw grayscale pattern
    fb_gray.clear()
    fb_gray.fill_rect(10, 10, 50, 50, BLACK)
    fb_gray.fill_rect(70, 10, 50, 50, DARK_GRAY)
    fb_gray.fill_rect(130, 10, 50, 50, LIGHT_GRAY)
    fb_gray.fill_rect(190, 10, 50, 50, WHITE)

    # Benchmark to_planes() conversion
    gc.collect()
    _, elapsed = timed(fb_gray.to_planes)
    print_metric("to_planes() [LUT conversion]", elapsed)

    # Benchmark to_mono() conversion
    gc.collect()
    _, elapsed = timed(fb_gray.to_mono)
    print_metric("to_mono() [threshold]", elapsed)

    # Full 4-gray display (if EPD available via canvas)
    try:
        black_plane, red_plane = fb_gray.to_planes()
        epd = canvas._epd
        _, elapsed = timed(epd.display_gray, black_plane, red_plane)
        print_metric("display_gray() [4-gray refresh]", elapsed)
    except Exception as e:
        print_metric("display_gray()", f"ERROR: {e}", "")

    print_separator()


def bench_power_states(canvas) -> None:
    """Benchmark power management operations."""
    print_header("EPD: POWER MANAGEMENT")

    from framebuffer import BLACK

    print("Measures sleep/wake overhead.")
    print("full_refresh() always sleeps. partial_refresh() stays awake.")
    print()

    epd = canvas._epd

    # Ensure display is awake first
    canvas.clear()
    canvas.fill_rect(50, 50, 80, 40, BLACK)
    canvas.full_refresh()

    # Measure sleep command time (already asleep after full_refresh)
    # So let's do a partial first to wake it
    canvas.fill_rect(10, 10, 30, 30, BLACK)
    ensure_basemap(canvas)
    canvas.fill_rect(50, 10, 30, 30, BLACK)
    canvas.partial_refresh()  # Now awake

    gc.collect()
    start = time.monotonic_ns()
    canvas.sleep()
    elapsed_sleep = (time.monotonic_ns() - start) / 1_000_000
    print_metric("sleep()", elapsed_sleep)

    # Wake via full refresh
    canvas.clear()
    _, elapsed_wake_full = timed(canvas.full_refresh)
    print_metric("wake via full_refresh()", elapsed_wake_full)

    # After full_refresh, display is asleep. Partial wakes it.
    canvas.fill_rect(10, 50, 30, 30, BLACK)
    _, elapsed_wake_partial = timed(canvas.partial_refresh)
    print_metric("wake via partial_refresh()", elapsed_wake_partial)

    # Compare consecutive partials (no wake overhead)
    print_separator()
    print_subheader("Consecutive partials (already awake)")
    canvas.fill_rect(50, 50, 30, 30, BLACK)
    _, elapsed_partial_awake = timed(canvas.partial_refresh)
    print_metric("partial_refresh() [consecutive]", elapsed_partial_awake)

    # Clean up
    canvas.sleep()

    # Show the overhead
    print_separator()
    if elapsed_wake_partial > elapsed_partial_awake:
        overhead = elapsed_wake_partial - elapsed_partial_awake
        print_metric("Wake overhead (HW reset)", overhead)

    print_separator()


def bench_hardware_inversion(canvas) -> None:
    """Benchmark hardware display inversion (v2 feature)."""
    print_header("EPD: HARDWARE INVERSION (v2 feature)")

    from framebuffer import BLACK

    print("invert_display() uses SSD1680's hardware inversion register.")
    print("Instant toggle without buffer modification - perfect for dark mode.")
    print()

    # Draw test pattern
    canvas.clear()
    canvas.text("Normal Mode", canvas.width // 2, 30, BLACK, align="center")
    canvas.fill_rect(50, 60, 80, 40, BLACK)
    ensure_basemap(canvas)

    # Toggle hardware inversion (instant, no redraw needed)
    _, elapsed = timed(canvas.invert_display, True)
    print_metric("invert_display(True)", elapsed)

    # The actual change shows on next update
    _, elapsed = timed(canvas.partial_refresh)
    print_metric("partial_refresh() [show inversion]", elapsed)

    # Toggle back
    _, elapsed = timed(canvas.invert_display, False)
    print_metric("invert_display(False)", elapsed)

    _, elapsed = timed(canvas.partial_refresh)
    print_metric("partial_refresh() [restore normal]", elapsed)

    # Clean up
    canvas.sleep()

    # Compare with software inversion
    print_separator()
    print_subheader("Comparison: HW vs SW inversion")

    from utils import avg_timed

    # Hardware inversion timing (register write only)
    hw_time = avg_timed(lambda: canvas.invert_display(True), 50)
    print_metric("HW invert (register write)", hw_time)

    # Software inversion timing (XOR full buffer)
    fb = canvas._fb
    sw_time = avg_timed(fb.invert, 50)
    print_metric("SW invert (buffer XOR)", sw_time)

    # Ensure buffer is back to normal (even iterations)
    canvas.invert_display(False)

    print_separator()


# =============================================================================
# GxEPD2 vs Custom v2 Comparison Benchmarks
# =============================================================================

def bench_gxepd2_update_sequences(canvas) -> None:
    """
    Benchmark different update sequence values.

    Compares:
      - 0xF7: Standard full refresh (both libraries)
      - 0xD7: GxEPD2 fast mode (with temp trick)
      - 0xC7: Custom v2 fast mode (no temp read)
      - 0xFC: Partial refresh (both libraries)
      - 0xCC: Custom v2 partial fast (no temp read)
    """
    print_header("GxEPD2 COMPARISON: UPDATE SEQUENCES")

    from framebuffer import BLACK

    print("Update Control 2 (0x22) sequence values comparison.")
    print()
    print("  0xF7 = Clk→Analog→Temp→Mode1→Power Off (standard)")
    print("  0xD7 = Clk→Analog→Temp→Mode1 (GxEPD2 fast, skips some)")
    print("  0xC7 = Clk→Analog→Mode1→Power Off (custom fast, no temp)")
    print("  0xFC = Mode2+Temp+Stay Powered (partial)")
    print("  0xCC = Mode2+Stay Powered (partial fast, no temp)")
    print()

    epd = canvas._epd
    fb = canvas._fb

    # Prepare test data
    fb.clear()
    fb.fill_rect(50, 50, 100, 50, BLACK)
    test_data = bytes(fb.buffer)

    results = {}

    # --- Full Refresh Sequences ---
    print_subheader("Full Refresh Sequences")

    # 0xF7 - Standard full (both libraries use this)
    epd._init_full()
    epd._write(0x24, test_data)  # BW RAM
    epd._write(0x26, test_data)  # RED RAM
    epd._write(0x22, 0xF7)       # Standard sequence
    gc.collect()
    start = time.monotonic()
    epd._write(0x20)             # Activate
    epd._wait(timeout=5.0, operation="0xF7")
    elapsed_f7 = (time.monotonic() - start) * 1000
    results['0xF7'] = elapsed_f7
    print_metric("0xF7 (standard full)", elapsed_f7)

    epd.sleep()
    time.sleep(0.1)

    # 0xD7 - GxEPD2 fast mode (with temp write)
    epd._reset()
    epd._wait()
    epd._write(0x12)  # SW Reset
    epd._wait()
    # GxEPD2's temp trick: write fake temp then use 0xD7
    epd._write(0x1A, (0x64, 0x00))  # 100°C temp write
    epd._write(0x01, (0x27, 0x01, 0x00))  # Driver output
    epd._write(0x21, (0x00, 0x80))  # Update ctrl 1
    epd._write(0x3C, 0x05)  # Border
    epd._write(0x11, 0x03)  # Data entry mode
    epd._write(0x44, (0x00, 0x0F))  # RAM X
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))  # RAM Y
    epd._write(0x4E, 0x00)  # X counter
    epd._write(0x4F, (0x00, 0x00))  # Y counter
    epd._write(0x24, test_data)
    epd._write(0x26, test_data)
    epd._write(0x22, 0xD7)       # GxEPD2 fast sequence
    gc.collect()
    start = time.monotonic()
    epd._write(0x20)
    epd._wait(timeout=5.0, operation="0xD7")
    elapsed_d7 = (time.monotonic() - start) * 1000
    results['0xD7'] = elapsed_d7
    print_metric("0xD7 (GxEPD2 fast + temp)", elapsed_d7)

    epd.sleep()
    time.sleep(0.1)

    # 0xC7 - Custom v2 fast mode (no temp read in sequence)
    epd._init_full()
    epd._write(0x24, test_data)
    epd._write(0x26, test_data)
    epd._write(0x22, 0xC7)       # Custom fast sequence
    gc.collect()
    start = time.monotonic()
    epd._write(0x20)
    epd._wait(timeout=5.0, operation="0xC7")
    elapsed_c7 = (time.monotonic() - start) * 1000
    results['0xC7'] = elapsed_c7
    print_metric("0xC7 (custom fast, no temp)", elapsed_c7)

    epd.sleep()
    time.sleep(0.1)

    # --- Partial Refresh Sequences ---
    print_separator()
    print_subheader("Partial Refresh Sequences")

    # Establish basemap first
    ensure_basemap(canvas)

    # 0xFC - Standard partial (both libraries)
    fb.fill_rect(10, 10, 50, 30, BLACK)
    test_data_2 = bytes(fb.buffer)

    epd._init_partial()
    if epd._prev_buffer:
        epd._write(0x26, epd._prev_buffer)  # OLD to RED
    epd._write(0x24, test_data_2)           # NEW to BW
    epd._write(0x22, 0xFC)                  # Partial + temp + stay powered
    gc.collect()
    start = time.monotonic()
    epd._write(0x20)
    epd._wait(timeout=2.0, operation="0xFC")
    elapsed_fc = (time.monotonic() - start) * 1000
    results['0xFC'] = elapsed_fc
    print_metric("0xFC (partial + temp)", elapsed_fc)

    # 0xCC - Custom partial fast (no temp)
    fb.fill_rect(70, 10, 50, 30, BLACK)
    test_data_3 = bytes(fb.buffer)

    if epd._prev_buffer:
        epd._prev_buffer[:] = test_data_2
        epd._write(0x26, epd._prev_buffer)
    epd._write(0x24, test_data_3)
    epd._write(0x22, 0xCC)                  # Partial fast (no temp)
    gc.collect()
    start = time.monotonic()
    epd._write(0x20)
    epd._wait(timeout=2.0, operation="0xCC")
    elapsed_cc = (time.monotonic() - start) * 1000
    results['0xCC'] = elapsed_cc
    print_metric("0xCC (partial fast, no temp)", elapsed_cc)

    # Summary
    print_separator()
    print_subheader("Summary")
    if results.get('0xF7') and results.get('0xD7'):
        diff = results['0xF7'] - results['0xD7']
        print_metric("0xF7 vs 0xD7 difference", diff)
    if results.get('0xF7') and results.get('0xC7'):
        diff = results['0xF7'] - results['0xC7']
        print_metric("0xF7 vs 0xC7 difference", diff)
    if results.get('0xFC') and results.get('0xCC'):
        diff = results['0xFC'] - results['0xCC']
        print_metric("0xFC vs 0xCC difference", diff)

    epd.sleep()
    print_separator()


def bench_gxepd2_temp_trick(canvas) -> None:
    """
    Benchmark temperature trick implementations.

    Compares:
      - GxEPD2: Simple temp write (0x1A=0x64) then 0xD7
      - Custom v2: Full sequence (0xB1 read → 0x1A write → 0x91 apply)
    """
    print_header("GxEPD2 COMPARISON: TEMPERATURE TRICK")

    from framebuffer import BLACK

    print("Temperature trick forces faster waveform by faking 100°C.")
    print()
    print("GxEPD2 approach:")
    print("  1. Write 0x64 to temp register (0x1A)")
    print("  2. Use 0xD7 sequence")
    print()
    print("Custom v2 approach:")
    print("  1. Read actual temp with 0xB1 sequence")
    print("  2. Override with 0x64 via 0x1A")
    print("  3. Apply with 0x91 sequence")
    print("  4. Use 0xC7 or 0xF7 sequence")
    print()

    epd = canvas._epd
    fb = canvas._fb

    fb.clear()
    fb.fill_rect(30, 30, 80, 60, BLACK)
    test_data = bytes(fb.buffer)

    # --- GxEPD2 Simple Temp Trick ---
    print_subheader("GxEPD2 Simple Temp Trick")

    gc.collect()
    start = time.monotonic()

    # GxEPD2's approach - just write temp and go
    epd._reset()
    epd._wait()
    epd._write(0x12)  # SW Reset
    epd._wait()
    epd._write(0x1A, (0x64, 0x00))  # Direct temp write (100°C)
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x3C, 0x05)
    epd._write(0x11, 0x03)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))

    init_time_simple = (time.monotonic() - start) * 1000

    epd._write(0x24, test_data)
    epd._write(0x26, test_data)
    epd._write(0x22, 0xD7)
    epd._write(0x20)
    epd._wait(timeout=5.0)
    total_simple = (time.monotonic() - start) * 1000

    print_metric("Init time (simple)", init_time_simple)
    print_metric("Total time (simple)", total_simple)

    epd.sleep()
    time.sleep(0.1)

    # --- Custom v2 Full Temp Trick ---
    print_separator()
    print_subheader("Custom v2 Full Temp Trick")

    gc.collect()
    start = time.monotonic()

    # Custom v2's approach - read actual temp first
    epd._reset()
    epd._wait()
    epd._write(0x12)  # SW Reset
    epd._wait()

    # Standard init
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x11, 0x03)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x3C, 0x05)
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x0C, (0x8B, 0x9C, 0x96, 0x0F))  # Soft start

    # Read actual temp first
    epd._write(0x18, 0x80)  # Internal temp sensor
    epd._write(0x22, 0xB1)  # Load temp sequence
    epd._write(0x20)
    epd._wait()

    # Override with fake temp
    epd._write(0x1A, (0x64, 0x00))  # 100°C
    epd._write(0x22, 0x91)  # Apply temp sequence
    epd._write(0x20)
    epd._wait()

    init_time_full = (time.monotonic() - start) * 1000

    epd._write(0x24, test_data)
    epd._write(0x26, test_data)
    epd._write(0x22, 0xC7)  # Or 0xF7
    epd._write(0x20)
    epd._wait(timeout=5.0)
    total_full = (time.monotonic() - start) * 1000

    print_metric("Init time (full sequence)", init_time_full)
    print_metric("Total time (full sequence)", total_full)

    # Summary
    print_separator()
    print_subheader("Summary")
    init_diff = init_time_full - init_time_simple
    total_diff = total_full - total_simple
    print_metric("Init overhead (full vs simple)", init_diff)
    print_metric("Total overhead", total_diff)
    print()
    print("Note: GxEPD2's simple approach is faster but may be less")
    print("reliable across temperature variations.")

    epd.sleep()
    print_separator()


def bench_gxepd2_soft_start(canvas) -> None:
    """
    Benchmark effect of Soft Start register (0x0C).

    Custom v2 sets: (0x8B, 0x9C, 0x96, 0x0F)
    GxEPD2 doesn't set this register (uses default/OTP values)
    """
    print_header("GxEPD2 COMPARISON: SOFT START (0x0C)")

    from framebuffer import BLACK

    print("Soft Start (0x0C) controls charge pump timing for booster.")
    print()
    print("Custom v2 always sets: 0x8B, 0x9C, 0x96, 0x0F")
    print("GxEPD2 doesn't set - relies on default/OTP values")
    print()

    epd = canvas._epd
    fb = canvas._fb

    fb.clear()
    fb.fill_rect(40, 40, 70, 50, BLACK)
    test_data = bytes(fb.buffer)

    # --- Without Soft Start (GxEPD2 style) ---
    print_subheader("WITHOUT Soft Start (GxEPD2 style)")

    gc.collect()
    start = time.monotonic()

    epd._reset()
    epd._wait()
    epd._write(0x12)
    epd._wait()
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x11, 0x03)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x3C, 0x05)
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x18, 0x80)
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    # NO 0x0C command

    init_no_ss = (time.monotonic() - start) * 1000

    epd._write(0x24, test_data)
    epd._write(0x26, test_data)
    epd._write(0x22, 0xF7)
    epd._write(0x20)
    epd._wait(timeout=5.0)
    total_no_ss = (time.monotonic() - start) * 1000

    print_metric("Init time", init_no_ss)
    print_metric("Total refresh time", total_no_ss)

    epd.sleep()
    time.sleep(0.1)

    # --- With Soft Start (Custom v2 style) ---
    print_separator()
    print_subheader("WITH Soft Start (Custom v2 style)")

    gc.collect()
    start = time.monotonic()

    epd._reset()
    epd._wait()
    epd._write(0x12)
    epd._wait()
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x11, 0x03)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x3C, 0x05)
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x18, 0x80)
    epd._write(0x0C, (0x8B, 0x9C, 0x96, 0x0F))  # Soft Start
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))

    init_with_ss = (time.monotonic() - start) * 1000

    epd._write(0x24, test_data)
    epd._write(0x26, test_data)
    epd._write(0x22, 0xF7)
    epd._write(0x20)
    epd._wait(timeout=5.0)
    total_with_ss = (time.monotonic() - start) * 1000

    print_metric("Init time", init_with_ss)
    print_metric("Total refresh time", total_with_ss)

    # Summary
    print_separator()
    print_subheader("Summary")
    init_diff = init_with_ss - init_no_ss
    total_diff = total_with_ss - total_no_ss
    print_metric("Init overhead", init_diff)
    print_metric("Refresh difference", total_diff)
    print()
    print("Note: Soft Start primarily affects power-up stability,")
    print("not refresh time. May improve reliability in edge cases.")

    epd.sleep()
    print_separator()


def bench_gxepd2_border_waveform(canvas) -> None:
    """
    Benchmark border waveform settings (0x3C).

    Custom v2: Full=0x05, Partial=0x80
    GxEPD2: Always 0x05
    """
    print_header("GxEPD2 COMPARISON: BORDER WAVEFORM (0x3C)")

    from framebuffer import BLACK

    print("Border Waveform Control (0x3C) settings:")
    print()
    print("  0x05 = GS Transition (border follows LUT)")
    print("  0x80 = VCOM level (stable border, no artifacts)")
    print("  0xC0 = HiZ (floating, may cause drift)")
    print()
    print("GxEPD2: Always uses 0x05")
    print("Custom v2: 0x05 for full, 0x80 for partial")
    print()

    epd = canvas._epd
    fb = canvas._fb

    # Draw edge pattern to observe border behavior
    fb.clear()
    fb.fill_rect(5, 5, 118, 40, BLACK)

    ensure_basemap(canvas)

    # --- Partial with 0x05 (GxEPD2 style) ---
    print_subheader("Partial with Border=0x05 (GxEPD2)")

    fb.fill_rect(20, 50, 80, 30, BLACK)
    test_data_2 = bytes(fb.buffer)

    epd._reset()
    epd._wait()
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x11, 0x03)
    epd._write(0x3C, 0x05)  # GxEPD2 style
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x18, 0x80)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))

    if epd._prev_buffer:
        epd._write(0x26, epd._prev_buffer)
    epd._write(0x24, test_data_2)
    epd._write(0x22, 0xFC)

    gc.collect()
    start = time.monotonic()
    epd._write(0x20)
    epd._wait(timeout=2.0)
    elapsed_05 = (time.monotonic() - start) * 1000

    print_metric("Partial refresh time", elapsed_05)
    print("  (Observe: border may flash with display)")

    time.sleep(0.5)

    # --- Partial with 0x80 (Custom v2 style) ---
    print_separator()
    print_subheader("Partial with Border=0x80 (Custom v2)")

    fb.fill_rect(60, 50, 80, 30, BLACK)
    test_data_3 = bytes(fb.buffer)

    epd._write(0x3C, 0x80)  # Custom v2 style - VCOM level

    if epd._prev_buffer:
        epd._prev_buffer[:] = test_data_2
        epd._write(0x26, epd._prev_buffer)
    epd._write(0x24, test_data_3)
    epd._write(0x22, 0xFC)

    gc.collect()
    start = time.monotonic()
    epd._write(0x20)
    epd._wait(timeout=2.0)
    elapsed_80 = (time.monotonic() - start) * 1000

    print_metric("Partial refresh time", elapsed_80)
    print("  (Observe: border should remain stable)")

    # Summary
    print_separator()
    print_subheader("Summary")
    diff = elapsed_80 - elapsed_05
    print_metric("Time difference", diff)
    print()
    print("Border=0x80 provides stable edges during partial refresh.")
    print("No timing impact, but cleaner visual result on edges.")

    epd.sleep()
    print_separator()


def bench_gxepd2_ram_patterns(canvas) -> None:
    """
    Benchmark RAM write patterns for differential updates.

    GxEPD2 pattern:
      1. writeImage() → writes to 0x24 (BW RAM)
      2. refresh()
      3. writeImageAgain() → writes to BOTH 0x24 and 0x26

    Custom v2 pattern:
      1. Automatic: writes OLD to 0x26, NEW to 0x24
      2. Maintains prev_buffer internally
    """
    print_header("GxEPD2 COMPARISON: RAM WRITE PATTERNS")

    from framebuffer import BLACK

    print("Differential updates require OLD and NEW images in RAMs:")
    print("  - RED RAM (0x26): OLD image for comparison")
    print("  - BW RAM (0x24): NEW image to display")
    print()
    print("GxEPD2: User manually syncs with writeImageAgain()")
    print("Custom v2: Automatic via internal prev_buffer")
    print()

    epd = canvas._epd
    fb = canvas._fb

    ensure_basemap(canvas)

    # --- GxEPD2 Pattern (manual sync) ---
    print_subheader("GxEPD2 Pattern (manual RAM sync)")

    # Frame 1: Initial image
    fb.clear()
    fb.fill_rect(30, 30, 50, 50, BLACK)
    frame1 = bytes(fb.buffer)

    gc.collect()
    start = time.monotonic()

    # Write to BW RAM only (like GxEPD2 writeImage)
    epd._init_partial()
    epd._write(0x24, frame1)
    epd._write(0x22, 0xFC)
    epd._write(0x20)
    epd._wait(timeout=2.0)

    # Sync to RED RAM (like GxEPD2 writeImageAgain)
    epd._write(0x4E, 0x00)  # Reset X counter
    epd._write(0x4F, (0x00, 0x00))  # Reset Y counter
    epd._write(0x24, frame1)  # Write to BW again
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x26, frame1)  # Write to RED

    sync_time_gxepd2 = (time.monotonic() - start) * 1000

    # Frame 2: Updated image
    fb.fill_rect(60, 30, 50, 50, BLACK)
    frame2 = bytes(fb.buffer)

    gc.collect()
    start = time.monotonic()

    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x24, frame2)  # New to BW
    epd._write(0x22, 0xFC)
    epd._write(0x20)
    epd._wait(timeout=2.0)

    # Sync again
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x24, frame2)
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x26, frame2)

    total_gxepd2 = (time.monotonic() - start) * 1000 + sync_time_gxepd2

    print_metric("Frame 1 + sync time", sync_time_gxepd2)
    print_metric("Frame 2 + sync time", total_gxepd2)

    epd.sleep()
    time.sleep(0.1)

    # --- Custom v2 Pattern (automatic sync) ---
    print_separator()
    print_subheader("Custom v2 Pattern (automatic prev_buffer)")

    ensure_basemap(canvas)

    # Frame 1
    fb.clear()
    fb.fill_rect(30, 30, 50, 50, BLACK)
    frame1 = bytes(fb.buffer)

    gc.collect()
    start = time.monotonic()

    epd._init_partial()
    if epd._prev_buffer:
        epd._write(0x26, epd._prev_buffer)  # OLD from buffer
    epd._write(0x24, frame1)  # NEW
    epd._write(0x22, 0xFC)
    epd._write(0x20)
    epd._wait(timeout=2.0)

    if epd._prev_buffer:
        epd._prev_buffer[:] = frame1  # Internal sync (just memcpy)

    frame1_time_v2 = (time.monotonic() - start) * 1000

    # Frame 2
    fb.fill_rect(60, 30, 50, 50, BLACK)
    frame2 = bytes(fb.buffer)

    gc.collect()
    start = time.monotonic()

    if epd._prev_buffer:
        epd._write(0x26, epd._prev_buffer)  # OLD (which is frame1)
    epd._write(0x24, frame2)  # NEW
    epd._write(0x22, 0xFC)
    epd._write(0x20)
    epd._wait(timeout=2.0)

    if epd._prev_buffer:
        epd._prev_buffer[:] = frame2

    frame2_time_v2 = (time.monotonic() - start) * 1000

    print_metric("Frame 1 time", frame1_time_v2)
    print_metric("Frame 2 time", frame2_time_v2)
    total_v2 = frame1_time_v2 + frame2_time_v2

    # Summary
    print_separator()
    print_subheader("Summary (2 frame sequence)")
    print_metric("GxEPD2 total", total_gxepd2)
    print_metric("Custom v2 total", total_v2)
    diff = total_gxepd2 - total_v2
    print_metric("Difference", diff)
    print()
    print("Custom v2 saves time by:")
    print("  - Writing OLD buffer first (already in memory)")
    print("  - Only one SPI write to 0x24 per frame")
    print("  - No post-refresh sync writes")

    epd.sleep()
    print_separator()


def bench_gxepd2_full_comparison(canvas) -> None:
    """
    Full end-to-end comparison: GxEPD2 style vs Custom v2 style.

    Simulates a typical usage pattern: initial clear, full refresh,
    then several partial updates.
    """
    print_header("GxEPD2 COMPARISON: FULL WORKFLOW")

    from framebuffer import BLACK

    print("Complete workflow comparison:")
    print("  1. Clear screen")
    print("  2. Initial full refresh")
    print("  3. Three partial updates")
    print()

    epd = canvas._epd
    fb = canvas._fb

    # --- GxEPD2 Style Workflow ---
    print_subheader("GxEPD2 Style Workflow")

    gc.collect()
    workflow_start = time.monotonic()

    # Step 1: Clear (GxEPD2's clearScreen writes to both RAMs)
    clear_data = bytes([0xFF]) * epd.BUFFER_SIZE

    epd._reset()
    epd._wait()
    epd._write(0x12)
    time.sleep(0.01)
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x3C, 0x05)
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x18, 0x80)
    epd._write(0x11, 0x03)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))

    epd._write(0x26, clear_data)  # Previous
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x24, clear_data)  # Current

    # Full refresh (with temp trick like useFastFullUpdate)
    epd._write(0x1A, (0x64, 0x00))
    epd._write(0x22, 0xD7)
    epd._write(0x20)
    epd._wait(timeout=5.0)

    full_time_gxepd2 = (time.monotonic() - workflow_start) * 1000
    print_metric("Clear + Full refresh", full_time_gxepd2)

    # Partials
    partial_times_gxepd2 = []
    prev_frame = clear_data

    for i in range(3):
        fb.clear()
        fb.fill_rect(20 + i * 40, 30, 30, 40, BLACK)
        new_frame = bytes(fb.buffer)

        gc.collect()
        start = time.monotonic()

        epd._write(0x11, 0x03)
        epd._write(0x44, (0x00, 0x0F))
        epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
        epd._write(0x4E, 0x00)
        epd._write(0x4F, (0x00, 0x00))
        epd._write(0x24, new_frame)
        epd._write(0x22, 0xFC)
        epd._write(0x20)
        epd._wait(timeout=2.0)

        # GxEPD2 writeImageAgain style sync
        epd._write(0x4E, 0x00)
        epd._write(0x4F, (0x00, 0x00))
        epd._write(0x24, new_frame)
        epd._write(0x4E, 0x00)
        epd._write(0x4F, (0x00, 0x00))
        epd._write(0x26, new_frame)

        elapsed = (time.monotonic() - start) * 1000
        partial_times_gxepd2.append(elapsed)
        print_metric(f"  Partial {i+1}", elapsed)

    total_gxepd2 = (time.monotonic() - workflow_start) * 1000
    print_metric("Total workflow time", total_gxepd2)

    epd.sleep()
    time.sleep(0.1)

    # --- Custom v2 Style Workflow ---
    print_separator()
    print_subheader("Custom v2 Style Workflow")

    gc.collect()
    workflow_start = time.monotonic()

    # Full init with temp trick
    epd._reset()
    epd._wait()
    epd._write(0x12)
    epd._wait()
    epd._write(0x01, (0x27, 0x01, 0x00))
    epd._write(0x11, 0x03)
    epd._write(0x44, (0x00, 0x0F))
    epd._write(0x45, (0x00, 0x00, 0x27, 0x01))
    epd._write(0x3C, 0x05)
    epd._write(0x21, (0x00, 0x80))
    epd._write(0x4E, 0x00)
    epd._write(0x4F, (0x00, 0x00))
    epd._write(0x0C, (0x8B, 0x9C, 0x96, 0x0F))  # Soft start

    # Temperature trick (full sequence)
    epd._write(0x18, 0x80)
    epd._write(0x22, 0xB1)
    epd._write(0x20)
    epd._wait()
    epd._write(0x1A, (0x64, 0x00))
    epd._write(0x22, 0x91)
    epd._write(0x20)
    epd._wait()

    epd._write(0x24, clear_data)
    epd._write(0x26, clear_data)
    epd._write(0x22, 0xC7)
    epd._write(0x20)
    epd._wait(timeout=5.0)

    # Update internal buffer
    if epd._prev_buffer:
        epd._prev_buffer[:] = clear_data

    full_time_v2 = (time.monotonic() - workflow_start) * 1000
    print_metric("Clear + Full refresh", full_time_v2)

    # Partials
    partial_times_v2 = []

    # Minimal partial init (just change border)
    epd._write(0x3C, 0x80)  # Border for partial

    for i in range(3):
        fb.clear()
        fb.fill_rect(20 + i * 40, 30, 30, 40, BLACK)
        new_frame = bytes(fb.buffer)

        gc.collect()
        start = time.monotonic()

        epd._write(0x4E, 0x00)
        epd._write(0x4F, (0x00, 0x00))
        if epd._prev_buffer:
            epd._write(0x26, epd._prev_buffer)  # OLD
        epd._write(0x4E, 0x00)
        epd._write(0x4F, (0x00, 0x00))
        epd._write(0x24, new_frame)  # NEW
        epd._write(0x22, 0xFC)
        epd._write(0x20)
        epd._wait(timeout=2.0)

        # Internal buffer sync (no SPI, just memory copy)
        if epd._prev_buffer:
            epd._prev_buffer[:] = new_frame

        elapsed = (time.monotonic() - start) * 1000
        partial_times_v2.append(elapsed)
        print_metric(f"  Partial {i+1}", elapsed)

    total_v2 = (time.monotonic() - workflow_start) * 1000
    print_metric("Total workflow time", total_v2)

    # Summary
    print_separator()
    print_subheader("SUMMARY")
    print_metric("GxEPD2 style total", total_gxepd2)
    print_metric("Custom v2 style total", total_v2)
    diff = total_gxepd2 - total_v2
    pct = (diff / total_gxepd2) * 100 if total_gxepd2 > 0 else 0
    print_metric("Time saved", diff)
    print_metric("Improvement", f"{pct:.1f}", "%")
    print()
    print("Full refresh difference:", f"{full_time_gxepd2 - full_time_v2:.1f}ms")
    avg_partial_gxepd2 = sum(partial_times_gxepd2) / len(partial_times_gxepd2)
    avg_partial_v2 = sum(partial_times_v2) / len(partial_times_v2)
    print(f"Avg partial (GxEPD2): {avg_partial_gxepd2:.1f}ms")
    print(f"Avg partial (v2):     {avg_partial_v2:.1f}ms")

    epd.sleep()
    print_separator()
