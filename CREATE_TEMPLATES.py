import os
import sys
import time

try:
    from PIL import ImageGrab
    import pyautogui
except ImportError:
    print("Install required: pip install pillow pyautogui")
    sys.exit(1)

os.makedirs("assets/templates/battle", exist_ok=True)

print("=== TEMPLATE CREATOR ===\n")

# Flee button
print("STEP 1: FLEE BUTTON")
print("1. Start a battle in Miscrits")
print("2. Hover mouse over the flee icon (running person, bottom left)")
input("Press Enter when ready...")

print("Capturing in 3 seconds...")
for i in range(3, 0, -1):
    print(f"{i}...")
    time.sleep(1)

x, y = pyautogui.position()
img = ImageGrab.grab(bbox=(x-25, y-25, x+25, y+25))
img.save("assets/templates/battle/flee_button.png")
print("✓ Saved flee_button.png\n")

# Continue button
print("STEP 2: CONTINUE BUTTON")
print("1. Win a battle to show victory screen")
print("2. Hover mouse over the Continue button")
input("Press Enter when ready...")

print("Capturing in 3 seconds...")
for i in range(3, 0, -1):
    print(f"{i}...")
    time.sleep(1)

x, y = pyautogui.position()
img = ImageGrab.grab(bbox=(x-60, y-25, x+60, y+25))
img.save("assets/templates/battle/continue_button.png")
print("✓ Saved continue_button.png\n")

print("=== DONE ===")
print("Templates created in assets/templates/battle/")