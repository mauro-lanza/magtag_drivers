"""
Hardware abstraction layer.

Modules:
    spi: Low-level SPI communication for EPD controllers
    buttons: MagTag button handler with event/state tracking
"""
from .spi import SPIDevice
from .buttons import Buttons

__all__ = ["SPIDevice", "Buttons"]
