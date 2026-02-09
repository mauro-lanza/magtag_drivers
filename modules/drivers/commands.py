"""
SSD1680 Command Constants
=========================
Register addresses and command bytes for the SSD1680 EPD controller.

Organized by functional category for easier navigation.
Reference: SSD1680 Datasheet Section 7 (Command Table)
"""

# =============================================================================
# Panel Configuration
# =============================================================================

CMD_DRIVER_OUTPUT = 0x01      # Driver Output Control - sets gate count (height)
CMD_SOFT_START = 0x0C         # Booster Soft Start - timing for charge pump
CMD_DATA_ENTRY = 0x11         # Data Entry Mode - X/Y increment direction
CMD_SW_RESET = 0x12           # Software Reset - resets all registers to POR

# =============================================================================
# Power Control
# =============================================================================

CMD_DEEP_SLEEP = 0x10         # Deep Sleep Mode - 0x01=retain RAM, 0x03=lose RAM

# =============================================================================
# Temperature & Waveform
# =============================================================================

CMD_TEMP_SENSOR = 0x18        # Temperature Sensor Control - 0x80=use internal
CMD_TEMP_WRITE = 0x1A         # Write to Temperature Register
CMD_TEMP_READ = 0x1B          # Read from Temperature Register (12-bit value)
CMD_LUT = 0x32                # Write Look-Up Table (153 bytes waveform data)

# =============================================================================
# Diagnostics
# =============================================================================

CMD_HV_READY = 0x14           # HV Ready Detection
CMD_VCI_DETECT = 0x15         # VCI Low Voltage Detection
CMD_STATUS = 0x2F             # Status Bit Read (HV ready, VCI, busy, chip ID)
CMD_CRC_CALC = 0x34           # CRC Calculation (triggers CRC compute on RAM)
CMD_CRC_STATUS = 0x35         # CRC Status Read (16-bit CRC result)

# =============================================================================
# Display Update Sequence
# =============================================================================

CMD_ACTIVATE = 0x20           # Master Activation - triggers update sequence
CMD_UPDATE_CTRL1 = 0x21       # Display Update Control 1 - RAM invert options
CMD_UPDATE_CTRL2 = 0x22       # Display Update Control 2 - update sequence select

# =============================================================================
# RAM Access
# =============================================================================

CMD_RAM_BLACK = 0x24          # Write to BW RAM - new/current image data
CMD_RAM_RED = 0x26            # Write to RED RAM - old image for differential
CMD_RAM_READ = 0x27           # Read RAM for Image Detection
CMD_RAM_READ_OPT = 0x41       # Read RAM Option (select BW or RED RAM to read)

# =============================================================================
# Border Control
# =============================================================================

CMD_BORDER = 0x3C             # Border Waveform Control - edge pixel behavior

# =============================================================================
# OTP Reading
# =============================================================================

CMD_OTP_DISPLAY = 0x2D        # OTP Read for Display Option (VCOM, waveform ver)
CMD_OTP_USER_ID = 0x2E        # User ID Read (10 bytes from OTP)

# =============================================================================
# Voltage Registers
# =============================================================================

CMD_VGH = 0x03                # Gate Driving Voltage (VGH)
CMD_VSH_VSL = 0x04            # Source Driving Voltage (VSH1, VSH2, VSL)
CMD_VCOM = 0x2C               # VCOM DC Level Register

# =============================================================================
# Gate Scan Control
# =============================================================================

CMD_GATE_SCAN_START = 0x0F    # Gate Scan Start Position (hardware scrolling)

# =============================================================================
# RAM Address Configuration
# =============================================================================

CMD_RAM_X = 0x44              # Set RAM X Address Start/End (in bytes, 0-15)
CMD_RAM_Y = 0x45              # Set RAM Y Address Start/End (0-295)
CMD_RAM_X_CNT = 0x4E          # Set RAM X Address Counter
CMD_RAM_Y_CNT = 0x4F          # Set RAM Y Address Counter

# =============================================================================
# Auto Write RAM (hardware pattern fills)
# =============================================================================

CMD_AUTO_WRITE_RED = 0x46     # Auto Write RED RAM for Regular Pattern
CMD_AUTO_WRITE_BW = 0x47      # Auto Write B/W RAM for Regular Pattern
