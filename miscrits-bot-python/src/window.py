import ctypes
import os
import win32api
import win32gui
import win32con
import win32process

# ---- DPI awareness (so coordinates match physical pixels) ----
def set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---- Rect helpers ----
def get_client_rect_on_screen(hwnd):
    """Return client area as screen coords: (L, T, R, B)."""
    l, t, r, b = win32gui.GetClientRect(hwnd)             # client coords
    tl = win32gui.ClientToScreen(hwnd, (l, t))            # map to screen
    br = win32gui.ClientToScreen(hwnd, (r, b))
    return (tl[0], tl[1], br[0], br[1])

def rect_to_xywh(rect):
    if not rect:
        return None
    L, T, R, B = rect
    return (L, T, R - L, B - T)

# ---- Window discovery ----
def find_window_by_title_substring(needle: str):
    """
    Match ONLY a window whose title is exactly equal to `needle`
    (case-insensitive). If multiple exist, pick the one with the largest
    client area.
    """
    needle = needle.strip().lower()
    best = {"hwnd": None, "rect": None, "title": None, "area": 0}

    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title.strip().lower() != needle:
            return
        try:
            L, T, R, B = get_client_rect_on_screen(hwnd)
            area = max(0, R - L) * max(0, B - T)
            if area > best["area"]:
                best.update({
                    "hwnd": hwnd,
                    "rect": (L, T, R, B),
                    "title": title,
                    "area": area
                })
        except Exception:
            pass

    win32gui.EnumWindows(enum_cb, None)
    return best["hwnd"], best["rect"], best["title"]

# ---- Foreground focusing (robust) ----
def bring_to_foreground(hwnd):
    """
    Use AttachThreadInput to avoid Windows focus restrictions.
    """
    try:
        fg = win32gui.GetForegroundWindow()
        tid1, _ = win32process.GetWindowThreadProcessId(fg)
        tid2, _ = win32process.GetWindowThreadProcessId(hwnd)
        user32 = ctypes.windll.user32
        user32.AttachThreadInput(tid1, tid2, True)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(tid1, tid2, False)
        return True
    except Exception:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False

# ---- Process & handle utilities ----
def is_window_valid(hwnd) -> bool:
    try:
        return hwnd and win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    except Exception:
        return False

def get_foreground_hwnd():
    try:
        return win32gui.GetForegroundWindow()
    except Exception:
        return None

def get_process_image(hwnd) -> str | None:
    """
    Full path to the owning process image, or None.
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        hproc = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            pid
        )
        try:
            return win32process.GetModuleFileNameEx(hproc, 0)
        finally:
            win32api.CloseHandle(hproc)
    except Exception:
        return None
