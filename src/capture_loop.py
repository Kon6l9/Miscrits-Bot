# src/capture_loop.py (Updated with state detection)
import os, json, time
import cv2
import numpy as np
from mss import mss
import ctypes

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
    SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass


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

        self.vision = Vision(self.cfg)
        
        # Initialize battle state detector
        self.battle_detector = BattleDetector(self.cfg, base_dir)

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

    # ----------------- Direct Input Methods -----------------
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
        """Click at client coordinates"""
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

    # ----------------- State-based Actions -----------------
    def handle_searching(self, frame_bgr):
        """Execute searching logic - look for spots and click them"""
        duration = self.battle_detector.get_state_duration()
        
        # Log when we first enter search mode
        if duration < 0.5:
            print("\n" + "="*60)
            print("🔍 SEARCH MODE STARTED 🔍")
            print("="*60 + "\n")
            self.log.info("[SEARCH] Entered search mode")
        
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
            self.last_rect_expire_ts = time.time() + 0.6
            
            self.log.info(f"[SEARCH] ✓ Spot found! score={maxv:.2f}")
        else:
            self.log.debug(f"[SEARCH] Scanning... score={maxv:.2f}")

    def handle_battle(self, frame_bgr):
        """Execute battle logic - this is where auto-battle will go"""
        duration = self.battle_detector.get_state_duration()
        
        if duration < 0.5:  # Only log once when entering battle
            print("\n" + "="*60)
            print("⚔️  BATTLE MODE STARTED ⚔️")
            print("="*60 + "\n")
            self.log.info(f"[BATTLE] ⚔️  Battle detected! Duration: {duration:.2f}s")
        
        # Show we're in battle periodically
        if int(duration) % 5 == 0 and duration > 1:  # Every 5 seconds
            self.log.info(f"[BATTLE] Still in battle... ({duration:.1f}s)")
        
        # TODO: Implement actual battle logic here
        # For now, just wait
        time.sleep(0.5)

    # ----------------- Public API -----------------
    def start(self):
        self.running = True
        self.log.info("="*60)
        self.log.info("🤖 Bot started with STATE DETECTION enabled")
        self.log.info("="*60)
        self._loop()

    def stop(self):
        self.running = False

    # ----------------- Main Loop with State Machine -----------------
    def _loop(self):
        L, T, W, H = self.window_xywh
        sct = mss()

        while self.running:
            try:
                # Capture window
                frame_bgr = np.array(
                    sct.grab({"left": L, "top": T, "width": W, "height": H})
                )[:, :, :3]

                # Detect current state
                state, confidence = self.battle_detector.detect_state(frame_bgr)
                
                # Execute appropriate handler based on state
                if state == BotState.SEARCHING:
                    self.handle_searching(frame_bgr)
                    
                elif state == BotState.IN_BATTLE:
                    self.handle_battle(frame_bgr)
                    
                elif state == BotState.COOLDOWN:
                    self.log.info("[COOLDOWN] Waiting before next search...")
                    time.sleep(self.cooldown_seconds)

                # Update overlay
                self._update_overlay(state, confidence)
                
                # Small delay between iterations
                time.sleep(0.1)

            except Exception as e:
                self.log.error(f"Loop error: {e}", exc_info=True)
                time.sleep(0.2)

        # Cleanup
        if self.overlay:
            try:
                self.overlay.destroy()
            except Exception:
                pass
        self.log.info("🛑 Bot stopped.")

    def _update_overlay(self, state: BotState, confidence: float):
        """Update overlay with current state and any detected elements"""
        if not self.overlay:
            return
            
        rects, texts = [], []
        
        # Show last found spot if in search mode
        now = time.time()
        if state == BotState.SEARCHING and self.last_rect and now <= self.last_rect_expire_ts:
            x1, y1, x2, y2 = self.last_rect
            rects.append((x1, y1, x2, y2, (0, 255, 0, 220)))
            texts.append((x1, max(0, y1 - 18), f"{self.last_score:.2f}", (0, 255, 0, 220)))
        
        # Show state indicator in top-left
        state_colors = {
            BotState.SEARCHING: (0, 255, 0, 255),      # Green
            BotState.IN_BATTLE: (0, 165, 255, 255),    # Orange
            BotState.COOLDOWN: (255, 255, 0, 255),     # Yellow
        }
        color = state_colors.get(state, (255, 255, 255, 255))
        texts.append((10, 30, f"STATE: {state.name} ({confidence:.1%})", color))
        
        try:
            self.overlay.update(rects, texts)
        except Exception:
            pass