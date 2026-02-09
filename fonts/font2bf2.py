#!/usr/bin/env python3
"""
Universal Font Converter
========================
Converts between TTF, BDF, and BF2 font formats for CircuitPython.

Features:
- Input: TTF, OTF, or BDF fonts
- Output: BF2 or BDF format
- Character subsetting from JSON files, text files, or predefined sets
- Preview rendered glyphs in terminal
- Multiple size support for TTF input

BF2 Format:
    Header (12 bytes):
        magic: 2 bytes ("B2")
        version: 1 byte (1)
        flags: 1 byte (bit 0: proportional)
        max_width: 1 byte
        height: 1 byte
        glyph_count: 2 bytes (little-endian)
        bytes_per_row: 1 byte
        default_width: 1 byte
        reserved: 2 bytes

    Index table (glyph_count * 6 bytes, sorted by codepoint):
        codepoint: 2 bytes (little-endian)
        width: 1 byte
        offset: 3 bytes (little-endian, position in glyph data)

    Glyph data:
        Each glyph: height * bytes_per_row bytes (row-major, MSB first)

Requirements:
    pip install bdflib fonttools Pillow

Usage:
    # From BDF to BF2 (most common)
    python font2bf2.py input.bdf output.bf2

    # From TTF at specific size to BF2
    python font2bf2.py input.ttf output.bf2 --size 12

    # Output BDF instead of BF2 (for subsetting or TTF conversion)
    python font2bf2.py input.ttf output.bdf --size 12

    # With character subsetting from JSON files
    python font2bf2.py input.bdf output.bf2 --scan-dir ../projects/anki/anki_decks

    # Using predefined character sets
    python font2bf2.py input.bdf output.bf2 --charset ascii --charset ui

    # Preview specific characters
    python font2bf2.py input.bdf output.bf2 --preview "Hello▲▼"
"""

import argparse
import json
import struct
import tempfile
import subprocess
import sys
from pathlib import Path
from typing import Set, Dict, List, Tuple, Optional
from math import ceil

# =============================================================================
# Character Sets
# =============================================================================

# Basic ASCII printable characters (space through tilde)
ASCII_PRINTABLE = set(chr(i) for i in range(0x0020, 0x007F))

# Extended Latin (Latin-1 Supplement)
LATIN_1_SUPPLEMENT = set(chr(i) for i in range(0x00A0, 0x0100))

# Latin Extended-A
LATIN_EXTENDED_A = set(chr(i) for i in range(0x0100, 0x0180))

# German-specific
GERMAN_CHARS = set('äöüÄÖÜßẞ')

# Common punctuation and symbols
COMMON_SYMBOLS = set('""''—–…•·€£¥©®™°±×÷§¶†‡')

# UI characters (arrows, shapes, checkmarks)
UI_CHARACTERS = set('←→↑↓↔↕▲▼◀▶●○◉◎■□▪▫★☆✓✗✔✘⚠⚡')

# CJK punctuation
CJK_PUNCTUATION = set('。，、；：？！""''（）【】《》')

# IPA characters
IPA_CHARACTERS = set(
    'ɐɑɒæɓʙβɔɕçɖðʤəɘɚɛɜɝɞɟʄɡɠɢʛɦɧħɥʜɨɪʝɭɬɫɮʟɱɯɰŋɳɲɴøɵɸθœɶʘɹɺɾɻʀʁɽʂʃʈʧʉʊʋⱱɤʌɣɯʍχʎʏʑʐʒʔʡʕʢǀǁǂǃˈˌːˑʼʴʰʱʲʷˠˤ˞'
)

# Named character sets
CHARSETS = {
    'ascii': ASCII_PRINTABLE,
    'latin1': LATIN_1_SUPPLEMENT,
    'latin-ext': LATIN_EXTENDED_A,
    'german': GERMAN_CHARS,
    'symbols': COMMON_SYMBOLS,
    'ui': UI_CHARACTERS,
    'cjk-punct': CJK_PUNCTUATION,
    'ipa': IPA_CHARACTERS,
}


def get_default_charset() -> Set[str]:
    """ASCII + Latin-1 + German + common symbols + UI."""
    charset = set()
    charset.update(ASCII_PRINTABLE)
    charset.update(LATIN_1_SUPPLEMENT)
    charset.update(GERMAN_CHARS)
    charset.update(COMMON_SYMBOLS)
    charset.update(UI_CHARACTERS)
    return charset


# =============================================================================
# Character Extraction
# =============================================================================

def extract_chars_from_json(json_path: Path) -> Set[str]:
    """Extract all unique characters from a JSON file."""
    chars = set()
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    def extract_from_value(value):
        if isinstance(value, str):
            chars.update(value)
        elif isinstance(value, list):
            for item in value:
                extract_from_value(item)
        elif isinstance(value, dict):
            for v in value.values():
                extract_from_value(v)

    extract_from_value(data)
    return chars


def extract_chars_from_text(text_path: Path) -> Set[str]:
    """Extract all unique characters from a text file."""
    with open(text_path, 'r', encoding='utf-8') as f:
        return set(f.read())


def scan_directory_for_chars(directory: Path, extensions: List[str] = None) -> Set[str]:
    """Scan directory for files and extract all characters."""
    if extensions is None:
        extensions = ['.json', '.txt', '.md']

    chars = set()
    for ext in extensions:
        for file_path in directory.rglob(f'*{ext}'):
            print(f"  Scanning: {file_path.name}")
            try:
                if ext == '.json':
                    chars.update(extract_chars_from_json(file_path))
                else:
                    chars.update(extract_chars_from_text(file_path))
            except Exception as e:
                print(f"    Warning: Could not read {file_path}: {e}")
    return chars


def load_charset_file(charset_path: Path) -> Set[str]:
    """Load characters from a charset file (U+XXXX format or plain text)."""
    chars = set()
    with open(charset_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('U+'):
                # U+XXXX format
                parts = line.split()
                try:
                    code = int(parts[0][2:], 16)
                    chars.add(chr(code))
                except ValueError:
                    pass
            else:
                # Plain characters
                chars.update(line)
    return chars


# =============================================================================
# BDF Parser (using bdflib)
# =============================================================================

def load_bdf_font(bdf_path: Path, allow_32bit: bool = False) -> Tuple[Dict, dict]:
    """
    Load a BDF font and return glyphs and properties.

    Args:
        bdf_path: Path to BDF file
        allow_32bit: If True, include codepoints > U+FFFF

    Returns:
        Tuple of (glyphs dict, properties dict)
        glyphs: {codepoint: {'width': int, 'data': list of row bytes}}
    """
    try:
        from bdflib import reader
    except ImportError:
        print("Error: bdflib not installed. Run: pip install bdflib")
        sys.exit(1)

    with open(bdf_path, 'rb') as f:
        font = reader.read_bdf(f)

    props = font.properties
    font_ascent = props.get(b'FONT_ASCENT', 8)
    font_descent = props.get(b'FONT_DESCENT', 0)
    font_height = font_ascent + font_descent

    # Determine max width
    max_width = 0
    for glyph in font.glyphs:
        max_width = max(max_width, glyph.advance)

    glyphs = {}
    max_codepoint = 0xFFFFFFFF if allow_32bit else 0xFFFF

    for glyph in font.glyphs:
        if glyph.codepoint is None or glyph.codepoint > max_codepoint:
            continue

        # BDF data is stored bottom-to-top, reverse it
        glyph_data = list(reversed(glyph.data))
        g_h = glyph.bbH
        g_y = glyph.bbY  # offset from baseline

        # Position glyph in output grid
        baseline_row = font_ascent - 1
        glyph_bottom = baseline_row - g_y
        glyph_top = glyph_bottom - g_h + 1

        # Build row-major bitmap
        bytes_per_row = ceil(max_width / 8)
        rows = []

        for y in range(font_height):
            row_byte = 0
            src_row = y - glyph_top

            if 0 <= src_row < len(glyph_data):
                # Get source row bits, shift to align with MSB
                src_bits = glyph_data[src_row]
                # BDF stores bits left-aligned in the bounding box
                # Shift to fit in max_width
                shift = (bytes_per_row * 8) - glyph.bbW
                row_byte = src_bits << (shift - glyph.bbX) if shift > glyph.bbX else src_bits >> (glyph.bbX - shift)
                row_byte &= (1 << (bytes_per_row * 8)) - 1

            # Convert to bytes
            row_bytes = row_byte.to_bytes(bytes_per_row, 'big')
            rows.append(row_bytes)

        glyphs[glyph.codepoint] = {
            'width': glyph.advance,
            'bbw': glyph.bbW + glyph.bbX,  # actual pixel extent
            'data': b''.join(rows),
        }

    properties = {
        'height': font_height,
        'max_width': max_width,
        'ascent': font_ascent,
        'descent': font_descent,
    }

    return glyphs, properties


# =============================================================================
# Custom Glyph Injection
# =============================================================================

def create_arrow_glyphs(height: int, width: int) -> Dict:
    """
    Create up/down arrow glyphs (▲ ▼) for any font size.

    Args:
        height: Font height in pixels
        width: Glyph width in pixels

    Returns:
        Dict with codepoints 0x25B2 (▲) and 0x25BC (▼)
    """
    bytes_per_row = ceil(width / 8)
    glyphs = {}

    # Calculate arrow dimensions based on font size
    # Arrow should be roughly 60-70% of height, centered vertically
    arrow_height = max(4, int(height * 0.6))
    start_row = (height - arrow_height) // 2

    # ▲ Up arrow (U+25B2)
    rows_up = []
    for row in range(height):
        relative_row = row - start_row
        if 0 <= relative_row < arrow_height:
            # Triangle: starts narrow at top, widens at bottom
            # At relative_row 0: 1 pixel, at arrow_height-1: full width
            pixels_in_row = 1 + (relative_row * 2 * (width - 2)) // (arrow_height - 1) if arrow_height > 1 else width
            pixels_in_row = min(pixels_in_row, width - 1)
            if pixels_in_row < 1:
                pixels_in_row = 1

            # Center the pixels
            start_pixel = (width - pixels_in_row) // 2

            # Build row bitmap
            row_bits = 0
            for px in range(pixels_in_row):
                bit_pos = (bytes_per_row * 8 - 1) - (start_pixel + px)
                if bit_pos >= 0:
                    row_bits |= (1 << bit_pos)

            rows_up.append(row_bits.to_bytes(bytes_per_row, 'big'))
        else:
            rows_up.append(bytes(bytes_per_row))

    glyphs[0x25B2] = {
        'width': width,
        'data': b''.join(rows_up),
    }

    # ▼ Down arrow (U+25BC) - flip the up arrow vertically
    rows_down = list(reversed(rows_up))
    glyphs[0x25BC] = {
        'width': width,
        'data': b''.join(rows_down),
    }

    return glyphs


def inject_missing_ui_glyphs(glyphs: Dict, properties: dict):
    """
    Inject commonly needed UI glyphs if they're missing.
    Currently handles: ▲ (U+25B2), ▼ (U+25BC)
    """
    height = properties['height']
    width = properties['max_width']

    arrow_codepoints = [0x25B2, 0x25BC]  # ▲ ▼

    if any(cp not in glyphs for cp in arrow_codepoints):
        print(f"Injecting missing arrow glyphs (▲▼)...")
        arrows = create_arrow_glyphs(height, width)
        for cp, glyph in arrows.items():
            if cp not in glyphs:
                glyphs[cp] = glyph


# =============================================================================
# TTF to BDF Conversion
# =============================================================================

def ttf_to_bdf(ttf_path: Path, size: int, output_dir: Path = None) -> Path:
    """
    Convert TTF to BDF using otf2bdf.

    Returns path to generated BDF file.
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp())

    bdf_path = output_dir / f"{ttf_path.stem}_{size}pt.bdf"

    # Check if otf2bdf is available
    try:
        subprocess.run(['otf2bdf', '-h'], capture_output=True, check=False)
    except FileNotFoundError:
        print("Error: otf2bdf not found. Install with:")
        print("  macOS: brew install otf2bdf")
        print("  Linux: sudo apt install otf2bdf")
        sys.exit(1)

    print(f"Converting TTF to BDF at {size}pt...")
    result = subprocess.run(
        ['otf2bdf', '-p', str(size), '-o', str(bdf_path), str(ttf_path)],
        capture_output=True,
        text=True
    )

    if result.returncode != 0 or not bdf_path.exists():
        print(f"Error converting TTF: {result.stderr}")
        sys.exit(1)

    return bdf_path


# =============================================================================
# BF2 Writer
# =============================================================================

BF2_MAGIC = b"B2"
BF2_VERSION = 1
BF2_HEADER_SIZE = 12
BF2_INDEX_ENTRY_SIZE = 6
FLAG_PROPORTIONAL = 0x01
FLAG_32BIT_CODEPOINTS = 0x02


def write_bf2(output_path: Path, glyphs: Dict, properties: dict,
              charset: Set[str] = None, proportional: bool = True,
              use_32bit: bool = False):
    """
    Write glyphs to BF2 format.

    Args:
        output_path: Output file path
        glyphs: Dict of {codepoint: {'width': int, 'data': bytes}}
        properties: Dict with 'height', 'max_width'
        charset: Optional set of characters to include (None = all)
        proportional: Whether to store per-glyph widths
        use_32bit: Use 32-bit codepoints (for glyphs > U+FFFF)
    """
    height = properties['height']
    max_width = properties['max_width']
    bytes_per_row = ceil(max_width / 8)

    # Filter glyphs by charset
    if charset:
        codepoints = sorted(ord(c) for c in charset if ord(c) in glyphs)
    else:
        codepoints = sorted(glyphs.keys())

    if not codepoints:
        print("Error: No glyphs to write!")
        return

    # Determine default width (most common or average)
    widths = [glyphs[cp]['width'] for cp in codepoints]
    default_width = max(set(widths), key=widths.count)

    # Check if actually proportional
    is_proportional = proportional and len(set(widths)) > 1

    print(f"Writing BF2: {len(codepoints)} glyphs, {max_width}x{height}, " +
          f"{'proportional' if is_proportional else 'monospace'}")

    # Build glyph data and index
    glyph_data = bytearray()
    index_entries = []

    for cp in codepoints:
        glyph = glyphs[cp]
        width = glyph['width'] if is_proportional else 0
        offset = len(glyph_data)

        # Index entry: codepoint (2 or 4), width (1), offset (3)
        if use_32bit:
            index_entries.append(struct.pack('<IB', cp, width) +
                               offset.to_bytes(3, 'little'))
        else:
            index_entries.append(struct.pack('<HB', cp, width) +
                               offset.to_bytes(3, 'little'))

        # Glyph data
        glyph_data.extend(glyph['data'])

    # Build header
    flags = FLAG_PROPORTIONAL if is_proportional else 0
    if use_32bit:
        flags |= FLAG_32BIT_CODEPOINTS
    header = struct.pack(
        '<2sBBBBHBBH',
        BF2_MAGIC,
        BF2_VERSION,
        flags,
        max_width,
        height,
        len(codepoints),
        bytes_per_row,
        default_width,
        0  # reserved
    )

    # Write file
    with open(output_path, 'wb') as f:
        f.write(header)
        for entry in index_entries:
            f.write(entry)
        f.write(glyph_data)

    size_kb = output_path.stat().st_size / 1024
    print(f"Created: {output_path} ({size_kb:.1f} KB)")


# =============================================================================
# BDF Writer
# =============================================================================

def write_bdf(output_path: Path, glyphs: Dict, properties: dict,
              charset: Set[str] = None, font_name: str = None):
    """
    Write glyphs to BDF format.

    Args:
        output_path: Output file path
        glyphs: Dict of {codepoint: {'width': int, 'data': bytes}}
        properties: Dict with 'height', 'max_width', 'ascent', 'descent'
        charset: Optional set of characters to include (None = all)
        font_name: Font name for BDF header
    """
    height = properties['height']
    max_width = properties['max_width']
    ascent = properties.get('ascent', height)
    descent = properties.get('descent', 0)
    bytes_per_row = ceil(max_width / 8)

    # Filter glyphs by charset
    if charset:
        codepoints = sorted(ord(c) for c in charset if ord(c) in glyphs)
    else:
        codepoints = sorted(glyphs.keys())

    if not codepoints:
        print("Error: No glyphs to write!")
        return

    # Generate font name
    if font_name is None:
        font_name = output_path.stem.replace('-', '_').replace(' ', '_')

    print(f"Writing BDF: {len(codepoints)} glyphs, {max_width}x{height}")

    with open(output_path, 'w', encoding='utf-8') as f:
        # BDF Header
        f.write("STARTFONT 2.1\n")
        f.write(f"FONT -{font_name}-medium-r-normal--{height}-{height*10}-75-75-c-{max_width*10}-iso10646-1\n")
        f.write(f"SIZE {height} 75 75\n")
        f.write(f"FONTBOUNDINGBOX {max_width} {height} 0 {-descent}\n")

        # Properties
        f.write("STARTPROPERTIES 6\n")
        f.write(f"FONT_ASCENT {ascent}\n")
        f.write(f"FONT_DESCENT {descent}\n")
        f.write(f"PIXEL_SIZE {height}\n")
        f.write(f"POINT_SIZE {height * 10}\n")
        f.write("SPACING \"C\"\n")
        f.write(f"DEFAULT_CHAR {codepoints[0] if codepoints else 32}\n")
        f.write("ENDPROPERTIES\n")

        f.write(f"CHARS {len(codepoints)}\n")

        # Write each glyph
        for cp in codepoints:
            glyph = glyphs[cp]
            width = glyph['width']
            data = glyph['data']

            # Glyph name (use Unicode name or hex)
            if cp < 128 and chr(cp).isprintable():
                name = chr(cp) if chr(cp).isalnum() else f"U+{cp:04X}"
            else:
                name = f"U+{cp:04X}"
            # Escape special chars in name
            name = name.replace(' ', '_')

            f.write(f"STARTCHAR {name}\n")
            f.write(f"ENCODING {cp}\n")
            f.write(f"SWIDTH {width * 1000 // height} 0\n")
            f.write(f"DWIDTH {width} 0\n")
            f.write(f"BBX {width} {height} 0 {-descent}\n")
            f.write("BITMAP\n")

            # Write bitmap rows
            for row in range(height):
                row_start = row * bytes_per_row
                row_bytes = data[row_start:row_start + bytes_per_row]

                # Convert to hex string
                hex_str = ''.join(f'{b:02X}' for b in row_bytes)
                f.write(f"{hex_str}\n")

            f.write("ENDCHAR\n")

        f.write("ENDFONT\n")

    size_kb = output_path.stat().st_size / 1024
    print(f"Created: {output_path} ({size_kb:.1f} KB)")


# =============================================================================
# Preview
# =============================================================================

def preview_glyphs(glyphs: Dict, properties: dict, text: str):
    """Print ASCII art preview of glyphs."""
    height = properties['height']
    max_width = properties['max_width']
    bytes_per_row = ceil(max_width / 8)

    print(f"\nPreview ({max_width}x{height}):")
    print("-" * 40)

    for char in text:
        cp = ord(char)
        if cp not in glyphs:
            print(f"'{char}' (U+{cp:04X}): NOT FOUND")
            continue

        glyph = glyphs[cp]
        width = glyph['width']
        data = glyph['data']

        # Find actual used width (rightmost set pixel)
        actual_width = 0
        for row in range(height):
            row_start = row * bytes_per_row
            row_bytes = data[row_start:row_start + bytes_per_row]
            for col in range(max_width - 1, -1, -1):
                byte_idx = col // 8
                bit_idx = 7 - (col % 8)
                if byte_idx < len(row_bytes) and (row_bytes[byte_idx] >> bit_idx) & 1:
                    actual_width = max(actual_width, col + 1)
                    break

        # Display width is max of advance and actual pixels
        display_width = max(width, actual_width)
        width_note = f" (bbW>{width})" if actual_width > width else ""
        print(f"'{char}' (U+{cp:04X}) width={width}{width_note}:")

        for row in range(height):
            row_start = row * bytes_per_row
            row_bytes = data[row_start:row_start + bytes_per_row]

            line = ""
            for col in range(display_width):
                byte_idx = col // 8
                bit_idx = 7 - (col % 8)
                if byte_idx < len(row_bytes) and (row_bytes[byte_idx] >> bit_idx) & 1:
                    line += "█"
                else:
                    line += "·"
            print(f"  {line}")
        print()


# =============================================================================
# Main
# =============================================================================

def print_charset_stats(chars: Set[str], name: str):
    """Print statistics about a character set."""
    ascii_count = sum(1 for c in chars if ord(c) < 128)
    latin = sum(1 for c in chars if 128 <= ord(c) < 0x0250)
    other = len(chars) - ascii_count - latin

    print(f"\n{name}:")
    print(f"  Total: {len(chars)} characters")
    print(f"  ASCII: {ascii_count}, Latin Extended: {latin}, Other: {other}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert TTF/BDF fonts to BF2 or BDF format for CircuitPython',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic BDF to BF2 conversion
  python font2bf2.py spleen-8x16.bdf spleen-8x16.bf2

  # TTF to BF2 at 12pt
  python font2bf2.py M_PLUS_1p/MPLUS1p-Regular.ttf mplus-12.bf2 --size 12

  # TTF to BDF (for further editing or subsetting)
  python font2bf2.py M_PLUS_1p/MPLUS1p-Regular.ttf mplus-12.bdf --size 12

  # BDF subsetting (output smaller BDF)
  python font2bf2.py full-font.bdf subset.bdf --charset ascii --charset ui

  # With character subsetting from Anki decks
  python font2bf2.py input.bdf output.bf2 --scan-dir ../projects/anki/anki_decks

  # Using predefined charsets
  python font2bf2.py input.bdf output.bf2 --charset ascii --charset ui

  # Preview specific characters
  python font2bf2.py input.bdf output.bf2 --preview "Hello▲▼"

  # Preview only (no output file required)
  python font2bf2.py input.bdf --preview "Test▲▼"

Available charsets: ascii, latin1, latin-ext, german, symbols, ui, cjk-punct, ipa
        """
    )

    parser.add_argument('input', type=Path, help='Input font file (TTF, OTF, or BDF)')
    parser.add_argument('output', type=Path, nargs='?', help='Output file (optional for preview-only)')

    parser.add_argument('--size', '-s', type=int, default=12,
                       help='Point size for TTF conversion (default: 12)')

    parser.add_argument('--scan-dir', '-d', type=Path,
                       help='Directory to scan for JSON/text files')

    parser.add_argument('--chars-file', '-c', type=Path,
                       help='File containing characters to include')

    parser.add_argument('--charset', action='append', dest='charsets',
                       choices=list(CHARSETS.keys()),
                       help='Predefined charset to include (can repeat)')

    parser.add_argument('--all-glyphs', action='store_true',
                       help='Include all glyphs from font (no subsetting)')

    parser.add_argument('--32bit', dest='use_32bit', action='store_true',
                       help='Use 32-bit codepoints (include glyphs > U+FFFF)')

    parser.add_argument('--monospace', action='store_true',
                       help='Force monospace output (no per-glyph widths)')

    parser.add_argument('--inject-arrows', action='store_true',
                       help='Inject arrow glyphs (▲▼) if missing from font')

    parser.add_argument('--use-bbx-width', action='store_true',
                       help='Use max(advance, bbx) as width (prevents clipping)')

    parser.add_argument('--preview', type=str,
                       help='Preview specific characters after conversion')

    parser.add_argument('--preview-only', action='store_true',
                       help='Only preview, don\'t write output')

    args = parser.parse_args()

    # If no output specified, require --preview and enable preview-only mode
    if args.output is None:
        if not args.preview:
            parser.error("--preview is required when no output file is specified")
        args.preview_only = True

    # Validate input
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    # ==========================================================================
    # Build character set
    # ==========================================================================

    if args.all_glyphs:
        charset = None
        print("Including all glyphs from font")
    else:
        charset = set()

        # Add predefined charsets
        if args.charsets:
            for name in args.charsets:
                charset.update(CHARSETS[name])
                print(f"Added charset '{name}': {len(CHARSETS[name])} chars")
        else:
            # Default charset
            charset = get_default_charset()
            print(f"Using default charset: {len(charset)} chars")

        # Scan directory
        if args.scan_dir:
            if args.scan_dir.exists():
                print(f"\nScanning: {args.scan_dir}")
                scanned = scan_directory_for_chars(args.scan_dir)
                new_chars = scanned - charset
                print(f"Found {len(scanned)} chars, {len(new_chars)} new")
                charset.update(scanned)
            else:
                print(f"Warning: Directory not found: {args.scan_dir}")

        # Load charset file
        if args.chars_file:
            if args.chars_file.exists():
                extra = load_charset_file(args.chars_file)
                charset.update(extra)
                print(f"Added {len(extra)} chars from {args.chars_file}")
            else:
                print(f"Warning: Charset file not found: {args.chars_file}")

        print_charset_stats(charset, "Final charset")

    # ==========================================================================
    # Load font
    # ==========================================================================

    suffix = args.input.suffix.lower()

    if suffix == '.bdf':
        print(f"\nLoading BDF: {args.input}")
        glyphs, properties = load_bdf_font(args.input, allow_32bit=args.use_32bit)
    elif suffix in ('.ttf', '.otf'):
        print(f"\nConverting TTF at {args.size}pt: {args.input}")
        bdf_path = ttf_to_bdf(args.input, args.size)
        glyphs, properties = load_bdf_font(bdf_path, allow_32bit=args.use_32bit)
    else:
        print(f"Error: Unsupported font format: {suffix}")
        print("Supported: .ttf, .otf, .bdf")
        sys.exit(1)

    print(f"Loaded {len(glyphs)} glyphs, {properties['max_width']}x{properties['height']}")

    # ==========================================================================
    # Apply BBX width if requested
    # ==========================================================================

    if args.use_bbx_width:
        adjusted = 0
        for cp, glyph in glyphs.items():
            bbw = glyph.get('bbw', glyph['width'])
            if bbw > glyph['width']:
                glyph['width'] = bbw
                adjusted += 1
        if adjusted:
            print(f"Adjusted {adjusted} glyphs to use BBX width (prevents clipping)")

    # ==========================================================================
    # Inject missing glyphs
    # ==========================================================================

    if args.inject_arrows:
        inject_missing_ui_glyphs(glyphs, properties)

    # ==========================================================================
    # Preview
    # ==========================================================================

    if args.preview:
        preview_glyphs(glyphs, properties, args.preview)

    if args.preview_only:
        return

    # ==========================================================================
    # Write output (BF2 or BDF based on extension)
    # ==========================================================================

    args.output.parent.mkdir(parents=True, exist_ok=True)

    output_ext = args.output.suffix.lower()
    if output_ext == '.bdf':
        write_bdf(args.output, glyphs, properties, charset)
    elif output_ext in ('.bf2', '.bin'):
        write_bf2(args.output, glyphs, properties, charset,
                  proportional=not args.monospace,
                  use_32bit=args.use_32bit)
    else:
        print(f"Warning: Unknown output extension '{output_ext}', defaulting to BF2")
        write_bf2(args.output, glyphs, properties, charset,
                  proportional=not args.monospace,
                  use_32bit=args.use_32bit)

    # Final preview
    if args.preview:
        print("\nOutput written successfully!")


if __name__ == '__main__':
    main()
