# src/capture_loop.py
# Battle detection: Run button + bottom skill tiles (shape-based), optional OCR ("it's your turn" / "items")
import os, json, time
import cv2
import numpy as np
from mss import mss
import ctypes
import easyocr  # pip install easyocr

from .vision import Vision
from .input_ctl import InputCtl
from .logger import setup_logger
from .overlay import Overlay
from .battle_state import BattleDetector, BotState
from .window import (
    find_window_by_title_substring,
    get_client_rect_on_screen,
    bring_to_foreground,
)

SPOTS_FILE = "Coords.json"

def _rect_to_xywh(rect):
    L, T, R, B = rect
    return L, T, max(0, R - L), max(0, B - T)

# ---------------- DPI awareness ----------------
try:
    user32 = ctypes.windll.user32
    SetThreadDpiAwarenessContext = user32.SetThreadDpiAwarenessContext
    SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass


class Bot:
    def __init__(self, cfg_path: str, base_dir: str, ui_mode_cb=None):
        """
        ui_mode_cb: optional callback fired on mode changes.
                    Signature: ui_mode_cb(mode: str, info: dict)
        """
        self.base_dir = base_dir
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

        self.log = setup_logger(
            "bot",
            os.path.join(base_dir, self.cfg.get("logging", {}).get("file", "bot.log")),
            self.cfg.get("logging", {}).get("level", "INFO"),
        )

        self.ui_mode_cb = ui_mode_cb

        self.vision = Vision(self.cfg)
        self.battle_detector = BattleDetector(self.cfg, base_dir)  # for Run button template

        self.show_preview = bool(self.cfg.get("debug", {}).get("show_preview", False))
        self.cooldown_seconds = float(self.cfg.get("search", {}).get("cooldown_seconds", 1))

        self.use_direct_input = bool(self.cfg.get("input", {}).get("use_direct_input", True))
        self.io = None if self.use_direct_input else InputCtl(self.cfg)

        self.overlay: Overlay | None = None
        self.running = False
        self.selected_spot = None
        self.window_rect = None
        self.window_xywh = None
        self.tpl_path = ""
        self.tpl_bgr = None
        self.tpl_small = None
        self.tpl_w = 0
        self.tpl_h = 0

        self.hwnd = None

        self.last_rect = None
        self.last_score = None
        self.last_rect_expire_ts = 0.0

        self._load_selected_spot()
        self._bind_window()

        # ---- EasyOCR init (optional) ----
        self._ocr_warned = False
        self.ocr_reader = None
        try:
            gpu_flag = bool(self.cfg.get("ocr", {}).get("gpu", False))
            self.ocr_reader = easyocr.Reader(['en'], gpu=gpu_flag)
            self.log.info(f"[OCR] EasyOCR initialized (gpu={gpu_flag})")
        except Exception as e:
            self.log.warning(f"[OCR] EasyOCR not available: {e}")

        # ---- Tunables (can override in config) ----
        # Throttling
        self.battle_check_interval_search = float(
            self.cfg.get("battle", {}).get("check_interval_search", 1.0)
        )
        self.battle_check_interval_battle = float(
            self.cfg.get("battle", {}).get("check_interval_battle", 2.0)
        )
        # Skill tiles acceptance
        self.tiles_min_count = int(self.cfg.get("battle", {}).get("tiles_min_count", 3))
        self.tiles_min_coverage = float(self.cfg.get("battle", {}).get("tiles_min_coverage", 0.01))  # 1% ROI
        # OCR participation
        self.require_ocr = bool(self.cfg.get("ocr", {}).get("require_words", False))

        # Cache for battle-readiness info (used by overlays)
        self.br_info = None
        self.last_battle_check_time = 0.0

    # ---------- UI event helper ----------
    def _emit_mode(self, mode: str, info: dict | None = None):
        try:
            if self.ui_mode_cb:
                self.ui_mode_cb(mode, info or {})
        except Exception:
            pass

    # ---------- Setup ----------
    def _load_selected_spot(self):
        spots_path = os.path.join(self.base_dir, SPOTS_FILE)
        if not os.path.exists(spots_path):
            raise RuntimeError(f"{SPOTS_FILE} not found next to your exe.")
        with open(spots_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spots = data.get("spots", [])
        idx = int(self.cfg.get("run", {}).get("selected_spot_index", 0))
        if not (0 <= idx < len(spots)):
            raise RuntimeError("No valid spot selected.")

        self.selected_spot = spots[idx]
        name = self.selected_spot.get("name", "Spot")
        tpl_rel = self.selected_spot.get("template") or ""
        thr = float(self.selected_spot.get("threshold", 0.82))
        self.log.info(f"Selected spot '{name}'  template={tpl_rel}  thr={thr:.2f}")

        if not tpl_rel:
            raise RuntimeError("Selected spot has no template.")

        self.tpl_path = os.path.join(self.base_dir, tpl_rel)
        if not os.path.exists(self.tpl_path):
            raise RuntimeError(f"Template image not found: {self.tpl_path}")

        self.tpl_bgr = cv2.imread(self.tpl_path, cv2.IMREAD_COLOR)
        if self.tpl_bgr is None:
            raise RuntimeError(f"Failed to read template: {self.tpl_path}")

        self.tpl_h, self.tpl_w = self.tpl_bgr.shape[:2]
        self.tpl_small = cv2.resize(self.tpl_bgr, (0, 0), fx=0.5, fy=0.5)

    def _bind_window(self):
        title_hint = self.cfg.get("window_title_hint", "Miscrits")
        hwnd, rect, _ = find_window_by_title_substring(title_hint)
        if not hwnd:
            raise RuntimeError("Miscrits window not found.")
        self.hwnd = hwnd

        self.window_rect = get_client_rect_on_screen(hwnd)
        self.window_xywh = _rect_to_xywh(self.window_rect)
        L, T, W, H = self.window_xywh
        self.log.info(f"Bound to window: (x={L}, y={T}, w={W}, h={H})")
        self.log.info(f"Input method: {'Direct Input' if self.use_direct_input else 'PyAutoGUI'}")

        try:
            bring_to_foreground(hwnd)
        except Exception:
            pass

        if self.show_preview:
            self.overlay = Overlay(hwnd)

    # ---------- Input (direct / pyautogui) ----------
    def _make_lparam(self, x, y):
        return (int(y) << 16) | (int(x) & 0xFFFF)

    def _real_child_from_point(self, parent_hwnd, sx, sy):
        user32 = ctypes.windll.user32
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT(int(sx), int(sy))
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return None

        CWP_SKIPINVISIBLE   = 0x0001
        CWP_SKIPDISABLED    = 0x0002
        CWP_SKIPTRANSPARENT = 0x0004

        pt_client = POINT(pt.x, pt.y)
        user32.ScreenToClient(hwnd, ctypes.byref(pt_client))

        child = user32.ChildWindowFromPointEx(
            hwnd, pt_client,
            CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT
        )
        if child and child != hwnd:
            return child
        return hwnd

    def _send_click_to_hwnd_client(self, hwnd, client_x, client_y):
        user32 = ctypes.windll.user32
        WM_MOUSEMOVE    = 0x0200
        WM_LBUTTONDOWN  = 0x0201
        WM_LBUTTONUP    = 0x0202
        MK_LBUTTON      = 0x0001

        lp = self._make_lparam(client_x, client_y)
        user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.01)
        user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(0.05)
        user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lp)

    def _send_click_at_screen(self, sx, sy):
        user32 = ctypes.windll.user32
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        child = self._real_child_from_point(self.hwnd, sx, sy)
        if not child:
            self.log.warning(f"No child window at ({sx}, {sy})")
            return

        ptc = POINT(int(sx), int(sy))
        user32.ScreenToClient(child, ctypes.byref(ptc))
        self._send_click_to_hwnd_client(child, ptc.x, ptc.y)

    def click_spot(self, client_x, client_y):
        """Click at client coordinates."""
        L, T, _, _ = self.window_xywh
        screen_x = L + client_x
        screen_y = T + client_y

        if self.use_direct_input:
            self._send_click_at_screen(screen_x, screen_y)
            self.log.info(f"[SEARCH] Direct click at client=({client_x},{client_y})")
        else:
            if self.io is None:
                self.log.error("InputCtl not initialized!")
                return
            self.io.click_xy(screen_x, screen_y)
            self.log.info(f"[SEARCH] PyAutoGUI click at client=({client_x},{client_y})")

    # ---------- ROI helpers ----------
    def _skills_roi_rect(self, shape):
        """Bottom bar where skill tiles live. Returns (x0,y0,x1,y1)."""
        H, W = shape[:2]
        y0 = int(H * 0.80)
        y1 = H
        x0 = int(W * 0.05)
        x1 = int(W * 0.95)
        return x0, y0, x1, y1

    # ---------- Enemy HUD ROI + detectors ----------
    def _enemy_hud_roi_rect(self, shape):
        """Covers the enemy HUD (portrait + HP bar) near top-mid-right."""
        H, W = shape[:2]
        x0 = int(W * 0.58)
        y0 = int(H * 0.03)
        x1 = int(W * 0.97)
        y1 = int(H * 0.20)
        return x0, y0, x1, y1

    def _find_square_portrait(self, roi_bgr, roi_origin_xy):
        """
        Try to find the square portrait inside the ROI by contour filtering.
        Returns full-frame rect (x1,y1,x2,y2) or None if not found.
        """
        ox, oy = roi_origin_xy
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
        edges = cv2.Canny(gray, 60, 140)
        edges = cv2.dilate(edges, np.ones((3,3), np.uint8), iterations=1)

        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            if area < 1800 or area > 30000:
                continue
            ar = w / max(1, h)
            if 0.85 <= ar <= 1.15:  # ~square
                if area > best_area:
                    best_area = area
                    best = (ox + x, oy + y, ox + x + w, oy + y + h)
        return best

    def _detect_enemy_portrait_and_hp(self, frame_bgr):
        """
        Returns:
          {
            "portrait_rect": (x1,y1,x2,y2) | None,
            "hp_rect":       (x1,y1,x2,y2) | None
          }
        """
        out = {"portrait_rect": None, "hp_rect": None}

        # --- ROI for enemy HUD ---
        rx0, ry0, rx1, ry1 = self._enemy_hud_roi_rect(frame_bgr.shape)
        roi = frame_bgr[ry0:ry1, rx0:rx1]
        if roi.size == 0:
            return out

        # 1) Portrait (contour-based; with fallback guess)
        portrait_rect = self._find_square_portrait(roi, (rx0, ry0))
        if not portrait_rect:
            H, W = roi.shape[:2]
            size = max(60, int(min(W, H) * 0.45))
            px1 = rx0 + W - size - 10
            py1 = ry0 + 10
            portrait_rect = (px1, py1, px1 + size, py1 + size)
        out["portrait_rect"] = portrait_rect

        # 2) HP bar (HSV green mask → pick widest thin rect)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[...,0], hsv[...,1], hsv[...,2]
        mask = ((h >= 35) & (h <= 95) & (s >= 45) & (v >= 60)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8), iterations=1)
        mask = cv2.dilate(mask, np.ones((3,3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_score = 0.0

        for c in contours:
            x, y, w, h_ = cv2.boundingRect(c)
            area = w * h_
            if area < 700:
                continue
            ar = w / max(1, h_)
            if ar < 3.5:
                continue
            score = w - (h_ * 1.5)
            if score > best_score:
                best_score = score
                best = (rx0 + x, ry0 + y, rx0 + x + w, ry0 + y + h_)

        out["hp_rect"] = best
        return out

    # ---------- Enemy rarity (triangle color) ----------
    def _classify_triangle_color(self, tri_bgr):
        hsv = cv2.cvtColor(tri_bgr, cv2.COLOR_BGR2HSV)
        H = hsv[...,0].astype(np.float32)
        S = hsv[...,1].astype(np.float32)
        V = hsv[...,2].astype(np.float32)

        h_mean = float(np.mean(H))
        s_mean = float(np.mean(S))
        v_mean = float(np.mean(V))

        if s_mean < 40 and v_mean > 80:
            return ("Common", 0.90, (h_mean, s_mean, v_mean))
        if 95 <= h_mean <= 130 and s_mean >= 60:
            return ("Rare", 0.85, (h_mean, s_mean, v_mean))
        if 45 <= h_mean <= 85 and s_mean >= 55:
            return ("Epic", 0.85, (h_mean, s_mean, v_mean))
        if 20 <= h_mean <= 40 and s_mean >= 60:
            return ("Legendary", 0.85, (h_mean, s_mean, v_mean))
        if (145 <= h_mean <= 175 or 0 <= h_mean <= 10) and s_mean >= 50:
            return ("Exotic", 0.80, (h_mean, s_mean, v_mean))

        if s_mean < 45:  return ("Common", 0.55, (h_mean, s_mean, v_mean))
        if h_mean < 20 or h_mean > 150: return ("Exotic", 0.55, (h_mean, s_mean, v_mean))
        if h_mean < 45:  return ("Legendary", 0.55, (h_mean, s_mean, v_mean))
        if h_mean < 95:  return ("Epic", 0.55, (h_mean, s_mean, v_mean))
        return ("Rare", 0.55, (h_mean, s_mean, v_mean))

    def _enemy_portrait_roi_rect(self, shape):
        """(kept for rarity; same region)"""
        return self._enemy_hud_roi_rect(shape)

    def _detect_enemy_rarity(self, frame_bgr):
        x0, y0, x1, y1 = self._enemy_portrait_roi_rect(frame_bgr.shape)
        roi = frame_bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return {"rarity": None, "conf": 0.0, "rect": None}

        rect = self._find_square_portrait(roi, (x0, y0))
        if not rect:
            H, W = roi.shape[:2]
            size = max(60, int(min(W, H) * 0.45))
            rx1 = x0 + W - size - 10
            ry1 = y0 + 10
            rect = (rx1, ry1, rx1 + size, ry1 + size)

        px1, py1, px2, py2 = rect
        portrait = frame_bgr[py1:py2, px1:px2]
        if portrait.size == 0:
            return {"rarity": None, "conf": 0.0, "rect": rect}

        h, w = portrait.shape[:2]
        tri_mask = np.zeros((h, w), dtype=np.uint8)
        tri_pts = np.array([[0, 0], [int(w*0.45), 0], [0, int(h*0.45)]], np.int32)
        cv2.fillConvexPoly(tri_mask, tri_pts, 255)
        tri_bgr = cv2.bitwise_and(portrait, portrait, mask=tri_mask)

        rarity, conf, _ = self._classify_triangle_color(tri_bgr)
        return {"rarity": rarity, "conf": conf, "rect": rect}

    # ---------- Shape-based skill tiles detector ----------
    def _find_skill_tiles(self, frame_bgr):
        x0, y0, x1, y1 = self._skills_roi_rect(frame_bgr.shape)
        roi = frame_bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return 0, [], 0.0

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
        edges = cv2.Canny(gray, 60, 140)
        kernel = np.ones((3,3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rects = []
        total_area = (y1 - y0) * (x1 - x0)
        tiles_area = 0

        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            if area < 800:
                continue
            ar = w / max(1, h)
            if ar < 1.6 or ar > 6.5:
                continue
            cont_area = cv2.contourArea(c)
            fill = cont_area / float(area)
            if fill < 0.5:
                continue

            rects.append((x0 + x, y0 + y, x0 + x + w, y0 + y + h))
            tiles_area += area

        coverage = tiles_area / float(total_area) if total_area else 0.0
        return len(rects), rects, coverage

    # ---------- OCR helper (optional) ----------
    def _ocr_has_battle_text(self, frame_bgr):
        out = {"items": False, "items_conf": 0.0, "turn": False, "turn_conf": 0.0}
        if self.ocr_reader is None:
            if not self._ocr_warned:
                self.log.warning("[OCR] EasyOCR reader not initialized; install easyocr or fix init.")
                self._ocr_warned = True
            return out

        try:
            x0, y0, x1, y1 = self._skills_roi_rect(frame_bgr.shape)
            roi = frame_bgr[y0:y1, x0:x1]
            if roi.size == 0:
                roi = frame_bgr

            up = cv2.resize(roi, (0, 0), fx=1.6, fy=1.6, interpolation=cv2.INTER_LINEAR)
            gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
            gray = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
            thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                        cv2.THRESH_BINARY, 35, 7)

            res = self.ocr_reader.readtext(thr, detail=1)
            tokens = [(t or "").strip().lower() for (_, t, _) in res if (t or "").strip()]

            def fuzzy_has(term, floor=0.72):
                import difflib
                best = 0.0
                for t in tokens:
                    best = max(best, difflib.SequenceMatcher(None, t, term).ratio())
                for i in range(len(tokens) - 2):
                    joined = (tokens[i] + " " + tokens[i+1] + " " + tokens[i+2]).strip()
                    best = max(best, difflib.SequenceMatcher(None, joined, term).ratio())
                for i in range(len(tokens) - 1):
                    j2 = (tokens[i] + " " + tokens[i+1]).strip()
                    best = max(best, difflib.SequenceMatcher(None, j2, term).ratio())
                return best >= floor, best

            items_ok, items_s = fuzzy_has("items", 0.80)
            turn_ok,  turn_s  = fuzzy_has("it's your turn", 0.70)

            out["items"] = items_ok
            out["items_conf"] = float(items_s)
            out["turn"]  = turn_ok
            out["turn_conf"]  = float(turn_s)
        except Exception as e:
            self.log.error(f"[OCR] EasyOCR error: {e}")
        return out

    # ---------- Battle readiness (Run + tiles [+ optional OCR]) ----------
    def _check_battle_ready(self, frame_bgr):
        info = {
            "run": 0.0,
            "tiles_count": 0,
            "tiles_coverage": 0.0,
            "ocr_items": False, "ocr_items_conf": 0.0,
            "ocr_turn": False,  "ocr_turn_conf": 0.0,
            "tile_rects": []
        }

        run_found, run_confidence = self.battle_detector._find_run_button(frame_bgr)
        info["run"] = float(run_confidence or 0.0)

        tiles_count, rects, coverage = self._find_skill_tiles(frame_bgr)
        info["tiles_count"] = tiles_count
        info["tiles_coverage"] = coverage
        info["tile_rects"] = rects

        tiles_ok = (tiles_count >= self.tiles_min_count) and (coverage >= self.tiles_min_coverage)

        ocr_ok = True
        if self.require_ocr:
            o = self._ocr_has_battle_text(frame_bgr)
            info["ocr_items"] = o.get("items", False)
            info["ocr_items_conf"] = o.get("items_conf", 0.0)
            info["ocr_turn"]  = o.get("turn", False)
            info["ocr_turn_conf"]  = o.get("turn", 0.0)
            ocr_ok = (info["ocr_items"] or info["ocr_turn"])

        ready = bool(run_found and tiles_ok and ocr_ok)

        self.log.info(
            f"[BATTLE-CHECK] run={info['run']:.2%} | tiles={tiles_count} "
            f"(cov {info['tiles_coverage']:.2%})"
            + (f" | ocr_items={info['ocr_items']}({info['ocr_items_conf']:.2f})"
               f" ocr_turn={info['ocr_turn']}({info['ocr_turn_conf']:.2f})" if self.require_ocr else "")
            + f" | ready={ready}"
        )
        return ready, info

    # ---------- State actions ----------
    def handle_searching(self, frame_bgr):
        duration = self.battle_detector.get_state_duration()

        if duration < 0.5:
            print("\n" + "="*60)
            print("🔍 SEARCH MODE STARTED 🔍")
            print("="*60 + "\n")
            self.log.info("[SEARCH] Entered search mode")
            self._emit_mode("SEARCH", {})

        threshold = float(self.selected_spot.get("threshold", 0.82))

        frame_small = cv2.resize(frame_bgr, (0, 0), fx=0.5, fy=0.5)
        res = cv2.matchTemplate(frame_small, self.tpl_small, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)

        x = int(maxloc[0] * 2)
        y = int(maxloc[1] * 2)
        found = maxv >= threshold

        if found:
            cx = x + self.tpl_w // 2
            cy = y + self.tpl_h // 2
            self.click_spot(cx, cy)

            self.last_rect = (x, y, x + self.tpl_w, y + self.tpl_h)
            self.last_score = float(maxv)
            self.last_rect_expire_ts = time.time() + 0.8

            self.log.info(f"[SEARCH] ✓ Spot found! score={maxv:.2f}")
        else:
            self.log.debug(f"[SEARCH] Scanning... score={maxv:.2f}")

    def handle_battle(self, frame_bgr):
        duration = self.battle_detector.get_state_duration()
        if duration < 0.5:
            print("\n" + "="*60)
            print("⚔️  BATTLE MODE STARTED ⚔️")
            print("="*60 + "\n")
            self.log.info(f"[BATTLE] ⚔️  Battle detected! Duration: {duration:.2f}s")
            self._emit_mode("BATTLE", self.br_info or {})
        if int(duration) % 5 == 0 and duration > 1:
            self.log.info(f"[BATTLE] Still in battle... ({duration:.1f}s)")
        time.sleep(0.5)

    # ---------- Public API ----------
    def start(self):
        self.running = True
        self.log.info("="*60)
        self.log.info("🤖 Bot started (Run + tiles, optional OCR)")
        self.log.info("="*60)
        self._loop()

    def stop(self):
        self.running = False

    # ---------- Main loop with throttling ----------
    def _loop(self):
        L, T, W, H = self.window_xywh
        sct = mss()

        current_mode = "SEARCH"
        last_spot_check_time = 0.0

        self.log.info("🤖 Starting in SEARCH mode...")
        print("\n" + "="*60)
        print("🔍 SEARCH MODE - Looking for spots...")
        print("="*60 + "\n")
        self._emit_mode("SEARCH", {})

        while self.running:
            try:
                now = time.time()

                frame_bgr = np.array(
                    sct.grab({"left": L, "top": T, "width": W, "height": H})
                )[:, :, :3]

                if current_mode == "SEARCH":
                    if now - last_spot_check_time >= 1.0:
                        last_spot_check_time = now

                        threshold = float(self.selected_spot.get("threshold", 0.82))
                        frame_small = cv2.resize(frame_bgr, (0, 0), fx=0.5, fy=0.5)
                        res = cv2.matchTemplate(frame_small, self.tpl_small, cv2.TM_CCOEFF_NORMED)
                        _, maxv, _, maxloc = cv2.minMaxLoc(res)

                        x = int(maxloc[0] * 2)
                        y = int(maxloc[1] * 2)
                        spot_found = maxv >= threshold

                        if spot_found:
                            cx = x + self.tpl_w // 2
                            cy = y + self.tpl_h // 2
                            self.click_spot(cx, cy)
                            self.last_rect = (x, y, x + self.tpl_w, y + self.tpl_h)
                            self.last_score = float(maxv)
                            self.last_rect_expire_ts = time.time() + 0.8
                            self.br_info = None
                            self.log.info(f"[SEARCH] ✓ Spot found! score={maxv:.2f} - Clicked!")
                        else:
                            if now - self.last_battle_check_time >= self.battle_check_interval_search:
                                self.last_battle_check_time = now
                                battle_ready, br = self._check_battle_ready(frame_bgr)
                                self.br_info = br
                                if battle_ready:
                                    current_mode = "BATTLE"
                                    print("\n" + "="*60)
                                    print("⚔️  BATTLE DETECTED - Switching to BATTLE MODE ⚔️")
                                    print("="*60 + "\n")
                                    self.log.info(
                                        f"[BATTLE] Ready. run={br['run']:.2%} "
                                        f"tiles={br['tiles_count']} cov={br['tiles_coverage']:.2%}"
                                    )
                                    self.battle_detector.force_state(BotState.IN_BATTLE)
                                    # prime rarity + HUD on entry
                                    try:
                                        r = self._detect_enemy_rarity(frame_bgr)
                                        br["enemy_rarity"] = r.get("rarity")
                                        br["enemy_rarity_conf"] = r.get("conf", 0.0)
                                        br["enemy_portrait_rect"] = r.get("rect")
                                        hud = self._detect_enemy_portrait_and_hp(frame_bgr)
                                        br["enemy_hp_rect"] = hud.get("hp_rect")
                                        if hud.get("portrait_rect"):
                                            br["enemy_portrait_rect"] = hud.get("portrait_rect")
                                    except Exception:
                                        pass
                                    self._emit_mode("BATTLE", br)

                    # Overlay (cached br_info)
                    self._update_overlay_search(frame_bgr, self.br_info)

                elif current_mode == "BATTLE":
                    if now - self.last_battle_check_time >= self.battle_check_interval_battle:
                        self.last_battle_check_time = now
                        battle_ready, br = self._check_battle_ready(frame_bgr)
                        self.br_info = br

                        # Enemy rarity + HUD each tick
                        try:
                            r = self._detect_enemy_rarity(frame_bgr)
                            self.br_info["enemy_rarity"] = r.get("rarity")
                            self.br_info["enemy_rarity_conf"] = r.get("conf", 0.0)
                            self.br_info["enemy_portrait_rect"] = r.get("rect")
                            hud = self._detect_enemy_portrait_and_hp(frame_bgr)
                            self.br_info["enemy_hp_rect"] = hud.get("hp_rect")
                            if hud.get("portrait_rect"):
                                self.br_info["enemy_portrait_rect"] = hud.get("portrait_rect")
                        except Exception:
                            pass

                        if battle_ready:
                            run_confidence = br["run"]
                        else:
                            current_mode = "SEARCH"
                            last_spot_check_time = 0.0
                            print("\n" + "="*60)
                            print("🔍 BATTLE ENDED - Switching to SEARCH MODE 🔍")
                            print("="*60 + "\n")
                            self.log.info(
                                f"[SEARCH] Battle UI missing. run={br['run']:.2%} "
                                f"tiles={br['tiles_count']} cov={br['tiles_coverage']:.2%}"
                            )
                            self.battle_detector.force_state(BotState.SEARCHING)
                            # clear cached rarity when leaving battle
                            if self.br_info:
                                self.br_info["enemy_rarity"] = None
                                self.br_info["enemy_rarity_conf"] = 0.0
                                self.br_info["enemy_portrait_rect"] = None
                                self.br_info["enemy_hp_rect"] = None
                            self._emit_mode("SEARCH", br)
                            if self.cooldown_seconds > 0:
                                time.sleep(self.cooldown_seconds)

                    self._execute_battle_logic(frame_bgr)

                    self._update_overlay_battle(
                        frame_bgr,
                        locals().get("run_confidence", 0.0),
                        self.br_info
                    )

                time.sleep(0.1)

            except Exception as e:
                self.log.error(f"Loop error: {e}", exc_info=True)
                time.sleep(0.2)

        if self.overlay:
            try:
                self.overlay.destroy()
            except Exception:
                pass
        self.log.info("🛑 Bot stopped.")

    def _execute_battle_logic(self, frame_bgr):
        """TODO: auto-attack / capture flow / flee, etc."""
        pass

    # ---------- Overlay (shows ROI, tiles, last match) ----------
    def _update_overlay_search(self, frame_bgr, br_info=None):
        if not self.overlay:
            return

        rects, texts = [], []

        # Last template match (green)
        now = time.time()
        if self.last_rect and now <= self.last_rect_expire_ts:
            x1, y1, x2, y2 = self.last_rect
            rects.append((x1, y1, x2, y2, (0, 255, 0, 220)))
            texts.append((x1, max(0, y1 - 18), f"{self.last_score:.2f}", (0, 255, 0, 220)))

        # ROI (cyan) for skills
        x0, y0, x1, y1 = self._skills_roi_rect(frame_bgr.shape)
        rects.append((x0, y0, x1, y1, (0, 255, 255, 120)))

        # Detected tiles (magenta)
        if br_info and br_info.get("tile_rects"):
            for (rx1, ry1, rx2, ry2) in br_info["tile_rects"]:
                rects.append((rx1, ry1, rx2, ry2, (255, 0, 255, 160)))

        texts.append((10, 30, "MODE: SEARCHING 🔍", (0, 255, 0, 255)))
        if br_info:
            texts.append((10, 52, f"Run: {br_info.get('run',0.0):.1f}%  Tiles: {br_info.get('tiles_count',0)}  "
                                   f"Cov: {br_info.get('tiles_coverage',0.0):.2%}", (255,255,255,255)))
            if self.require_ocr:
                texts.append((10, 72, f"Items: {br_info.get('ocr_items',False)} ({br_info.get('ocr_items_conf',0.0):.2f})", (255,255,255,255)))
                texts.append((10, 92, f"Turn : {br_info.get('ocr_turn',False)}  ({br_info.get('ocr_turn_conf',0.0):.2f})", (255,255,255,255)))

        try:
            self.overlay.update(rects, texts)
        except Exception:
            pass

    def _update_overlay_battle(self, frame_bgr, confidence, br_info=None):
        if not self.overlay:
            return

        rects, texts = [], []

        # 1) HUD ROI (cyan) — shows where we look for portrait & HP
        ex0, ey0, ex1, ey1 = self._enemy_hud_roi_rect(frame_bgr.shape)
        rects.append((ex0, ey0, ex1, ey1, (0, 255, 255, 160)))  # cyan frame

        # 2) Portrait + HP bar (green)
        if br_info:
            prect = br_info.get("enemy_portrait_rect")
            hprect = br_info.get("enemy_hp_rect")
            if prect:
                rects.append((prect[0], prect[1], prect[2], prect[3], (0, 255, 0, 230)))
            if hprect:
                rects.append((hprect[0], hprect[1], hprect[2], hprect[3], (0, 255, 0, 230)))

        # 3) Existing info (run/tiles/etc.)
        run = br_info.get("run", 0.0) if br_info else 0.0
        tiles = br_info.get("tiles_count", 0) if br_info else 0
        cov = br_info.get("tiles_coverage", 0.0) if br_info else 0.0
        texts.append((10, 30, f"MODE: BATTLE ⚔️  (run {run:.1f}%)", (255, 255, 255, 255)))
        texts.append((10, 54, f"Tiles: {tiles}  Cov: {cov:.2%}", (255, 255, 255, 255)))

        # 4) Rarity read-out (optional)
        if br_info and br_info.get("enemy_rarity"):
            texts.append((10, 78, f"Enemy: {br_info['enemy_rarity']} ({int(100*br_info.get('enemy_rarity_conf',0))}%)",
                        (255, 255, 0, 255)))

        # 5) Heartbeat
        texts.append((10, 104, "OVERLAY OK", (0, 255, 0, 255)))

        try:
            self.overlay.update(rects, texts)
        except Exception:
            pass
