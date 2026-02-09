"""
Text rendering subsystem.

Modules:
    bf2: BF2 font format parser
    renderer: Text renderer with multi-font support and caching
"""
from .bf2 import BF2Font
from .renderer import TextRenderer

__all__ = ["BF2Font", "TextRenderer"]
