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

print("=== BATTLE TEMPLATE CREATOR ===\n")
print("This will help capture essential battle UI elements\n")

templates = [
    ("flee_button", "Flee icon (running person, bottom left)", 25, 25),
    ("continue_button", "Continue button after victory", 60, 25),
    ("keep_button", "Keep button in capture dialog", 40, 20),
    ("release_button", "Release button in capture dialog", 40, 20),
    ("turn_indicator", "It's your turn! banner", 125, 20),
    ("capture_text", "Capture! text indicator", 50, 15),
    ("victory_banner", "You Win! text", 100, 30),
    ("skill_1_icon", "First skill icon (leftmost)", 35, 35),
    ("abilities_tab", "Abilities tab button", 40, 15),
    ("items_tab", "Items tab button", 40, 15),
]

print("Instructions:")
print("1. Start Miscrits at 1152x648 resolution")
print("2. For each template, hover your mouse over the exact element")
print("3. Press Enter when ready")
print("4. The script will capture after 3 seconds countdown\n")

for name, description, w, h in templates:
    print(f"\n{'='*50}")
    print(f"TEMPLATE: {name}")
    print(f"Description: {description}")
    print(f"Size: {w}x{h} pixels")
    print("="*50)
    
    input(f"\nHover mouse over {description} and press Enter...")
    
    print("Capturing in...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    
    x, y = pyautogui.position()
    
    # Capture region centered on mouse
    left = x - w//2
    top = y - h//2
    right = x + w//2
    bottom = y + h//2
    
    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        filepath = f"assets/templates/battle/{name}.png"
        img.save(filepath)
        print(f"✓ Saved: {filepath}")
    except Exception as e:
        print(f"✗ Failed: {e}")

print("\n" + "="*50)
print("=== TEMPLATE CAPTURE COMPLETE ===")
print("="*50)
print("\nTemplates saved in: assets/templates/battle/")
print("\nNext steps:")
print("1. Review captured templates")
print("2. Re-capture any that look incorrect")
print("3. Start the bot with --ui or --start")