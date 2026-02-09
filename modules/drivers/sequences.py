"""
SSD1680 Update Sequences & Configuration Constants
===================================================
Values for the Display Update Control 2 register (0x22) and other
configuration constants.

The update sequence controls:
  - Clock enable/disable
  - Analog power enable/disable
  - Temperature sensor reading
  - LUT loading (Mode 1 or Mode 2)
  - Display driving
  - Power-down sequence
"""

# =============================================================================
# Update Sequences (Register 0x22 values)
# =============================================================================

# Full refresh sequences (Mode 1 - standard waveform)
SEQ_FULL = 0xF7               # Clk -> Analog -> Temp -> Mode1 -> Power Off
                              # Used for: Initial display, clearing ghosting
                              # Time: ~1.4s at 25°C

SEQ_CUSTOM_LUT = 0xC7         # Clk -> Analog -> Mode1 -> Power Off (no temp)
                              # Used for: Custom LUT refresh (LUT already loaded)

# Partial refresh sequences (Mode 2 - differential waveform)
SEQ_PARTIAL = 0xFC            # Clk -> Analog -> Temp -> Mode2 -> STAYS POWERED
                              # Used for: Partial updates with temp compensation
                              # Time: ~0.3s at 25°C

# Power control sequences
SEQ_POWER_ON = 0xE0           # Power on analog circuits only
SEQ_POWER_OFF = 0x83          # Power off analog circuits only

# Temperature reading sequence
SEQ_LOAD_TEMP = 0xB1          # Load temperature value from internal sensor


# =============================================================================
# Deep Sleep Modes (Register 0x10 values)
# =============================================================================

SLEEP_MODE_1 = 0x01           # RAM retained, ~0.5µA, wake needs HW reset
SLEEP_MODE_2 = 0x03           # RAM lost, lowest power, wake needs full init


# =============================================================================
# Voltage Defaults (for custom LUT waveforms)
# =============================================================================

DEFAULT_VGH = 0x17            # Gate High Voltage: 20V
DEFAULT_VSH1 = 0x41           # Source High Voltage 1: +15V
DEFAULT_VSH2 = 0xA8           # Source High Voltage 2: +5V
DEFAULT_VSL = 0x32            # Source Low Voltage: -15V
DEFAULT_VCOM = 0x50           # VCOM DC Level: -2.0V


# =============================================================================
# Temperature Sensor
# =============================================================================

TEMP_SENSOR_INTERNAL = 0x80   # Use internal temperature sensor
TEMP_MIN = 0                  # Minimum operating temperature (°C)
TEMP_MAX = 50                 # Maximum operating temperature (°C)


# =============================================================================
# Operation Timeouts (seconds)
# =============================================================================

TIMEOUT_DEFAULT = 10.0        # Default for unknown operations
TIMEOUT_FULL = 5.0            # Full refresh: ~1.4s typical
TIMEOUT_PARTIAL = 1.0         # Partial refresh: ~0.3s typical
TIMEOUT_COMMAND = 0.5         # Simple commands
TIMEOUT_POWER = 0.5           # Power on/off sequences


# =============================================================================
# Booster Soft Start (Register 0x0C)
# =============================================================================

SOFT_START_DEFAULT = (0x8B, 0x9C, 0x96, 0x0F)


# =============================================================================
# Border Waveform (Register 0x3C)
# =============================================================================

BORDER_FULL = 0x05            # GS Transition - follows LUT waveform
BORDER_PARTIAL = 0x80         # VCOM level - stable border for partials


# =============================================================================
# Data Entry Mode (Register 0x11)
# =============================================================================

DATA_ENTRY_INC = 0x03         # X+, Y+ with X incrementing first
