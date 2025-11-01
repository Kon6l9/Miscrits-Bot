# src/overlay.py
import win32con, win32gui, win32ui, win32api
from ctypes import windll, byref, sizeof, c_int
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# Simple safe font
def _font(size=16):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

class Overlay:
    """
    Transparent click-through overlay aligned to a target window.
    Draw by calling update(rects=[(x1,y1,x2,y2, (r,g,b,a))], texts=[(x,y,'msg',(r,g,b,a))])
    Coordinates are in the CLIENT area of target window.
    """
    def __init__(self, target_hwnd):
        self.target_hwnd = target_hwnd
        self.hwnd = None
        self.hdc = None
        self.memdc = None
        self.hbmp = None
        self.size = (0, 0)
        self._create_window()

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
                   win32con.WS_EX_TRANSPARENT |
                   win32con.WS_EX_TOOLWINDOW |   # do not show in alt-tab
                   win32con.WS_EX_TOPMOST)

        self.hwnd = win32gui.CreateWindowEx(
            exstyle, class_name, "MiscritsOverlay",
            win32con.WS_POPUP, 0, 0, 0, 0, 0, 0,
            wc.hInstance, None
        )

        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        # Set a color key for full transparency where pixels are (0,0,0)
        win32gui.SetLayeredWindowAttributes(self.hwnd, 0x000000, 255, win32con.LWA_ALPHA)

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        self.destroy()
        return 0

    def _get_client_rect_screen(self):
        # Align overlay to client area (not including title bar/borders)
        left, top, right, bottom = win32gui.GetClientRect(self.target_hwnd)
        # Map client (0,0) to screen
        pt = win32gui.ClientToScreen(self.target_hwnd, (0, 0))
        L, T = pt
        W, H = right - left, bottom - top
        return L, T, W, H

    def _ensure_memdc(self, w, h):
        if self.memdc is not None and self.size == (w, h):
            return
        self.size = (w, h)
        # Clean previous
        if self.memdc:
            win32gui.DeleteObject(self.hbmp)
            win32gui.DeleteDC(self.memdc)
            self.memdc = None

        hdc = win32gui.GetDC(self.hwnd)
        self.memdc = win32ui.CreateCompatibleDC(win32ui.CreateDCFromHandle(hdc))
        self.hbmp = win32ui.CreateBitmap()
        self.hbmp.CreateCompatibleBitmap(win32ui.CreateDCFromHandle(hdc), w, h)
        self.memdc.SelectObject(self.hbmp)
        win32gui.ReleaseDC(self.hwnd, hdc)

    def update(self, rects=None, texts=None):
        """Blit a fresh RGBA buffer with drawings onto the overlay and align it."""
        rects = rects or []
        texts = texts or []

        L, T, W, H = self._get_client_rect_screen()
        if W <= 0 or H <= 0:
            return

        self._ensure_memdc(W, H)

        # Compose an RGBA image (black = fully transparent due to colorkey)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        for (x1, y1, x2, y2, color) in rects:
            c = color if color else (0, 255, 0, 200)
            draw.rectangle([x1, y1, x2, y2], outline=c, width=2)

        fnt = _font(16)
        for (x, y, text, color) in texts:
            c = color if color else (0, 255, 0, 200)
            draw.text((x, y), text, fill=c, font=fnt)

        # Push to layered window via UpdateLayeredWindow
        # Convert PIL image to raw BGRA bytes
        bgra = np.array(img, dtype=np.uint8)
        # PIL gives RGBA; Windows expects BGRA
        bgra = bgra[:, :, [2, 1, 0, 3]]

        self.memdc.SelectObject(self.hbmp)
        win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, L, T, W, H, 0)

        # Copy the raw buffer into HBITMAP
        bmi = win32gui.BITMAPINFO()
        bmi.bmiHeader = win32gui.BITMAPINFOHEADER()
        bmi.bmiHeader.biSize = sizeof(win32gui.BITMAPINFOHEADER())
        bmi.bmiHeader.biWidth = W
        bmi.bmiHeader.biHeight = -H  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = win32con.BI_RGB

        windll.gdi32.SetDIBitsToDevice(
            self.memdc.GetSafeHdc(),             # hdc
            0, 0, W, H,
            0, 0, 0, H,
            bgra.ctypes.data_as(win32api.LPVOID),
            byref(bmi), win32con.DIB_RGB_COLORS
        )

        # Alpha blend onto screen
        ptSrc = (0, 0)
        ptDst = (L, T)
        sz = (W, H)
        blend = win32gui.BLENDFUNCTION()
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = win32con.AC_SRC_ALPHA

        win32gui.UpdateLayeredWindow(
            self.hwnd, 0, ptDst, sz, self.memdc.GetSafeHdc(),
            ptSrc, 0, blend, win32con.ULW_ALPHA
        )

    def clear(self):
        self.update([], [])

    def destroy(self):
        try:
            if self.memdc:
                win32gui.DeleteObject(self.hbmp)
                win32gui.DeleteDC(self.memdc)
                self.memdc = None
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd)
                self.hwnd = None
        except Exception:
            pass
