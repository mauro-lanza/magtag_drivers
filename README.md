# SSD1680 E-Paper Driver for MagTag (v2)

Custom CircuitPython driver for the Adafruit MagTag's 2.9" e-paper display (SSD1680 controller, GDEY029T94 panel) with **partial refresh support** — achieving ~0.31s updates instead of the standard ~1.4s.

## Why This Exists

The built-in `adafruit_ssd1680` library only supports full refresh (~1.4s per update), which is too slow for interactive applications like flashcards. This driver bypasses `displayio` entirely and communicates directly via SPI to enable partial refresh mode.

**GxEPD2 Compatible:** The coordinate system, buffer layout, and power management patterns match the popular [GxEPD2](https://github.com/ZinggJM/GxEPD2) Arduino library, making future C++ porting straightforward.

### Why Not displayio?

E-paper needs things `displayio` doesn't expose:

1. **Explicit refresh control** — Partial vs full, timing-critical
2. **Differential buffer access** — Hardware RAM comparison needs direct manipulation
3. **SPI-ready format** — Our bytearray matches SSD1680's RAM format (zero conversion)

The tradeoff: We can't use `bitmaptools.blit()` (it operates on `displayio.Bitmap`, not bytearrays). Our pure-Python blit is adequate since it's still faster than display refresh time.

## Performance

Benchmarked on MagTag 2.9" GDEY029T94 (ESP32-S2, SPI @ 20MHz):

| Refresh Mode | Total   | BUSY Time | Use Case |
|--------------|---------|-----------|----------|
| Full         | ~1.51s  | ~1.40s    | Initial display, clear ghosting |
| Full (fast)  | ~1.96s  | ~1.83s    | Temperature LUT trick, less flashing |
| Partial      | ~0.36s  | ~0.31s    | Fast updates (4.5x faster!) |
| Region       | ~0.36s  | ~0.31s    | Update specific area |
| 4-gray       | ~3.36s  | ~3.10s    | Grayscale images, dithered photos |
| Custom LUT   | ~3.02s  | ~2.80s    | User-defined waveforms |
| Power on     | ~96ms   | -         | Wake from power-off state |
| Power off    | ~143ms  | -         | Prevent screen fading when idle |

## Architecture

```
┌─────────────┐     ┌──────────┐
│   Canvas    │     │ Buttons  │  (independent)
└──────┬──────┘     └──────────┘
       │
       ├── DrawBuffer ──── FrameBuffer (pixel buffer, rotation, 1/2-bit depth)
       │
       ├── TextRenderer ── BF2Font (multi-font stack, LRU cache)
       │
       └── SSD1680 ──────── SPIDevice (low-level SPI + GPIO)
              │
              └── DriverState (state machine + DisplayState enum)
```

Each layer has a single responsibility and can be injected independently (for testing or custom setups). `Canvas` is the typical entry point — it auto-creates all dependencies for MagTag hardware.

## Project Structure

```
magtag_drivers/
├── modules/                        # Main library package (v2.0.0)
│   ├── __init__.py                 # Package exports and version
│   ├── canvas.py                   # High-level drawing + display API
│   ├── example_architecture.py     # Usage patterns and examples
│   ├── buffer/                     # Framebuffer & drawing subsystem
│   │   ├── framebuffer.py          # Core pixel buffer (1/2-bit, rotation, LUT conversion)
│   │   └── draw.py                 # Shape drawing primitives (extends FrameBuffer)
│   ├── text/                       # Text rendering subsystem
│   │   ├── bf2.py                  # BF2 font format parser
│   │   └── renderer.py             # Multi-font renderer with LRU cache
│   ├── drivers/                    # Display driver layer
│   │   ├── base.py                 # DisplayDriver abstract protocol (duck typing)
│   │   ├── ssd1680.py              # SSD1680 controller driver
│   │   ├── commands.py             # SSD1680 register/command constants
│   │   ├── sequences.py            # Update sequences, timeouts, voltage defaults
│   │   ├── state.py                # DriverState machine + DisplayState enum
│   │   └── lut.py                  # Waveform LUTs (4-gray, etc.)
│   ├── hardware/                   # Hardware abstraction layer
│   │   ├── spi.py                  # SPI communication + GPIO management
│   │   └── buttons.py              # Button handler (events, state, deep sleep)
│   └── _archive/                   # Legacy v1 code (reference only)
├── demos/
│   ├── benchmark_v2/               # Performance benchmark suite (interactive + headless)
│   └── general_demo/               # Multi-page interactive Canvas/driver demos
├── fonts/
│   └── font2bf2.py                 # Universal font converter (TTF/BDF → BF2)
├── scripts/
│   └── run_benchmarks.lua          # TIO Lua script for serial benchmark automation
├── GDEY029T94_docs/                # External documentation from Good Display
└── libraries/                      # External dependencies
```

## Quick Start

```python
from canvas import Canvas

canvas = Canvas()
canvas.init()

canvas.clear()
canvas.text("Hello World!", 10, 10, scale=2)
canvas.rect(10, 60, 100, 30)
canvas.fill_circle(200, 64, 20)

canvas.full_refresh()        # First refresh must be full (establishes basemap)

canvas.clear()
canvas.text("Updated!", 10, 10)
canvas.partial_refresh()     # ~0.31s
```

### With Dependency Injection

```python
from hardware.spi import SPIDevice
from drivers.ssd1680 import SSD1680
from buffer import DrawBuffer
from text import TextRenderer
from canvas import Canvas

spi = SPIDevice.from_board()
driver = SSD1680(spi, use_diff_buffer=True)
buffer = DrawBuffer(driver.WIDTH, driver.HEIGHT, depth=1, rotation=90)
text = TextRenderer(buffer, cache_size=4096)

canvas = Canvas(driver=driver, buffer=buffer, text_renderer=text)
```

### Grayscale (2-bit)

```python
from canvas import Canvas, BLACK, DARK_GRAY, LIGHT_GRAY, WHITE

canvas = Canvas(depth=2)
canvas.init()
canvas.fill_rect(10, 10, 50, 50, DARK_GRAY)
canvas.full_refresh()  # Automatically uses 4-gray LUT
```

## Installation

```bash
cp -r modules/ /Volumes/CIRCUITPY/lib/
```

## Key Design Decisions

### Differential Buffer: Software Pre-Refresh vs GxEPD2 Post-Refresh

The SSD1680 uses two RAM buffers for differential updates: RAM 0x24 (new) vs RAM 0x26 (old). GxEPD2 syncs these with `writeImageAgain()` *after* refresh (3 SPI transfers). We maintain a software `_prev_buffer` and write it *before* refresh (2 SPI transfers).

| Approach | SPI Transfers | SPI Time | Notes |
|----------|---------------|----------|-------|
| No buffer | 1 | 3.0ms | Ghosts accumulate |
| **Our `_prev_buffer`** | **2** | **5.3ms** | **Recommended** |
| GxEPD2 writeAgain | 3 | 8.0ms | Correct, slower |

The 4.7KB buffer (0.2% of ESP32-S2's ~2MB RAM) saves 2.7ms (33%) per partial update.

### State Machine vs Bitflags

V1 used GxEPD2-style bitflags (`_STATE_POWER_ON | _STATE_HIBERNATING | ...`). V2 replaces this with a `DriverState` class and `DisplayState` enum — self-documenting, type-safe, with named transitions like `on_full_refresh_complete()`.

State flow:
```
UNINITIALIZED → READY → UPDATING → READY → SLEEPING → (hardware reset) → UNINITIALIZED
```

### Hibernate Behavior (GxEPD2 Pattern)

Power management differs by refresh mode:

- **Partial refresh** → Stays awake (fast subsequent updates expected)
- **Full refresh** → Auto-hibernates (image safe if power cut)

This matches GxEPD2's design: partial updates are fast and frequent, full refresh is the natural "cleanup" point. The display auto-wakes from hibernate on the next operation via hardware reset.

### Update Command Selection (0x22 register)

We benchmarked multiple update codes on this specific panel:

| Code | Source | Mode | Measured | Notes |
|------|--------|------|----------|-------|
| **0xF7** | SSD1680 datasheet | Full | 1.40s | Selected — standard full |
| 0xD7 | GxEPD2 `useFastFullUpdate` | Full | 1.83s | Slower on this panel |
| **0xFC** | GxEPD2 | Partial | 0.31s | Selected — 31% faster than 0xFF |
| 0xFF | Good Display sample | Partial | 0.45s | Original sample code |
| **0xC7** | Good Display sample | Custom LUT | 1.83s | Selected — for custom waveforms |

### 4-Gray: Custom LUT vs Temperature Trick

Good Display's sample code uses a temperature trick (register 0x1A = 90°C) to access different OTP LUTs. This didn't produce reliable grayscale on the GDEY029T94 panel. We use a custom 153-byte LUT waveform instead — more reliable and portable. The 2-bit framebuffer stores 4 gray levels natively, with LUT-based conversion to the two RAM planes the hardware expects.

### Text: Multi-Font Stacking vs Named Font Switching

V1 had `load_font()` / `set_font("name")` / `reset_font()` for switching between cached named fonts. V2 replaces this with a font stack: `load_font()` sets the base, `add_font()` layers on extensions. Glyphs resolve by searching fonts in load order (first match wins). This naturally supports the common pattern of a small ASCII font + optional icon/CJK extension fonts without explicit switching.

### Text: Why Not Horizontal Spans?

We tested u8g2-style horizontal span drawing (detecting pixel runs and drawing with `hline`). In C this is faster, but in Python the function call overhead exceeded the savings. Span detection added ~20-45% to draw times. Direct pixel-loop rendering is faster in interpreted Python.

### Buffer: Lazy LUT Initialization

The 2-bit → 1-bit and 2-bit → plane conversion LUTs (768 bytes total) are only allocated on first use. Most users stay in 1-bit mono mode and never pay this cost.

### Buffer: Byte-Aligned Fast Paths

`hline` and `fill_rect` detect when pixel spans align to byte boundaries and use whole-byte fill operations instead of per-pixel bit manipulation. For the common case of full-width clears and rectangular UI elements, this is significantly faster.

### SPI: Pre-allocated Command Buffers

The `SPIDevice` pre-allocates small bytearrays for command/data transmission, avoiding repeated allocation during display updates. On CircuitPython's allocator, this reduces GC pressure during time-sensitive refresh sequences.

### Duck Typing over ABC

`DisplayDriver` is an abstract base defined with duck typing (raising `NotImplementedError`) rather than Python's `abc.ABC`, since CircuitPython doesn't support the `abc` module.

## Font Tooling

`font2bf2.py` converts TTF, OTF, or BDF fonts to the BF2 binary format. Key features:

- Character subsetting from JSON files, text files, or predefined sets (`--charset ascii`, `--charset ui`)
- Project scanning for used characters (`--scan-dir`)
- 16-bit or 32-bit codepoint modes
- Preview rendering in terminal (`--preview "ABC▲▼"`)

```bash
# Most common: BDF → BF2
python fonts/font2bf2.py input.bdf output.bf2

# TTF at specific size
python fonts/font2bf2.py MyFont.ttf myfont-12pt.bf2 --size 12

# All glyphs, 32-bit codepoints
python fonts/font2bf2.py input.bdf output.bf2 --all-glyphs --32bit
```

Requirements: `pip install bdflib fonttools Pillow`

## Hardware Reference

### Display
- **Panel:** GDEY029T94 — 296 × 128 pixels, 128 wide × 296 tall physical
- **Controller:** SSD1680
- **Rotation 90** gives landscape (296 × 128 logical) — the default

### SPI Configuration
- Write: 20MHz / Read: 2.5MHz (per datasheet)
- Data entry mode 0x03: X+, Y+, X first (GxEPD2-compatible)
- RAM 0x24 = current frame, RAM 0x26 = previous frame

### MagTag Pins
- SPI: `board.EPD_SCK`, `board.EPD_MOSI`
- Control: `board.EPD_CS`, `board.EPD_DC`, `board.EPD_RESET`, `board.EPD_BUSY`
- Buttons: `board.BUTTON_A` through `board.BUTTON_D`

### Rotation Transforms (GxEPD2-compatible)
| Rotation | Transform |
|----------|-----------|
| 0° | No change |
| 90° | swap(x,y); x = W-1-x |
| 180° | x = W-1-x; y = H-1-y |
| 270° | swap(x,y); y = H-1-y |

## Serial Monitor

```bash
brew install tio
tio /dev/cu.usbmodem* --log --log-file logs/bench_$(date +%Y%m%d_%H%M%S).log

# Automated benchmark run
tio /dev/cu.usbmodem* --script-file scripts/run_benchmarks.lua \
    --log --log-file logs/bench_$(date +%Y%m%d_%H%M%S).log
```

## Credits

Based on analysis of:
- [GxEPD2](https://github.com/ZinggJM/GxEPD2) by Jean-Marc Zingg — rotation, buffer layout, power patterns
- [Good Display](https://www.good-display.com/product/389.html) — Arduino GDEY029T94 driver
- [Adafruit SSD1680](https://github.com/adafruit/Adafruit_CircuitPython_SSD1680) — CircuitPython reference, sample LUTs
- [adafruit_framebuf](https://github.com/adafruit/Adafruit_CircuitPython_framebuf) — font format, buffer patterns
- [u8g2](https://github.com/olikraus/u8g2) — direct buffer manipulation techniques
- SSD1680 datasheet
