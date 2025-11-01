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
    """Convert (L, T, R, B) to (L, T, W, H)"""
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

        # Config variables
        self.show_preview = bool(self.cfg.get("debug", {}).get("show_preview", False))
        self.search_delay = max(
            1.0, float(self.cfg.get("search", {}).get("search_delay_ms", 10000)) / 1000.0
        )

        self.overlay: Overlay | None = None
        self.running = False
        self.paused = False
        self.selected_spot = None
        self.window_rect = None
        self.window_xywh = None
        self.hwnd = None
        
        # Initialize stats dictionary - FIX FOR THE ERROR
        self.stats = {
            "clicks": 0,
            "matches": 0,
            "misses": 0,
            "errors": 0,
            "encounters": 0,
            "captures": 0,
            "skipped": 0
        }
        
        # Template matching variables
        self.tpl_path = ""
        self.tpl_bgr = None
        self.tpl_small = None
        self.tpl_w = 0
        self.tpl_h = 0
        self.threshold = 0.82

        from .battle import BattleManager
        
        # Battle management (optional, based on config)
        self.battle_enabled = bool(self.cfg.get("battle", {}).get("enabled", False))
        self.battle_manager = None
        if self.battle_enabled:
            self.battle_manager = BattleManager(self.cfg, self.vision, self.io, self.log)
            self.log.info("Battle system enabled")

        self._load_selected_spot()
        self._bind_window()

    def _load_selected_spot(self):
        """Load selected spot from config and prepare template"""
        spots_path = os.path.join(self.base_dir, SPOTS_FILE)
        if not os.path.exists(spots_path):
            raise RuntimeError(f"{SPOTS_FILE} not found. Run --init first.")

        with open(spots_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spots = data.get("spots", [])
        idx = int(self.cfg.get("run", {}).get("selected_spot_index", 0))
        if not (0 <= idx < len(spots)):
            raise RuntimeError("No valid spot selected in config.")

        self.selected_spot = spots[idx]
        name = self.selected_spot.get("name", "Spot")
        tpl_rel = self.selected_spot.get("template") or ""
        self.threshold = float(self.selected_spot.get("threshold", 0.82))

        self.log.info(f"Selected spot: '{name}'  threshold={self.threshold:.2f}")

        if not tpl_rel:
            raise RuntimeError(f"Spot '{name}' has no template attached.")

        self.tpl_path = os.path.join(self.base_dir, tpl_rel)
        if not os.path.exists(self.tpl_path):
            raise RuntimeError(f"Template not found: {self.tpl_path}")

        self.tpl_bgr = cv2.imread(self.tpl_path, cv2.IMREAD_COLOR)
        if self.tpl_bgr is None:
            raise RuntimeError(f"Failed to read template: {self.tpl_path}")

        self.tpl_h, self.tpl_w = self.tpl_bgr.shape[:2]
        # Downsample for faster matching (we'll scale coordinates back)
        self.tpl_small = cv2.resize(self.tpl_bgr, (0, 0), fx=0.5, fy=0.5)
        
        self.log.info(f"Template loaded: {self.tpl_w}x{self.tpl_h} pixels")

    def _bind_window(self):
        """Find and bind to Miscrits window"""
        title_hint = self.cfg.get("window_title_hint", "Miscrits")
        self.hwnd, rect, title = find_window_by_title_substring(title_hint)
        
        if not self.hwnd:
            raise RuntimeError(
                f"Window '{title_hint}' not found.\n\n"
                "Make sure Miscrits is running in windowed or borderless mode."
            )

        self.window_rect = get_client_rect_on_screen(self.hwnd)
        self.window_xywh = _rect_to_xywh(self.window_rect)
        L, T, W, H = self.window_xywh
        
        self.log.info(f"Bound to '{title}' (HWND={self.hwnd})")
        self.log.info(f"Client area: x={L}, y={T}, w={W}, h={H}")

        # Initialize input controller with window handle
        self.io.set_window(self.hwnd)

        # Try to focus window
        try:
            bring_to_foreground(self.hwnd)
            time.sleep(0.3)
        except Exception:
            self.log.warning("Could not bring window to foreground automatically")

        # Initialize overlay if preview enabled
        if self.show_preview:
            try:
                self.overlay = Overlay(self.hwnd)
                self.log.info("Overlay initialized")
            except Exception as e:
                self.log.warning(f"Could not create overlay: {e}")
                self.overlay = None

    def start(self):
        """Start the bot main loop"""
        self.running = True
        self.log.info("=" * 60)
        self.log.info("Bot started - Press configured hotkeys to control")
        self.log.info(f"Search interval: {self.search_delay:.1f}s")
        self.log.info(f"Match threshold: {self.threshold:.2f}")
        self.log.info("=" * 60)
        self._loop()

    def stop(self):
        """Stop the bot"""
        self.running = False
        self.log.info("Stop signal received")

    def pause_toggle(self):
        """Toggle pause state"""
        self.paused = not self.paused
        status = "PAUSED" if self.paused else "RESUMED"
        self.log.info(f"Bot {status}")

    def _loop(self):
        """Main bot loop - continuously scan for template and click"""
        L, T, W, H = self.window_xywh
        sct = mss()
        
        consecutive_errors = 0
        max_errors = 5

        while self.running:
            try:
                # Handle pause
                if self.paused:
                    time.sleep(0.5)
                    continue

                # Update overlay position (handles window moves)
                if self.overlay:
                    try:
                        self.overlay.update([], [])
                    except Exception:
                        pass

                # Capture game window
                try:
                    frame_bgr = np.array(
                        sct.grab({"left": L, "top": T, "width": W, "height": H})
                    )[:, :, :3]
                except Exception as e:
                    self.log.error(f"Screen capture failed: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        self.log.error("Too many capture errors, stopping")
                        break
                    time.sleep(1)
                    continue

                consecutive_errors = 0  # Reset on success

                # Downscale for faster matching
                frame_small = cv2.resize(frame_bgr, (0, 0), fx=0.5, fy=0.5)
                
                # Template matching
                res = cv2.matchTemplate(frame_small, self.tpl_small, cv2.TM_CCOEFF_NORMED)
                _, maxv, _, maxloc = cv2.minMaxLoc(res)

                # Scale coordinates back to full resolution
                x = int(maxloc[0] * 2)
                y = int(maxloc[1] * 2)
                found = maxv >= self.threshold

                if found:
                    # Calculate center of matched template
                    cx = x + self.tpl_w // 2
                    cy = y + self.tpl_h // 2
                    
                    # Convert to screen coordinates
                    screen_x = L + cx
                    screen_y = T + cy

                    # Click the spot
                    try:
                        self.io.click_xy(screen_x, screen_y)
                        self.stats["clicks"] += 1
                        self.stats["matches"] += 1
                        
                        self.log.info(
                            f"✓ MATCH [{maxv:.3f}] at client({cx},{cy}) "
                            f"→ clicked screen({screen_x},{screen_y})"
                        )
                    except Exception as e:
                        self.log.error(f"Click failed: {e}")
                        self.stats["errors"] += 1

                    # Update overlay with green box
                    if self.overlay:
                        rects = [(x, y, x + self.tpl_w, y + self.tpl_h, (0, 255, 0, 220))]
                        texts = [
                            (x, max(y - 25, 5), f"Match: {maxv:.2f}", (0, 255, 0, 220)),
                            (10, 10, f"Clicks: {self.stats['clicks']}", (255, 255, 255, 220))
                        ]
                        self.overlay.update(rects, texts)
                else:
                    self.stats["misses"] += 1
                    
                    if self.stats["misses"] % 10 == 0:  # Log every 10 misses
                        self.log.debug(f"No match (best: {maxv:.3f} < {self.threshold:.3f})")

                    # Update overlay with status
                    if self.overlay:
                        texts = [
                            (10, 10, f"Scanning... ({maxv:.2f})", (255, 100, 100, 220)),
                            (10, 35, f"Clicks: {self.stats['clicks']}", (255, 255, 255, 220))
                        ]
                        self.overlay.update([], texts)

                # Wait before next scan
                time.sleep(self.search_delay)

            except KeyboardInterrupt:
                self.log.info("Interrupted by user")
                break
            except Exception as e:
                self.log.error(f"Unexpected error in main loop: {e}")
                self.stats["errors"] += 1
                time.sleep(2)

        # Cleanup
        self._cleanup()

    def _cleanup(self):
        """Clean up resources"""
        if self.overlay:
            try:
                self.overlay.destroy()
                self.log.info("Overlay destroyed")
            except Exception:
                pass

        self.log.info("=" * 60)
        self.log.info("Bot stopped")
        self.log.info(f"Session stats: {self.stats['clicks']} clicks, "
                     f"{self.stats['matches']} matches, "
                     f"{self.stats['misses']} misses, "
                     f"{self.stats['errors']} errors")
        self.log.info("=" * 60)


# Optional: Hotkey handler for pause/stop
def setup_hotkeys(bot: Bot, cfg: dict):
    """Setup global hotkeys for bot control"""
    try:
        import keyboard
        
        pause_key = cfg.get("hotkeys", {}).get("pause_resume", "f9")
        stop_key = cfg.get("hotkeys", {}).get("stop", "f10")
        
        keyboard.add_hotkey(pause_key, bot.pause_toggle)
        keyboard.add_hotkey(stop_key, bot.stop)
        
        bot.log.info(f"Hotkeys registered: {pause_key}=pause/resume, {stop_key}=stop")
        return True
    except Exception as e:
        bot.log.warning(f"Could not setup hotkeys: {e}")
        return False