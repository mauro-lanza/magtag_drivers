"""
MagTag EPD Library v2
=====================
A comprehensive e-paper display driver library for the Adafruit MagTag
and similar GDEY029T94 (296x128) displays using the SSD1680 controller.

Architecture
------------
The library is organized into layers:

    Canvas          High-level drawing + display management
       │
       ├── DrawBuffer    Graphics primitives (shapes, lines)
       │      │
       │      └── FrameBuffer    Pixel buffer with rotation
       │
       ├── TextRenderer  Font rendering with caching
       │      │
       │      └── BF2Font        Font format parser
       │
       └── SSD1680       Display driver (hardware control)
              │
              └── SPIDevice   Low-level SPI communication

    Buttons         MagTag button handler (independent)

Quick Start
-----------
    from canvas import Canvas

    canvas = Canvas()
    canvas.init()
    canvas.text("Hello!", 10, 30)
    canvas.full_refresh()

Advanced Usage
--------------
    # Dependency injection for testing or custom setup
    from hardware.spi import SPIDevice
    from drivers.ssd1680 import SSD1680
    from canvas import Canvas

    spi = SPIDevice.from_board()
    driver = SSD1680(spi)
    canvas = Canvas(driver=driver)

Module Structure
----------------
    lib_v2/
    ├── canvas.py            High-level interface
    ├── buffer/
    │   ├── framebuffer.py   Core pixel buffer
    │   └── draw.py          Shape drawing primitives
    ├── text/
    │   ├── bf2.py           BF2 font format parser
    │   └── renderer.py      Text rendering engine
    ├── drivers/
    │   ├── base.py          DisplayDriver protocol
    │   ├── ssd1680.py       SSD1680 controller driver
    │   ├── commands.py      Command constants
    │   ├── sequences.py     Update sequences
    │   ├── state.py         Driver state machine
    │   └── lut.py           Waveform look-up tables
    └── hardware/
        ├── spi.py           SPI communication layer
        └── buttons.py       Button handler
"""

# Core buffer classes
from buffer import FrameBuffer, DrawBuffer, BLACK, WHITE, DARK_GRAY, LIGHT_GRAY

# Text rendering
from text import BF2Font, TextRenderer

# Hardware layer
from hardware import SPIDevice, Buttons

# Driver layer
from drivers import SSD1680, DisplayDriver, DisplayState, DriverState
from drivers.lut import LUT_4GRAY

# High-level interface
from canvas import Canvas

__all__ = [
    # High-level
    "Canvas",
    # Graphics
    "DrawBuffer",
    "FrameBuffer",
    # Text
    "TextRenderer",
    "BF2Font",
    # Drivers
    "SSD1680",
    "DisplayDriver",
    "DisplayState",
    "DriverState",
    # Hardware
    "SPIDevice",
    "Buttons",
    # LUTs
    "LUT_4GRAY",
    # Colors
    "BLACK",
    "WHITE",
    "DARK_GRAY",
    "LIGHT_GRAY",
]

__version__ = "2.0.0"
