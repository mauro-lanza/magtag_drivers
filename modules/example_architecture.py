"""
Architecture Example - New v2 Library Structure
================================================
This example demonstrates the refactored library architecture.

The new architecture separates concerns into layers:
1. SPIDevice - Low-level SPI communication
2. SSD1680 - Display controller driver
3. DrawBuffer/FrameBuffer - Graphics operations
4. TextRenderer - Font rendering with caching
5. Buttons - Button handling (runtime and deep sleep)
6. Canvas - High-level unified interface
"""

# =============================================================================
# Option 1: Simple Usage (recommended for most users)
# =============================================================================

def simple_example():
    """Most users should use this approach."""
    from canvas import Canvas

    # Canvas auto-creates all dependencies
    canvas = Canvas(rotation=90)

    # Initialize display
    canvas.init(clear=True)

    # Draw some content
    canvas.clear()
    canvas.text("Hello World!", 10, 30)
    canvas.rect(10, 60, 100, 40)
    canvas.fill_circle(200, 80, 30)

    # Update display
    canvas.full_refresh()

    # Done - canvas sleeps display on full_refresh


def button_example():
    """Button handling example."""
    from canvas import Canvas
    from hardware.buttons import Buttons

    canvas = Canvas()
    canvas.init()

    # Runtime button handling
    btns = Buttons()
    canvas.text("Press any button", 10, 30)
    canvas.full_refresh()

    btn = btns.wait()  # Wait for button press
    canvas.clear()
    canvas.text(f"You pressed {btn}", 10, 30)
    canvas.full_refresh()

    # Deep sleep with button wake
    canvas.deep_sleep_until_button([Buttons.A, Buttons.B])
    # Code restarts here after button press


# =============================================================================
# Option 2: With Dependency Injection (for testing or custom setups)
# =============================================================================

def advanced_example():
    """Advanced users can inject their own components."""
    from hardware.spi import SPIDevice
    from drivers.ssd1680 import SSD1680
    from buffer import DrawBuffer
    from text import TextRenderer
    from canvas import Canvas

    # Create components individually (useful for testing with mocks)
    spi = SPIDevice.from_board()
    driver = SSD1680(spi, use_diff_buffer=True)
    buffer = DrawBuffer(driver.WIDTH, driver.HEIGHT, depth=1, rotation=90)
    text = TextRenderer(buffer, cache_size=4096)

    # Inject into Canvas
    canvas = Canvas(
        driver=driver,
        buffer=buffer,
        text_renderer=text,
    )

    canvas.init()
    canvas.text("Custom Setup!", 10, 30)
    canvas.full_refresh()


# =============================================================================
# Option 3: Direct Driver Access (for low-level control)
# =============================================================================

def driver_example():
    """Direct driver access for maximum control."""
    from hardware.spi import SPIDevice
    from drivers.ssd1680 import SSD1680
    from buffer import FrameBuffer

    # Create SPI device
    spi = SPIDevice.from_board()

    # Create driver
    driver = SSD1680(spi)
    driver.init(clear=True)

    # Create buffer and draw
    fb = FrameBuffer(driver.WIDTH, driver.HEIGHT, depth=1, rotation=0)
    fb.clear()

    # Direct pixel manipulation
    for x in range(50):
        for y in range(50):
            fb.pixel(x + 10, y + 10, 0)  # BLACK

    # Display the buffer
    driver.display(fb.to_mono(), full=True)

    # Check diagnostics
    print(f"Driver state: {driver.state}")
    print(f"Partial count: {driver.partial_count}")

    # Clean up
    driver.deinit()


# =============================================================================
# Option 4: State Machine Inspection
# =============================================================================

def state_example():
    """Inspect driver state machine."""
    from drivers.state import DisplayState, DriverState

    # Create state
    state = DriverState()
    print(f"Initial: {state}")

    # Simulate state transitions
    state.on_init_complete()
    print(f"After init: {state}")

    state.on_full_refresh_complete()
    print(f"After full refresh: {state}")

    for i in range(5):
        state.on_partial_refresh_complete()
    print(f"After 5 partials: {state}")

    print(f"Needs full? {state.needs_full_refresh()}")
    print(f"Can partial? {state.can_partial_refresh()}")


# =============================================================================
# Run selected example
# =============================================================================

if __name__ == "__main__":
    # Uncomment the example you want to run:
    # simple_example()
    # button_example()
    # advanced_example()
    # driver_example()
    state_example()  # This one works without hardware
