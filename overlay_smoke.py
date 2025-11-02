import time
import win32gui, win32con, win32api
from ctypes import windll, byref, c_void_p
from src.overlay import Overlay

# make DPI-aware
try:
    user32 = windll.user32
    user32.SetProcessDpiAwarenessContext(c_void_p(-4))
except Exception:
    pass

def find_miscrits_hwnd():
    target = None
    def cb(h, _):
        nonlocal target
        if not win32gui.IsWindowVisible(h):
            return
        title = win32gui.GetWindowText(h)
        if "miscrit" in title.lower():
            target = h
    win32gui.EnumWindows(cb, None)
    return target

def main():
    hwnd = find_miscrits_hwnd()
    if not hwnd:
        win32api.MessageBox(0, "Miscrits window not found.", "Overlay Diag")
        return

    win32api.MessageBox(0, f"Found Miscrits hwnd={hwnd}\nBringing to front...", "Overlay Diag")

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass

    ov = Overlay(hwnd)
    win32api.MessageBox(0, "Overlay created — look for red box!", "Overlay Diag")

    t0 = time.time()
    while time.time() - t0 < 8:
        rects = [(50, 50, 400, 200, (255, 0, 0, 255))]
        texts = [(60, 60, "Overlay test — red rectangle", (255, 255, 255, 255))]
        ov.update(rects, texts)
        time.sleep(0.5)

    ov.destroy()
    win32api.MessageBox(0, "Overlay destroyed.", "Overlay Diag")

if __name__ == "__main__":
    main()
