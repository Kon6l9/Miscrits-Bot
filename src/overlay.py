# src/overlay.py
import win32con, win32gui, win32ui, win32api
from ctypes import windll, byref, sizeof, c_void_p, c_uint8, Structure
from ctypes import c_int, c_uint, c_long, POINTER, create_string_buffer, memmove
from ctypes import wintypes
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# ---------------- Win32 helpers ----------------

AC_SRC_ALPHA = 0x01
ULW_ALPHA    = 0x00000002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

class BLENDFUNCTION(Structure):
    _fields_ = [
        ("BlendOp",        c_uint8),
        ("BlendFlags",     c_uint8),
        ("SourceConstantAlpha", c_uint8),
        ("AlphaFormat",    c_uint8),
    ]

# ---------------- Font ----------------

def _font(size=16):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

# ---------------- Overlay ----------------

class Overlay:
    """
    Transparent click-through overlay aligned to a target window's CLIENT area.
    Call update(rects=[(x1,y1,x2,y2,(r,g,b,a))], texts=[(x,y,'msg',(r,g,b,a))])
    """
    def __init__(self, target_hwnd):
        self.target_hwnd = target_hwnd
        self.hwnd = None
        self.memdc = None
        self.hbmp = None
        self.bits_ptr = None   # pointer to DIB section bits
        self.size = (0, 0)
        self._screen_dc = None
        self._create_window()

    # ---------- window creation ----------
    def _create_window(self):
        class_name = "MiscritsOverlayWnd"
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = class_name
        wc.lpfnWndProc = { win32con.WM_DESTROY: self._on_destroy }
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass  # already registered

        exstyle = (win32con.WS_EX_LAYERED |
                   win32con.WS_EX_TRANSPARENT |   # let mouse pass through
                   win32con.WS_EX_TOOLWINDOW |    # hide from Alt-Tab
                   win32con.WS_EX_TOPMOST)

        self.hwnd = win32gui.CreateWindowEx(
            exstyle, class_name, "MiscritsOverlay",
            win32con.WS_POPUP, 0, 0, 0, 0, 0, 0,
            wc.hInstance, None
        )

        # Do NOT set color key/alpha here; per-pixel alpha via UpdateLayeredWindow
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)

        # Keep a screen DC around
        self._screen_dc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        self.destroy()
        return 0

    # ---------- geometry ----------
    def _get_client_rect_screen(self):
        # Client rectangle
        left, top, right, bottom = win32gui.GetClientRect(self.target_hwnd)
        # Convert client (0,0) to screen coordinates
        L, T = win32gui.ClientToScreen(self.target_hwnd, (0, 0))
        W, H = right - left, bottom - top
        return L, T, W, H

    # ---------- surface (32-bit DIB section) ----------
    def _ensure_memdc(self, w, h):
        if self.memdc is not None and self.size == (w, h):
            return

        # cleanup if resizing
        self._free_surface()

        self.size = (w, h)
        # Create a 32-bit top-down DIB section and select into a compatible DC
        self.memdc = win32ui.CreateCompatibleDC(self._screen_dc)

        # Build BITMAPINFO for 32-bit BGRA, top-down
        bmi = win32gui.BITMAPINFO()
        bmi.bmiHeader = win32gui.BITMAPINFOHEADER()
        bmi.bmiHeader.biSize = sizeof(win32gui.BITMAPINFOHEADER())
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # negative => top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = win32con.BI_RGB
        bmi.bmiHeader.biSizeImage = w * h * 4

        # CreateDIBSection gives us an HBITMAP and a pointer to the pixel bits
        bits_ptr = c_void_p()
        hdc = self._screen_dc.GetSafeHdc()
        hbmp = windll.gdi32.CreateDIBSection(
            hdc, byref(bmi), win32con.DIB_RGB_COLORS, byref(bits_ptr), 0, 0
        )
        if not hbmp:
            raise RuntimeError("CreateDIBSection failed")

        self.hbmp = win32ui.CreateBitmapFromHandle(hbmp)
        self.memdc.SelectObject(self.hbmp)
        self.bits_ptr = bits_ptr

    def _free_surface(self):
        try:
            if self.memdc:
                # hBmp will be deleted automatically when DC is deleted,
                # but explicitly delete the handle for safety.
                try:
                    if self.hbmp:
                        win32gui.DeleteObject(self.hbmp.GetHandleAttrib())
                except Exception:
                    pass
                self.memdc.DeleteDC()
        finally:
            self.memdc = None
            self.hbmp = None
            self.bits_ptr = None
            self.size = (0, 0)

    # ---------- drawing / present ----------
    def update(self, rects=None, texts=None):
        rects = rects or []
        texts = texts or []

        L, T, W, H = self._get_client_rect_screen()
        if W <= 0 or H <= 0:
            return

        self._ensure_memdc(W, H)

        # Compose RGBA image (fully transparent background)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        for (x1, y1, x2, y2, color) in rects:
            c = color if color else (0, 255, 0, 200)
            draw.rectangle([x1, y1, x2, y2], outline=c, width=2)

        fnt = _font(16)
        for (x, y, text, color) in texts:
            c = color if color else (0, 255, 0, 200)
            draw.text((x, y), text, fill=c, font=fnt)

        # Convert to BGRA (Windows expects that) and copy into DIB section memory
        bgra = np.asarray(img, dtype=np.uint8)[:, :, [2, 1, 0, 3]]  # RGBA -> BGRA
        memmove(self.bits_ptr, bgra.ctypes.data, bgra.size)

        # Position/size overlay without activating it
        win32gui.SetWindowPos(
            self.hwnd, win32con.HWND_TOPMOST, L, T, W, H,
            SWP_NOACTIVATE | SWP_SHOWWINDOW
        )

        # Alpha blend the DIB section to the layered window
        blend = BLENDFUNCTION()
        blend.BlendOp = 0          # AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = AC_SRC_ALPHA

        # UpdateLayeredWindow expects src POINT=(0,0), dst POINT=(L,T), size=(W,H)
        win32gui.UpdateLayeredWindow(
            self.hwnd, 0, (L, T), (W, H),
            self.memdc.GetSafeHdc(), (0, 0), 0, byref(blend), ULW_ALPHA
        )

    def clear(self):
        self.update([], [])

    def destroy(self):
        try:
            self._free_surface()
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
                self.hwnd = None
        except Exception:
            pass
