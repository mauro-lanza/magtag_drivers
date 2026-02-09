"""
BF2 Font Format Parser
======================
Handles loading and querying of fonts in the BF2 (Binary Font v2) format.

BF2 is a custom compact font format designed for microcontrollers:
- Fixed-size header (12 bytes)
- Compact glyph index (6 or 8 bytes per entry)
- Packed bitmap data (1 bit per pixel)
- File-based streaming (loads glyphs on demand)

Format Layout:
    [Header: 12 bytes]
    [Index: count × entry_size bytes]
    [Bitmap data: variable]

Header Structure (12 bytes):
    - Magic: "B2" (2 bytes)
    - Version: 1 byte
    - Flags: 1 byte (bit 0=proportional, bit 1=32-bit codepoints)
    - Max width: 1 byte
    - Height: 1 byte
    - Glyph count: 2 bytes (little-endian)
    - Bytes per row: 1 byte
    - Default width: 1 byte
    - Reserved: 2 bytes
"""

import struct

_BF2_MAGIC = b"B2"
_BF2_HEADER_SIZE = 12


class BF2Font:
    """
    BF2 font file reader.

    Keeps the font file open for on-demand glyph data reading.
    Use close() or context manager to release the file handle.

    Attributes:
        height: Glyph height in pixels
        max_w: Maximum glyph width in pixels
        def_w: Default width for missing glyphs
        count: Number of glyphs in the font
        bpr: Bytes per row of glyph bitmap data
        prop: True if proportional (variable-width) font
    """

    def __init__(self, path: str):
        """
        Open and parse a BF2 font file.

        Args:
            path: File system path to the .bf2 font file

        Raises:
            ValueError: If the file is not a valid BF2 font
            OSError: If the file cannot be opened
        """
        self.file = open(path, "rb")

        # Validate magic
        if self.file.read(2) != _BF2_MAGIC:
            self.file.close()
            raise ValueError("Invalid BF2 font file")

        # Parse header (remaining 10 bytes after magic)
        hdr = self.file.read(10)
        (_, flags, self.max_w, self.height, self.count,
         self.bpr, self.def_w, _) = struct.unpack("<BBBBHBBH", hdr)

        self.prop = bool(flags & 1)
        self.entry_size = 8 if (flags & 2) else 6
        self._data_start = _BF2_HEADER_SIZE + self.count * self.entry_size

        # Load glyph index into memory for O(1) lookup
        self.index = {}
        idx_data = self.file.read(self.count * self.entry_size)

        for i in range(self.count):
            off = i * self.entry_size
            if self.entry_size == 8:
                cp, w, o0, o1, o2 = struct.unpack("<IBBBB", idx_data[off:off + 8])
            else:
                cp, w, o0, o1, o2 = struct.unpack("<HBBBB", idx_data[off:off + 6])
            self.index[cp] = (w, o0 | (o1 << 8) | (o2 << 16))

    def get(self, cp: int):
        """
        Look up a glyph by codepoint.

        Args:
            cp: Unicode codepoint

        Returns:
            (width, data_offset) tuple, or None if not found
        """
        return self.index.get(cp)

    def read(self, offset: int) -> bytes:
        """
        Read glyph bitmap data at the given offset.

        Args:
            offset: Byte offset into the bitmap data section

        Returns:
            Raw bitmap bytes (height × bytes_per_row)
        """
        self.file.seek(self._data_start + offset)
        return self.file.read(self.height * self.bpr)

    def close(self):
        """Close the font file handle."""
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False
