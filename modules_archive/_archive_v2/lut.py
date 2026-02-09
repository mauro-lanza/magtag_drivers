"""
LUT - Look-Up Tables for EPD Waveforms
======================================
Custom waveform definitions for different display modes.

Available LUTs:
    LUT_4GRAY      - 4-level grayscale rendering (from Adafruit example)

Usage:
    from lut import LUT_4GRAY
    from epd import EPD

    with EPD() as epd:
        # Split 2-bit framebuffer into two 1-bit planes
        black_plane, red_plane = fb.to_planes()
        epd.display_gray(black_plane, red_plane)

Note:
    Custom LUT refresh clears the basemap flag. A full refresh is
    required before partial updates will work correctly again.
"""

# =============================================================================
# 4-Gray LUT
# =============================================================================

# 4-level grayscale LUT from Adafruit's ssd1680 grayscale example
# This waveform drives pixels to achieve 4 distinct gray levels.
#
# Gray mapping (when split into planes):
#   BLACK      = 0b00 (both planes 0)
#   DARK_GRAY  = 0b01 (black=0, red=1)
#   LIGHT_GRAY = 0b10 (black=1, red=0)
#   WHITE      = 0b11 (both planes 1)

LUT_4GRAY = (
    # Voltage Source (VS) levels for each phase L0-L4
    b"\x2a\x60\x15\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L0
    b"\x20\x60\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L1
    b"\x28\x60\x14\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L2
    b"\x00\x60\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L3
    b"\x00\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # VS L4
    # Timing Parameters (TP), Source Repeat (SR), Repeat (RP) for Groups 0-11
    b"\x00\x02\x00\x05\x14\x00\x00"  # Group 0
    b"\x1e\x1e\x00\x00\x00\x00\x01"  # Group 1
    b"\x00\x02\x00\x05\x14\x00\x00"  # Group 2
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 3
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 4
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 5
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 6
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 7
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 8
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 9
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 10
    b"\x00\x00\x00\x00\x00\x00\x00"  # Group 11
    # Frame Rate (FR) and XON settings
    b"\x24\x22\x22\x22\x23\x32\x00\x00\x00"
)

# LUT size in bytes (for validation)
LUT_SIZE = 153
