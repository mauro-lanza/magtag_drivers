"""
GxEPD2 vs Custom Driver Comparison Benchmarks
==============================================
Comprehensive comparison of driver approaches, covering areas where
GxEPD2 and the custom v2 driver differ in implementation.

Comparison Areas:
  1. Power Management - sleep/wake timing, hibernate vs powerOff
  2. Window Clipping - partial RAM writes vs full buffer transfer
  3. Voltage Settings - register value comparison
  4. Partial Refresh Quality - ghosting over multiple updates
  5. Basemap Requirements - partial without prior full refresh
  6. OTP Version Handling - panel detection differences

Reference:
  GxEPD2_290_GDEY029T94.cpp - Jean-Marc Zingg's implementation
  https://github.com/ZinggJM/GxEPD2
"""

import gc
import time
from utils import (
    print_header, print_metric, print_separator, print_subheader,
    timed, ensure_basemap
)


def run(canvas, buttons=None) -> None:
    """Run all GxEPD2 comparison benchmarks.

    Args:
        canvas: Canvas instance
        buttons: Optional Buttons instance for interactive mode
    """
    bench_power_management(canvas)
    bench_window_clipping(canvas)
    bench_voltage_settings(canvas)
    bench_partial_quality(canvas)
    bench_basemap_requirement(canvas)
    bench_otp_reading(canvas)


# =============================================================================
# 1. Power Management Comparison
# =============================================================================

def bench_power_management(canvas) -> None:
    """Compare power management approaches between drivers.

    GxEPD2 has two separate methods:
      - powerOff(): Powers off analog circuits (0x83 sequence)
      - hibernate(): powerOff + deep sleep command (0x10, 0x01)

    Custom v2 has:
      - sleep(retain_ram=True): Deep sleep mode 1 (RAM retained)
      - sleep(retain_ram=False): Deep sleep mode 2 (RAM lost)
      - power_off(): Same as GxEPD2 powerOff (0x83)
      - power_on(): Explicit power-on (0xE0)

    Key Difference:
      GxEPD2 hibernate() = power_off + sleep mode 1
      Custom sleep() = enters sleep directly (power turns off automatically)
    """
    print_header("POWER MANAGEMENT COMPARISON")

    epd = canvas._epd

    print("GxEPD2 approach:")
    print("  powerOff()  = 0x22, 0x83, 0x20 (analog off, booster off)")
    print("  hibernate() = powerOff() + 0x10, 0x01 (deep sleep mode 1)")
    print()
    print("Custom v2 approach:")
    print("  power_off() = 0x22, 0x83, 0x20 (same as GxEPD2)")
    print("  power_on()  = 0x22, 0xE0, 0x20 (explicit power on)")
    print("  sleep()     = 0x10, 0x01 or 0x03 (direct to deep sleep)")
    print()

    # Ensure display is awake and initialized (not hibernating)
    epd._reset()
    epd._init_full()
    epd._state |= 0x04  # _STATE_POWER_ON - mark as powered

    # Test 1: Power off and on cycle (GxEPD2 style)
    print_subheader("Power Off/On Cycle (GxEPD2 style)")

    _, elapsed_off = timed(epd.power_off)
    print_metric("power_off()", elapsed_off)

    _, elapsed_on = timed(epd.power_on)
    print_metric("power_on()", elapsed_on)

    print_metric("Total cycle", elapsed_off + elapsed_on)

    # Test 2: Sleep and wake cycle (custom style)
    print_subheader("Sleep/Wake Cycle (custom style)")

    # Sleep mode 1 (RAM retained)
    _, elapsed_sleep1 = timed(epd.sleep, True)
    print_metric("sleep(retain_ram=True)", elapsed_sleep1)

    # Wake from sleep requires hardware reset
    _, elapsed_wake = timed(epd._reset)
    # Then re-init
    _, elapsed_init = timed(epd._init_full)
    print_metric("wake (reset + init)", elapsed_wake + elapsed_init)

    # Test 3: Sleep mode 2 (RAM lost - lowest power)
    print_subheader("Sleep Mode 2 (lowest power)")

    # Display is now awake from previous test, just sleep it
    _, elapsed_sleep2 = timed(epd.sleep, False)
    print_metric("sleep(retain_ram=False)", elapsed_sleep2)

    # Wake from mode 2
    _, elapsed_wake2 = timed(epd._reset)
    _, elapsed_init2 = timed(epd._init_full)
    print_metric("wake (reset + init)", elapsed_wake2 + elapsed_init2)

    # Test 4: Compare partial refresh after different wake methods
    print_subheader("First Partial After Wake")

    # After power_on only (no sleep) - wake first then test
    epd._reset()
    epd._init_full()
    canvas.clear()
    canvas.full_refresh()  # Establish basemap
    # Now display is sleeping, wake it for the power test
    epd._reset()
    epd._init_full()
    epd.power_off()
    epd.power_on()
    canvas.fill_rect(10, 10, 50, 30, 0)  # BLACK = 0
    _, elapsed_partial_after_power = timed(canvas.partial_refresh)
    print_metric("partial after power_on()", elapsed_partial_after_power)

    # After sleep + wake (hardware reset)
    epd.sleep(True)
    epd._reset()
    epd._init_full()
    canvas.fill_rect(10, 10, 50, 30, 0)
    _, elapsed_partial_after_sleep = timed(canvas.partial_refresh)
    print_metric("partial after sleep + wake", elapsed_partial_after_sleep)

    # Cleanup
    epd.sleep()

    print()
    print("Analysis:")
    print("  - power_off/on is faster but uses more standby power (~µA vs ~nA)")
    print("  - sleep() is slower to wake but uses least power")
    print("  - For battery devices: use sleep() between infrequent updates")
    print("  - For rapid updates: stay powered or use power_off/on")

    print_separator()


# =============================================================================
# 2. Window Clipping Comparison
# =============================================================================

def bench_window_clipping(canvas) -> None:
    """Compare partial window RAM writes vs full buffer transfers.

    GxEPD2 can write only changed region to RAM:
      _setPartialRamArea(x, y, w, h)
      writeImage(bitmap, x, y, w, h)  <- clips to region

    Custom v2 sends full buffer even for region updates:
      display_region() still writes full buffer to RAM
      (optimization potential here)

    This benchmark measures the data transfer overhead.
    """
    print_header("WINDOW CLIPPING COMPARISON")

    epd = canvas._epd
    ensure_basemap(canvas)

    print("Testing RAM write efficiency for partial updates...")
    print()

    # Small region update (typical UI element)
    small_x, small_y = 50, 30
    small_w, small_h = 40, 20
    small_bytes = (small_w * small_h) // 8

    # Medium region (clock/counter display)
    med_x, med_y = 20, 20
    med_w, med_h = 100, 50
    med_bytes = (med_w * med_h) // 8

    # Large region (half screen)
    large_x, large_y = 0, 0
    large_w, large_h = canvas.width // 2, canvas.height
    large_bytes = (large_w * large_h) // 8

    # Full buffer size
    full_bytes = (canvas.width * canvas.height) // 8

    print("Region sizes (bytes to transfer):")
    print(f"  Small ({small_w}x{small_h}):  {small_bytes:>5} bytes (GxEPD2 clipped)")
    print(f"  Medium ({med_w}x{med_h}): {med_bytes:>5} bytes (GxEPD2 clipped)")
    print(f"  Large ({large_w}x{large_h}): {large_bytes:>5} bytes (GxEPD2 clipped)")
    print(f"  Full buffer:         {full_bytes:>5} bytes (custom v2 always)")
    print()

    # Benchmark: Custom v2 region update (sends full buffer)
    print_subheader("Custom v2 - Full Buffer Transfer")

    canvas.clear()
    canvas.fill_rect(small_x, small_y, small_w, small_h, 0)
    _, elapsed_small = timed(canvas.partial_refresh)
    print_metric(f"Small region update ({small_w}x{small_h})", elapsed_small)

    canvas.fill_rect(med_x, med_y, med_w, med_h, 0)
    _, elapsed_med = timed(canvas.partial_refresh)
    print_metric(f"Medium region update ({med_w}x{med_h})", elapsed_med)

    canvas.fill_rect(large_x, large_y, large_w, large_h, 0)
    _, elapsed_large = timed(canvas.partial_refresh)
    print_metric(f"Large region update ({large_w}x{large_h})", elapsed_large)

    # Benchmark: Direct SPI transfer timing
    print_subheader("SPI Transfer Overhead Analysis")

    # Time just the SPI write for different sizes
    test_data_small = bytes(small_bytes)
    test_data_full = bytes(full_bytes)

    # Measure SPI transfer time for different sizes
    epd._init_partial() if hasattr(epd, '_init_partial') else epd._init_full()

    # Small data transfer
    gc.collect()
    start = time.monotonic_ns()
    epd._write(0x24, test_data_small)
    elapsed_spi_small = (time.monotonic_ns() - start) / 1_000_000
    print_metric(f"SPI write {small_bytes} bytes", elapsed_spi_small)

    # Full data transfer
    gc.collect()
    start = time.monotonic_ns()
    epd._write(0x24, test_data_full)
    elapsed_spi_full = (time.monotonic_ns() - start) / 1_000_000
    print_metric(f"SPI write {full_bytes} bytes", elapsed_spi_full)

    # Calculate potential savings
    spi_overhead = elapsed_spi_full - elapsed_spi_small
    print()
    print("Analysis:")
    print(f"  SPI overhead for full vs small: {spi_overhead:.1f}ms")
    print(f"  Potential savings with windowed write: ~{spi_overhead:.0f}ms per update")
    print("  Note: Actual refresh time dominates (~300ms partial)")

    # Cleanup
    epd.sleep()

    print_separator()


# =============================================================================
# 3. Voltage Settings Comparison
# =============================================================================

def bench_voltage_settings(canvas) -> None:
    """Compare voltage register settings between implementations.

    GxEPD2 GDEY029T94 uses:
      - No explicit voltage settings (relies on OTP)
      - Border waveform: 0x05

    Custom v2 uses (for custom LUT):
      - VGH (0x03): 0x17 = 20V
      - VSH1/VSH2/VSL (0x04): 0x41, 0xA8, 0x32
      - VCOM (0x2C): 0x50 = -2.0V

    This benchmark reads current values and tests different settings.
    """
    print_header("VOLTAGE SETTINGS COMPARISON")

    epd = canvas._epd
    ensure_basemap(canvas)

    print("GxEPD2 approach: Relies on OTP waveform voltage settings")
    print("Custom v2 approach: Explicit voltages for custom LUT only")
    print()

    # Define voltage constants
    CUSTOM_VGH = 0x17   # 20V
    CUSTOM_VSH1 = 0x41  # +15V
    CUSTOM_VSH2 = 0xA8  # +5V
    CUSTOM_VSL = 0x32   # -15V
    CUSTOM_VCOM = 0x50  # -2.0V

    print("Custom v2 voltage defaults:")
    print(f"  VGH  (0x03): 0x{CUSTOM_VGH:02X} → ~20V (gate high)")
    print(f"  VSH1 (0x04): 0x{CUSTOM_VSH1:02X} → ~+15V (source high 1)")
    print(f"  VSH2 (0x04): 0x{CUSTOM_VSH2:02X} → ~+5V (source high 2)")
    print(f"  VSL  (0x04): 0x{CUSTOM_VSL:02X} → ~-15V (source low)")
    print(f"  VCOM (0x2C): 0x{CUSTOM_VCOM:02X} → ~-2.0V (common)")
    print()

    # Test: Display with different VCOM levels
    print_subheader("VCOM Level Impact on Contrast")

    from framebuffer import BLACK, WHITE

    vcom_values = [
        (0x28, "-1.0V (weak)"),
        (0x50, "-2.0V (default)"),
        (0x78, "-3.0V (strong)"),
    ]

    for vcom, desc in vcom_values:
        # Ensure display is awake before writing register
        if epd._state & 0x08:  # _STATE_HIBERNATING
            epd._reset()
            epd._init_full()

        # Write VCOM value
        epd._write(0x2C, bytes([vcom]))

        # Draw test pattern
        canvas.clear()
        canvas.fill_rect(10, 10, 108, 60, BLACK)
        canvas.fill_rect(15, 15, 98, 50, WHITE)
        canvas.fill_rect(20, 20, 88, 40, BLACK)
        canvas.text(f"VCOM={desc}", canvas.width // 2, 90, BLACK, align="center")

        _, elapsed = timed(canvas.full_refresh)
        print_metric(f"VCOM 0x{vcom:02X} ({desc})", elapsed)

    # Note: VCOM will reset to default on next _init_full() - no need to restore
    # Display is now sleeping after the last full_refresh()

    print()
    print("Note: Visual difference is subtle. Higher VCOM (more negative)")
    print("      typically improves contrast but may reduce panel life.")

    print_separator()


# =============================================================================
# 4. Partial Refresh Quality (Ghosting Analysis)
# =============================================================================

def bench_partial_quality(canvas) -> None:
    """Measure ghosting accumulation over multiple partial refreshes.

    GxEPD2 enforces periodic full refresh via _initial_refresh flag.
    Custom v2 has partial_threshold setting.

    This test performs many partials and observes ghosting buildup.
    """
    print_header("PARTIAL REFRESH QUALITY (GHOSTING)")

    epd = canvas._epd
    ensure_basemap(canvas)

    from framebuffer import BLACK

    print("Testing ghosting accumulation over consecutive partial updates...")
    print("Watch the display for increasing ghosting artifacts.")
    print()

    # Save original threshold
    original_threshold = epd._partial_threshold
    epd._partial_threshold = 0  # Disable auto full refresh

    # Test: Alternating patterns to maximize ghosting
    iterations = 20
    times = []

    print_subheader(f"Alternating Pattern Test ({iterations} iterations)")

    for i in range(iterations):
        # Pattern A: checkerboard-like
        canvas.clear()
        for y in range(0, canvas.height, 20):
            for x in range(0, canvas.width, 20):
                if (x // 20 + y // 20) % 2 == 0:
                    canvas.fill_rect(x, y, 20, 20, BLACK)
        canvas.text(f"Partial #{i+1}", canvas.width // 2, 5, BLACK, align="center")

        _, elapsed = timed(canvas.partial_refresh)
        times.append(elapsed)

        if (i + 1) % 5 == 0:
            avg_last_5 = sum(times[-5:]) / 5
            print_metric(f"Partials {i-3}-{i+1} avg", avg_last_5)

    # Statistics
    print()
    print(f"  Total partials without full refresh: {iterations}")
    print(f"  Average partial time: {sum(times)/len(times):.2f} ms")
    print(f"  Variance: {max(times) - min(times):.2f} ms")
    print()

    # Now do full refresh and measure improvement
    print_subheader("Full Refresh Recovery")

    canvas.clear()
    canvas.fill_rect(50, 30, 100, 60, BLACK)
    canvas.text("After Full", canvas.width // 2, 100, BLACK, align="center")

    _, elapsed_full = timed(canvas.full_refresh)
    print_metric("Full refresh (clears ghosting)", elapsed_full)

    # Restore threshold
    epd._partial_threshold = original_threshold

    print()
    print("Analysis:")
    print("  - Ghosting becomes visible after ~10-15 partials")
    print(f"  - Custom v2 default threshold: {original_threshold} partials")
    print("  - GxEPD2 requires manual refresh management")

    # Cleanup
    epd.sleep()

    print_separator()


# =============================================================================
# 5. Basemap Requirement Comparison
# =============================================================================

def bench_basemap_requirement(canvas) -> None:
    """Test partial refresh behavior without prior full refresh.

    GxEPD2 writeImageAgain() can update without basemap:
      - Writes same data to both RAM planes
      - Allows partial update even on first run

    Custom v2 requires basemap:
      - First partial without basemap triggers automatic full refresh
      - This is a safety feature to prevent undefined behavior
    """
    print_header("BASEMAP REQUIREMENT COMPARISON")

    epd = canvas._epd

    print("GxEPD2: writeImageAgain() writes to both RAMs, enabling partial")
    print("        without prior full refresh (useful for power-on updates)")
    print()
    print("Custom v2: Requires basemap (full refresh) before partials.")
    print("           First partial auto-triggers full refresh if no basemap.")
    print()

    # Clear basemap flag
    from epd import _STATE_BASEMAP
    epd._state &= ~_STATE_BASEMAP  # Clear basemap flag

    from framebuffer import BLACK

    # Test 1: Partial without basemap (custom v2 behavior)
    print_subheader("Partial Without Basemap (Custom v2)")

    canvas.clear()
    canvas.fill_rect(50, 30, 100, 60, BLACK)
    canvas.text("No Basemap", canvas.width // 2, 100, BLACK, align="center")

    _, elapsed = timed(canvas.partial_refresh)

    has_basemap = bool(epd._state & _STATE_BASEMAP)
    print_metric("partial_refresh() called", elapsed)
    print(f"  → Basemap flag after: {has_basemap}")
    if elapsed > 1000:  # If it took > 1s, likely did full refresh
        print("  → Detected automatic full refresh trigger")
    else:
        print("  → Partial executed (basemap was present)")

    # Test 2: Simulate GxEPD2 writeImageAgain pattern
    print_subheader("Simulated writeImageAgain (GxEPD2 style)")

    # Clear basemap flag again
    epd._state &= ~_STATE_BASEMAP

    # Manually write to both RAMs (like writeImageAgain)
    canvas.clear()
    canvas.fill_rect(30, 20, 80, 50, BLACK)
    mono_data = canvas._fb.to_mono()

    epd._init_full()
    epd._set_window(0, 0, epd.WIDTH, epd.HEIGHT)

    # Write same data to both RAMs (simulating writeImageAgain)
    gc.collect()
    start = time.monotonic_ns()
    epd._write(0x26, mono_data)  # Previous (RED RAM)
    epd._write(0x24, mono_data)  # Current (BW RAM)

    # Partial update (without full refresh first)
    epd._write(0x22, bytes([0xFC]))  # Partial mode
    epd._write(0x20)  # Activate
    epd._wait(timeout=1.0, operation="partial")
    elapsed_gxepd2_style = (time.monotonic_ns() - start) / 1_000_000

    print_metric("writeImageAgain + partial", elapsed_gxepd2_style)
    print("  → This achieves partial update without prior full refresh")

    # Cleanup
    epd.sleep()

    print()
    print("Analysis:")
    print("  - GxEPD2 pattern useful for quick power-on displays")
    print("  - Custom v2's auto-full-refresh is safer but slower on first update")
    print("  - Trade-off: flexibility vs safety")

    print_separator()


# =============================================================================
# 6. OTP Version Handling
# =============================================================================

def bench_otp_reading(canvas) -> None:
    """Compare OTP (One-Time Programmable) memory handling.

    GxEPD2: Does not read OTP - assumes fixed panel type
    Custom v2: Can read OTP for display options and user ID

    OTP contains:
      - Display option (VCOM value)
      - Waveform version
      - User ID (10 bytes)
    """
    print_header("OTP VERSION HANDLING")

    epd = canvas._epd
    ensure_basemap(canvas)

    print("GxEPD2: Assumes fixed panel type from class selection")
    print("Custom v2: Can read OTP memory for panel info")
    print()

    # Read display option (0x2D)
    print_subheader("OTP Display Option (0x2D)")

    epd._init_full()

    try:
        # Enable OTP read
        epd._write(0x2D)
        display_opt = epd._read(0x2D, 2)
        print(f"  Raw bytes: 0x{display_opt[0]:02X} 0x{display_opt[1]:02X}")
        print(f"  VCOM from OTP: {display_opt[0]}")
    except Exception as e:
        print(f"  OTP read not supported or failed: {e}")

    # Read User ID (0x2E)
    print_subheader("OTP User ID (0x2E)")

    try:
        epd._write(0x2E)
        user_id = epd._read(0x2E, 10)
        print(f"  User ID: {user_id.hex()}")
    except Exception as e:
        print(f"  User ID read not supported or failed: {e}")

    # Temperature sensor test
    print_subheader("Internal Temperature Sensor")

    temp = epd.read_temperature()
    print_metric("Current panel temperature", temp, "°C")

    print()
    print("Analysis:")
    print("  - OTP reading allows runtime panel detection")
    print("  - VCOM from OTP can optimize contrast for specific panel")
    print("  - User ID can be used for device identification")
    print("  - GxEPD2 relies on compile-time panel selection")

    # Cleanup
    epd.sleep()

    print_separator()


# =============================================================================
# Summary
# =============================================================================

def print_summary() -> None:
    """Print overall comparison summary."""
    print_header("COMPARISON SUMMARY")

    print("""
    Feature                    GxEPD2          Custom v2
    ─────────────────────────────────────────────────────────────
    Power Management          powerOff +       sleep() modes
                              hibernate()      (1 = RAM, 2 = low)

    Window Clipping           Per-region       Full buffer
                              RAM write        always sent

    Voltage Control           OTP only         Explicit for
                                               custom LUT

    Partial Quality           Manual           Auto threshold
                              management       (configurable)

    Basemap Requirement       Optional         Required
                              (writeAgain)     (auto-triggers)

    OTP Reading               Not used         Available

    Conclusion:
      - GxEPD2: More flexible, requires careful management
      - Custom v2: Safer defaults, some optimization opportunities
      - Key improvement potential: window clipping for RAM writes
    """)

    print_separator()
