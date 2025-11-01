# src/input_ctl.py
import time, random
import ctypes
from ctypes import windll, c_long, c_ulong, c_int, byref, POINTER, Structure
import win32api
import win32con
import win32gui

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import pydirectinput
    HAS_PDI = True
except ImportError:
    HAS_PDI = False


def _jitter(a, b):
    """Random value between a and b"""
    return a + random.random() * (b - a)


# Virtual key codes for common keys
VK_CODES = {
    '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
    '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39, '0': 0x30,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
    'space': win32con.VK_SPACE,
    'enter': win32con.VK_RETURN,
    'esc': win32con.VK_ESCAPE,
    'tab': win32con.VK_TAB,
    'shift': win32con.VK_SHIFT,
    'ctrl': win32con.VK_CONTROL,
    'alt': win32con.VK_MENU,
}


def get_vk_code(key: str) -> int:
    """Get virtual key code for a key string"""
    key = key.lower()
    return VK_CODES.get(key, ord(key.upper()) if len(key) == 1 else 0)


class InputCtl:
    """
    Input controller with multiple backends:
    - DirectInput: Send messages directly to window (non-intrusive, works in background)
    - PyAutoGUI: Standard mouse/keyboard control (requires focus)
    - PyDirectInput: Direct input for games (requires focus)
    """
    
    def __init__(self, cfg):
        self.cfg = cfg
        self.hwnd = None
        self.backend = cfg.get("input", {}).get("backend", "directinput")
        
        # Timing configuration
        self.move_duration_range = cfg.get("input", {}).get("move_duration_range", [0.04, 0.11])
        self.click_delay_range = cfg.get("input", {}).get("click_delay_ms_range", [80, 180])
        self.move_delay_range = cfg.get("input", {}).get("move_delay_ms_range", [60, 140])
        
        if HAS_PYAUTOGUI:
            pyautogui.PAUSE = 0
            pyautogui.FAILSAFE = False
        
        # Log backend selection
        self._log_backend()

    def _log_backend(self):
        """Log which backend is being used"""
        if self.backend == "directinput":
            print("✓ Using DirectInput (non-intrusive, no mouse movement)")
        elif self.backend == "pydirectinput" and HAS_PDI:
            print("✓ Using PyDirectInput (requires focus)")
        elif self.backend == "pyautogui" and HAS_PYAUTOGUI:
            print("✓ Using PyAutoGUI (requires focus, moves cursor)")
        else:
            print("⚠ Warning: Configured backend not available, using fallback")

    def set_window(self, hwnd):
        """Set target window handle for DirectInput"""
        self.hwnd = hwnd
        if self.backend == "directinput":
            print(f"DirectInput bound to HWND={hwnd} - inputs will NOT move your mouse")

    def _sleep_ms(self, ms):
        """Sleep for milliseconds"""
        time.sleep(ms / 1000.0)

    def _random_delay(self, delay_range):
        """Random delay from range"""
        return _jitter(delay_range[0], delay_range[1])

    # ========== CLICKING METHODS ==========

    def click_xy(self, x: int, y: int):
        """
        Click at screen coordinates (x, y)
        DirectInput mode: NO MOUSE MOVEMENT, sends messages to window
        Other modes: Moves actual mouse cursor
        """
        if self.backend == "directinput":
            if not self.hwnd:
                raise RuntimeError("DirectInput requires window handle. Call set_window() first.")
            self._click_directinput(x, y)
        elif self.backend == "pydirectinput" and HAS_PDI:
            self._click_pydirectinput(x, y)
        else:
            self._click_pyautogui(x, y)

    def _click_directinput(self, screen_x: int, screen_y: int):
        """
        Click using Windows messages - COMPLETELY NON-INTRUSIVE
        Your actual mouse cursor WILL NOT MOVE
        """
        if not self.hwnd:
            raise RuntimeError("Window handle not set for DirectInput")

        try:
            # Convert screen coords to client coords
            client_x, client_y = win32gui.ScreenToClient(self.hwnd, (screen_x, screen_y))

            # Create lParam (y in high word, x in low word)
            lParam = win32api.MAKELONG(client_x, client_y)

            # Send mouse messages directly to window
            # WM_MOUSEMOVE - optional, some games need this
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lParam)
            self._sleep_ms(self._random_delay([10, 30]))
            
            # WM_LBUTTONDOWN - press mouse button
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
            self._sleep_ms(self._random_delay([30, 70]))
            
            # WM_LBUTTONUP - release mouse button
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lParam)
            
            # Add configured delay
            self._sleep_ms(self._random_delay(self.click_delay_range))
            
        except Exception as e:
            raise RuntimeError(f"DirectInput click failed: {e}")

    def _click_pydirectinput(self, x: int, y: int):
        """Click using PyDirectInput (requires window focus, MOVES CURSOR)"""
        if not HAS_PDI:
            raise RuntimeError("PyDirectInput not available")
        pydirectinput.moveTo(x, y, duration=self._random_delay(self.move_duration_range) / 1000.0)
        self._sleep_ms(self._random_delay(self.move_delay_range))
        pydirectinput.click()
        self._sleep_ms(self._random_delay(self.click_delay_range))

    def _click_pyautogui(self, x: int, y: int):
        """Click using PyAutoGUI (requires window focus, MOVES CURSOR)"""
        if not HAS_PYAUTOGUI:
            raise RuntimeError("PyAutoGUI not available")
        
        pyautogui.moveTo(x, y, duration=self._random_delay(self.move_duration_range))
        self._sleep_ms(self._random_delay(self.move_delay_range))
        pyautogui.click()
        self._sleep_ms(self._random_delay(self.click_delay_range))

    # ========== KEYBOARD METHODS ==========

    def key(self, key: str):
        """Press a key"""
        if self.backend == "directinput":
            if not self.hwnd:
                raise RuntimeError("DirectInput requires window handle")
            self._key_directinput(key)
        elif self.backend == "pydirectinput" and HAS_PDI:
            pydirectinput.press(key)
            self._sleep_ms(self._random_delay(self.click_delay_range))
        elif HAS_PYAUTOGUI:
            pyautogui.press(key)
            self._sleep_ms(self._random_delay(self.click_delay_range))
        else:
            raise RuntimeError("No keyboard backend available")

    def _key_directinput(self, key: str):
        """
        Send key press using Windows messages (non-intrusive).
        """
        if not self.hwnd:
            raise RuntimeError("Window handle not set for DirectInput")

        vk_code = get_vk_code(key)
        if not vk_code:
            raise ValueError(f"Unknown key: {key}")

        try:
            # Calculate scan code and lParam
            scan_code = win32api.MapVirtualKey(vk_code, 0)
            
            # Key down
            lParam_down = (scan_code << 16) | 1
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk_code, lParam_down)
            self._sleep_ms(self._random_delay([40, 90]))
            
            # Key up
            lParam_up = (scan_code << 16) | 0xC0000001
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk_code, lParam_up)
            self._sleep_ms(self._random_delay(self.click_delay_range))
        except Exception as e:
            raise RuntimeError(f"DirectInput key press failed: {e}")

    def key_combo(self, *keys):
        """Press multiple keys simultaneously (e.g., ctrl+c)"""
        if self.backend == "directinput":
            if not self.hwnd:
                raise RuntimeError("DirectInput requires window handle")
            
            vk_codes = [get_vk_code(k) for k in keys]
            
            # Press all keys
            for vk in vk_codes:
                scan_code = win32api.MapVirtualKey(vk, 0)
                lParam_down = (scan_code << 16) | 1
                win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, lParam_down)
                self._sleep_ms(20)
            
            self._sleep_ms(50)
            
            # Release in reverse order
            for vk in reversed(vk_codes):
                scan_code = win32api.MapVirtualKey(vk, 0)
                lParam_up = (scan_code << 16) | 0xC0000001
                win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, lParam_up)
                self._sleep_ms(20)
            
            self._sleep_ms(self._random_delay(self.click_delay_range))
        elif HAS_PYAUTOGUI:
            pyautogui.hotkey(*keys)
            self._sleep_ms(self._random_delay(self.click_delay_range))
        else:
            raise RuntimeError("Key combo not supported with current backend")

    # ========== MOUSE MOVEMENT (only for non-DirectInput) ==========

    def move_to(self, x: int, y: int):
        """
        Move mouse to position
        DirectInput: Does nothing (no cursor movement needed)
        Other modes: Moves actual cursor
        """
        if self.backend == "directinput":
            # DirectInput doesn't need cursor movement
            return
        elif self.backend == "pydirectinput" and HAS_PDI:
            duration = self._random_delay(self.move_duration_range)
            pydirectinput.moveTo(x, y, duration=duration)
            self._sleep_ms(self._random_delay(self.move_delay_range))
        elif HAS_PYAUTOGUI:
            duration = self._random_delay(self.move_duration_range)
            pyautogui.moveTo(x, y, duration=duration)
            self._sleep_ms(self._random_delay(self.move_delay_range))

    def click(self):
        """Click at current position (only for PyAutoGUI/PyDirectInput)"""
        if self.backend == "directinput":
            raise RuntimeError("DirectInput doesn't support clicking at current position - use click_xy() instead")
        elif self.backend == "pydirectinput" and HAS_PDI:
            pydirectinput.click()
        elif HAS_PYAUTOGUI:
            pyautogui.click()
        else:
            raise RuntimeError("No click backend available")
        
        self._sleep_ms(self._random_delay(self.click_delay_range))

    # ========== DRAG & DROP ==========

    def drag_to(self, x: int, y: int, duration: float = 0.5):
        """Drag to position (only PyAutoGUI)"""
        if self.backend == "directinput":
            raise RuntimeError("DirectInput drag not implemented - use mouse messages manually")
        elif HAS_PYAUTOGUI:
            pyautogui.dragTo(x, y, duration=duration)
            self._sleep_ms(self._random_delay(self.click_delay_range))
        else:
            raise RuntimeError("Drag not supported with current backend")

    # ========== UTILITY ==========

    def wait(self, seconds: float):
        """Wait for specified seconds with small random jitter"""
        actual = seconds + random.uniform(-0.05, 0.05)
        time.sleep(max(0, actual))

    def get_backend_info(self) -> str:
        """Get information about current backend"""
        if self.backend == "directinput":
            status = "✓ ACTIVE" if self.hwnd else "⚠ NOT INITIALIZED"
            return f"DirectInput {status} (hwnd={self.hwnd}) - Non-intrusive, NO cursor movement"
        elif self.backend == "pydirectinput":
            status = "✓ AVAILABLE" if HAS_PDI else "✗ NOT INSTALLED"
            return f"PyDirectInput {status} - Requires focus, moves cursor"
        else:
            status = "✓ AVAILABLE" if HAS_PYAUTOGUI else "✗ NOT INSTALLED"
            return f"PyAutoGUI {status} - Requires focus, moves cursor"


# ========== HELPER FUNCTIONS ==========

def test_input_methods(hwnd=None):
    """Test all available input methods"""
    print("=" * 60)
    print("INPUT METHODS TEST")
    print("=" * 60)
    print(f"PyAutoGUI available: {HAS_PYAUTOGUI}")
    print(f"PyDirectInput available: {HAS_PDI}")
    print()
    
    if hwnd:
        print(f"Testing DirectInput with HWND={hwnd}")
        print("This should NOT move your mouse cursor!")
        print()
        
        try:
            # Test key press
            scan_code = win32api.MapVirtualKey(VK_CODES['a'], 0)
            lParam_down = (scan_code << 16) | 1
            lParam_up = (scan_code << 16) | 0xC0000001
            
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, VK_CODES['a'], lParam_down)
            time.sleep(0.05)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, VK_CODES['a'], lParam_up)
            print("✓ DirectInput key press successful (sent 'a' key)")
        except Exception as e:
            print(f"✗ DirectInput key press failed: {e}")
        
        try:
            # Test click at client coords (100, 100)
            lParam = win32api.MAKELONG(100, 100)
            win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lParam)
            time.sleep(0.02)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lParam)
            time.sleep(0.05)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lParam)
            print("✓ DirectInput click successful at client (100,100)")
            print("  → Your cursor did NOT move!")
        except Exception as e:
            print(f"✗ DirectInput click failed: {e}")
    else:
        print("No HWND provided, skipping DirectInput tests")
        print("To test DirectInput:")
        print("  1. Find your game window")
        print("  2. Run: test_input_methods(hwnd)")
    
    print("=" * 60)