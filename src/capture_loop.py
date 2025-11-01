# src/capture_loop.py
import os, json, time
import cv2
import numpy as np
from mss import mss

from .vision import Vision
from .input_ctl import InputCtl
from .logger import setup_logger
from .overlay import Overlay
from .window import (
    find_window_by_title_substring,
    get_client_rect_on_screen,
    bring_to_foreground,
)

SPOTS_FILE = "Coords.json"


def _rect_to_xywh(rect):
    # rect is (L, T, R, B) in screen coords
    L, T, R, B = rect
    return L, T, max(0, R - L), max(0, B - T)


class Bot:
    def __init__(self, cfg_path: str, base_dir: str):
        self.base_dir = base_dir
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.log = setup_logger(
            "bot",
            os.path.join(base_dir, self.cfg.get("logging", {}).get("file", "bot.log")),
            self.cfg.get("logging", {}).get("level", "INFO"),
        )

        self.io = InputCtl(self.cfg)
        self.vision = Vision(self.cfg)

        # Initialize these BEFORE any method that reads them
        self.show_preview = bool(self.cfg.get("debug", {}).get("show_preview", False))
        self.search_delay = max(
            1.0, float(self.cfg.get("search", {}).get("search_delay_ms", 10000)) / 1000.0
        )

        self.overlay: Overlay | None = None
        self.running = False
        self.selected_spot = None
        self.window_rect = None        # (L,T,R,B)
        self.window_xywh = None        # (L,T,W,H)
        self.tpl_path = ""
        self.tpl_bgr = None
        self.tpl_small = None
        self.tpl_w = 0
        self.tpl_h = 0

        # Load config pieces
        self._load_selected_spot()
        self._bind_window()

    # ----------------- setup helpers -----------------
    def _load_selected_spot(self):
        """Read selected spot index from config → load its template/threshold."""
        spots_path = os.path.join(self.base_dir, SPOTS_FILE)
        if not os.path.exists(spots_path):
            raise RuntimeError(f"{SPOTS_FILE} not found next to your exe.")

        with open(spots_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spots = data.get("spots", [])
        idx = int(self.cfg.get("run", {}).get("selected_spot_index", 0))
        if not (0 <= idx < len(spots)):
            raise RuntimeError("No valid spot selected. Go to Spots tab and pick one.")

        self.selected_spot = spots[idx]
        name = self.selected_spot.get("name", "Spot")
        tpl_rel = self.selected_spot.get("template") or ""
        thr = float(self.selected_spot.get("threshold", 0.82))

        self.log.info(f"Selected spot '{name}'  template={tpl_rel}  thr={thr:.2f}")

        if not tpl_rel:
            raise RuntimeError("Selected spot has no template. Attach one from clipboard.")

        self.tpl_path = os.path.join(self.base_dir, tpl_rel)
        if not os.path.exists(self.tpl_path):
            raise RuntimeError(f"Template image not found: {self.tpl_path}")

        self.tpl_bgr = cv2.imread(self.tpl_path, cv2.IMREAD_COLOR)
        if self.tpl_bgr is None:
            raise RuntimeError(f"Failed to read template: {self.tpl_path}")

        self.tpl_h, self.tpl_w = self.tpl_bgr.shape[:2]
        # Precompute a 0.5 scale for fast matching, we’ll rescale coords back.
        self.tpl_small = cv2.resize(self.tpl_bgr, (0, 0), fx=0.5, fy=0.5)

    def _bind_window(self):
        """Find Miscrits client window and prepare overlay."""
        title_hint = self.cfg.get("window_title_hint", "Miscrits")
        hwnd, rect, _ = find_window_by_title_substring(title_hint)
        if not hwnd:
            raise RuntimeError("Miscrits window not found. Keep it in windowed/borderless mode.")

        # Client area (exclude title bar) in screen coords
        self.window_rect = get_client_rect_on_screen(hwnd)
        self.window_xywh = _rect_to_xywh(self.window_rect)
        L, T, W, H = self.window_xywh
        self.log.info(f"Bound to Miscrits client: (x={L}, y={T}, w={W}, h={H})")

        try:
            bring_to_foreground(hwnd)
        except Exception:
            pass

        if self.show_preview:
            self.overlay = Overlay(hwnd)

    # ----------------- public API -----------------
    def start(self):
        self.running = True
        self.log.info("Bot started.")
        self._loop()

    def stop(self):
        self.running = False

    # ----------------- main loop -----------------
    def _loop(self):
        L, T, W, H = self.window_xywh
        threshold = float(self.selected_spot.get("threshold", 0.82))
        sct = mss()

        while self.running:
            # Realign overlay each loop (handles window moves)
            if self.overlay:
                try:
                    self.overlay.update([], [])
                except Exception:
                    pass

            # Live capture of the Miscrits client area
            frame_bgr = np.array(
                sct.grab({"left": L, "top": T, "width": W, "height": H})
            )[:, :, :3]

            # Downscale for faster match
            frame_small = cv2.resize(frame_bgr, (0, 0), fx=0.5, fy=0.5)
            res = cv2.matchTemplate(frame_small, self.tpl_small, cv2.TM_CCOEFF_NORMED)
            _, maxv, _, maxloc = cv2.minMaxLoc(res)

            # Scale coords back to client space
            x = int(maxloc[0] * 2)
            y = int(maxloc[1] * 2)
            found = maxv >= threshold

            if found:
                cx = x + self.tpl_w // 2
                cy = y + self.tpl_h // 2
                sx, sy = L + cx, T + cy
                self.io.click_xy(sx, sy)
                self.log.info(f"FOUND score={maxv:.2f}  client=({x},{y})  clicked=({sx},{sy})")

                if self.overlay:
                    rects = [(x, y, x + self.tpl_w, y + self.tpl_h, (0, 255, 0, 220))]
                    texts = [(x, max(y - 20, 0), f"{maxv:.2f}", (0, 255, 0, 220))]
                    self.overlay.update(rects, texts)
            else:
                self.log.info(f"No match score={maxv:.2f} (< {threshold:.2f})")
                if self.overlay:
                    texts = [(10, 10, f"No match ({maxv:.2f})", (255, 64, 64, 220))]
                    self.overlay.update([], texts)

            time.sleep(self.search_delay)

        # Cleanup
        if self.overlay:
            try:
                self.overlay.destroy()
            except Exception:
                pass
        self.log.info("Bot stopped.")
