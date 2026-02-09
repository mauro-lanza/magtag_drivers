"""
Canvas Demo - Interactive Feature Showcase
==========================================
Multi-page demo with internal navigation:
  Button A: Previous page
  Button D: Next page
  Button B: Exit to menu
"""

import time
from buttons import Buttons

# =============================================================================
# Navigation Helpers
# =============================================================================

def show_and_wait(canvas, btns, mode="partial"):
    """Update display and wait for navigation button.

    Returns:
        -1 for previous (A), +1 for next (D), 0 for exit (B)
    """
    start = time.monotonic()
    canvas.update(mode=mode)
    print(f"  Refresh ({mode}): {time.monotonic() - start:.2f}s")
    print("  [A]=Prev  [D]=Next  [B]=Exit")

    while True:
        btn = btns.wait([Buttons.A, Buttons.B, Buttons.D])
        if btn == Buttons.A:
            return -1
        elif btn == Buttons.D:
            return +1
        elif btn == Buttons.B:
            return 0


# =============================================================================
# Demo Functions
# =============================================================================

def demo_text_alignment(canvas):
    """Demo 1: Text Alignment"""
    canvas.clear()
    canvas.text("TEXT ALIGNMENT", canvas.width // 2, 2, align="center")
    canvas.hline(0, 16, canvas.width)

    # Left, center, right alignment
    canvas.text("Left aligned", 5, 20)
    canvas.text("Center aligned", canvas.width // 2, 36, align="center")
    canvas.text("Right aligned", canvas.width - 5, 52, align="right")

    # Visual guide - vertical line at center
    canvas.vline(canvas.width // 2, 20, 45)

    # Scale demonstration
    canvas.text("Scale 1", 5, 75)
    canvas.text("Scale 2", 80, 72, scale=2)
    canvas.text("S3", 200, 68, scale=3)


def demo_text_wrapping(canvas):
    """Demo 2: Text Wrapping"""
    canvas.clear()
    canvas.text("TEXT WRAPPING", canvas.width // 2, 2, align="center")
    canvas.hline(0, 16, canvas.width)

    long_text = "The quick brown fox jumps over the lazy dog."

    # Left-aligned wrapped
    canvas.rect(5, 20, 140, 50)
    canvas.text(long_text, 8, 23, max_width=134)

    # Center-aligned wrapped
    canvas.rect(150, 20, 140, 50)
    canvas.text(long_text, 153, 23, max_width=134, align="center")

    # Right-aligned wrapped
    canvas.rect(5, 75, 140, 50)
    canvas.text(long_text, 8, 78, max_width=134, align="right")

    # Labels
    canvas.text("left", 75, 58, align="center")
    canvas.text("center", 220, 58, align="center")
    canvas.text("right", 75, 113, align="center")


def demo_text_box(canvas):
    """Demo 3: Text Box with Vertical Alignment"""
    canvas.clear()
    canvas.text("TEXT BOX ALIGNMENT", canvas.width // 2, 2, align="center")
    canvas.hline(0, 16, canvas.width)

    # 3x3 grid of alignment combinations
    box_w, box_h = 95, 34
    start_x, start_y = 5, 20
    gap = 3

    aligns = ["left", "center", "right"]
    valigns = ["top", "middle", "bottom"]

    for row, valign in enumerate(valigns):
        for col, align in enumerate(aligns):
            bx = start_x + col * (box_w + gap)
            by = start_y + row * (box_h + gap)
            canvas.rect(bx, by, box_w, box_h)
            canvas.text_box(f"{align[0]}/{valign[0]}", bx, by, box_w, box_h,
                           align=align, valign=valign)


def demo_shapes(canvas):
    """Demo 4: Drawing Shapes"""
    canvas.clear()
    canvas.text("SHAPES", canvas.width // 2, 2, align="center")
    canvas.hline(0, 16, canvas.width)

    # Rectangles
    canvas.rect(10, 22, 40, 30)
    canvas.fill_rect(60, 22, 40, 30)
    canvas.text("rect", 10, 56)
    canvas.text("filled", 60, 56)

    # Lines
    canvas.line(120, 22, 170, 52)
    canvas.line(120, 52, 170, 22)
    canvas.text("lines", 130, 56)

    # Circles
    canvas.circle(210, 37, 15)
    canvas.text("circle", 193, 56)

    # H/V lines
    canvas.hline(250, 27, 40)
    canvas.vline(270, 22, 30)
    canvas.text("h/v", 260, 56)

    # Border around entire canvas
    canvas.rect(0, 72, canvas.width, 56)
    canvas.text("Canvas border: rect(0, 72, width, 56)", 10, 90)


def demo_inverted(canvas):
    """Demo 5: Inverted Colors"""
    canvas.clear(black=True)  # Black background

    # White text on black
    canvas.text("WHITE ON BLACK", canvas.width // 2, 5, black=False,
                align="center", scale=2)

    # White shapes
    canvas.rect(20, 38, 100, 40, black=False)
    canvas.fill_rect(20, 38, 100, 40, black=False)
    canvas.text("filled rect", 30, 82, black=False)

    canvas.circle(200, 58, 25, black=False)
    canvas.text("circle", 180, 92, black=False)

    # Mix: black box with white text inside white area
    canvas.fill_rect(250, 38, 40, 40, black=False)
    canvas.text("!", 270, 48, black=True, scale=2, align="center")


def demo_animation(canvas):
    """Demo 6: Animation / Rapid Updates"""
    import time
    for i in range(5):
        canvas.clear()
        canvas.text("ANIMATION", canvas.width // 2, 2, align="center")

        # Moving progress bar
        progress = (i + 1) * 20
        canvas.rect(20, 30, 256, 20)
        canvas.fill_rect(22, 32, int(252 * progress / 100), 16)
        canvas.text(f"{progress}%", canvas.width // 2, 55, align="center")

        # Counter
        canvas.text(f"Frame {i + 1}/5", canvas.width // 2, 80,
                   align="center", scale=2)

        start = time.monotonic()
        canvas.update()
        print(f"  Frame {i + 1}: {time.monotonic() - start:.2f}s")
        time.sleep(0.5)

    # Final state for navigation
    canvas.clear()
    canvas.text("ANIMATION COMPLETE", canvas.width // 2, 30, align="center")
    canvas.text("5 frames @ partial refresh", canvas.width // 2, 50, align="center")
    canvas.text("Press A/D to navigate", canvas.width // 2, 80, align="center")


def demo_wrapped_box(canvas):
    """Demo 7: Wrapped Text in Box"""
    canvas.clear()
    canvas.text("WRAPPED TEXT BOX", canvas.width // 2, 2, align="center")
    canvas.hline(0, 16, canvas.width)

    # Center-aligned, middle
    canvas.rect(10, 20, 135, 105)
    canvas.text_box("This demonstrates wrapped text inside a box horizontally centered and vertically middle-aligned within the box.",
                   15, 20, 125, 105, align="center", valign="middle", wrap=True)

    # Left-aligned, top
    canvas.rect(150, 20, 135, 105)
    canvas.text_box("This demonstrates wrapped text inside a box left-aligned and starts at the top of the box.",
                   155, 20, 125, 105, align="left", valign="top", wrap=True)


# =============================================================================
# Demo Registry - Add/remove demos here
# =============================================================================

DEMOS = [
    ("Text Alignment", demo_text_alignment),
    ("Text Wrapping", demo_text_wrapping),
    ("Text Box", demo_text_box),
    ("Shapes", demo_shapes),
    ("Inverted Colors", demo_inverted),
    ("Animation", demo_animation),
    ("Wrapped Box", demo_wrapped_box),
]


# =============================================================================
# Main Entry Point
# =============================================================================

def run(canvas, btns=None):
    """Run canvas demo with internal page navigation.

    Args:
        canvas: Canvas instance
        btns: Buttons instance (creates one if None)

    Returns when user presses B to exit.
    """
    own_btns = btns is None
    if own_btns:
        btns = Buttons()

    print("\n--- Canvas Demo ---")
    print(f"Canvas: {canvas.width}x{canvas.height}")
    print("Navigation: [A]=Prev [D]=Next [B]=Exit")

    current = 0
    num_demos = len(DEMOS)

    while True:
        name, func = DEMOS[current]
        print(f"\nPage {current + 1}/{num_demos}: {name}")

        # Run the demo function
        func(canvas)

        # Page indicator
        canvas.text(f"{current + 1}/{num_demos}", canvas.width - 5, 5, align="right")

        # Wait for navigation
        direction = show_and_wait(canvas, btns)

        if direction == 0:  # Exit
            print("Exiting canvas demo")
            break

        current = (current + direction) % num_demos

    if own_btns:
        btns.deinit()
