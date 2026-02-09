"""
LUT - Look-Up Tables for EPD Waveforms
======================================
Custom waveform definitions for different display modes.

Available LUTs:
    LUT_4GRAY - 4-level grayscale rendering

LUT Structure (153 bytes for SSD1680):
    - Bytes 0-59: VS (voltage source) for 5 LUTs × 12 groups
    - Bytes 60-143: TP/SR/RP timing (12 groups × 7 bytes)
    - Bytes 144-149: FR frame rate (6 bytes)
    - Bytes 150-152: XON gate scan selection (3 bytes)
"""

# =============================================================================
# 4-Gray LUT
# =============================================================================

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

LUT_SIZE = 153
