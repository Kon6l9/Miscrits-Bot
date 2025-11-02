# src/capture_loop.py - Fixed with proper spot detection and battle handling
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
            1.0, float(self.cfg.get("search", {}).get("search_delay_ms", 1000)) / 1000.0
        )

        self.overlay: Overlay | None = None
        self.running = False
        self.paused = False
        self.selected_spot = None
        self.window_rect = None
        self.window_xywh = None
        self.hwnd = None
        
        # Initialize stats
        self.stats = {
            "clicks": 0,
            "matches": 0,
            "misses": 0,
            "errors": 0,
            "encounters": 0,
            "captures": 0,
            "skipped": 0,
            "defeated": 0
        }
        
        # Template matching
        self.tpl_path = ""
        self.tpl_bgr = None
        self.tpl_small = None
        self.tpl_w = 0
        self.tpl_h = 0
        self.threshold = 0.82

        # Battle management
        self.battle_enabled = bool(self.cfg.get("battle", {}).get("enabled", False))
        self.battle_manager = None
        
        # Cooldown tracking
        self.cooldown_duration = 24.0
        if not self.cfg.get("traits", {}).get("cooldown_reduction", False):
            self.cooldown_duration = 34.0
        
        if self.battle_enabled:
            from .battle import BattleManager
            self.battle_manager = BattleManager(self.cfg, self.vision, self.io, self.log, self.base_dir)
            self.log.info("⚔️ Battle system enabled")
            self.log.info(f"⏱️ Cooldown: {self.cooldown_duration}s after battles")
        else:
            self.log.info("⚠️ Battle system disabled")

        self._load_selected_spot()
        self._bind_window()

    def _load_selected_spot(self):
        """Load selected spot from config"""
        spots_path = os.path.join(self.base_dir, SPOTS_FILE)
        if not os.path.exists(spots_path):
            raise RuntimeError(f"{SPOTS_FILE} not found. Run --init first.")

        with open(spots_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spots = data.get("spots", [])
        idx = int(self.cfg.get("run", {}).get("selected_spot_index", 0))
        if not (0 <= idx < len(spots)):
            raise RuntimeError("No valid spot selected.")

        self.selected_spot = spots[idx]
        name = self.selected_spot.get("name", "Spot")
        tpl_rel = self.selected_spot.get("template") or ""
        self.threshold = float(self.selected_spot.get("threshold", 0.82))

        self.log.info(f"Selected: '{name}' (threshold={self.threshold:.2f})")

        if not tpl_rel:
            raise RuntimeError(f"Spot '{name}' has no template.")

        self.tpl_path = os.path.join(self.base_dir, tpl_rel)
        if not os.path.exists(self.tpl_path):
            raise RuntimeError(f"Template not found: {self.tpl_path}")

        self.tpl_bgr = cv2.imread(self.tpl_path, cv2.IMREAD_COLOR)
        if self.tpl_bgr is None:
            raise RuntimeError(f"Failed to read template: {self.tpl_path}")

        self.tpl_h, self.tpl_w = self.tpl_bgr.shape[:2]
        self.tpl_small = cv2.resize(self.tpl_bgr, (0, 0), fx=0.5, fy=0.5)
        
        self.log.info(f"Template: {self.tpl_w}x{self.tpl_h}")

    def _bind_window(self):
        """Find and bind to Miscrits window"""
        title_hint = self.cfg.get("window_title_hint", "Miscrits")
        self.hwnd, rect, title = find_window_by_title_substring(title_hint)
        
        if not self.hwnd:
            raise RuntimeError(f"Window '{title_hint}' not found.")

        self.window_rect = get_client_rect_on_screen(self.hwnd)
        self.window_xywh = _rect_to_xywh(self.window_rect)
        L, T, W, H = self.window_xywh
        
        self.log.info(f"Window: '{title}' ({W}x{H})")
        self.io.set_window(self.hwnd)

        try:
            bring_to_foreground(self.hwnd)
            time.sleep(0.3)
        except:
            pass

        if self.show_preview:
            try:
                self.overlay = Overlay(self.hwnd)
                self.log.info("Overlay enabled")
            except Exception as e:
                self.log.warning(f"Overlay failed: {e}")
                self.overlay = None

    def start(self):
        """Start the bot main loop"""
        self.running = True
        self.log.info("=" * 60)
        self.log.info("🤖 Bot started")
        self.log.info(f"🔍 Search interval: {self.search_delay:.1f}s")
        self.log.info(f"🎯 Match threshold: {self.threshold:.2f}")
        self.log.info(f"⚔️ Battle mode: {self.cfg.get('battle', {}).get('mode', 'capture').upper()}")
        self.log.info("=" * 60)
        self._loop()

    def stop(self):
        """Stop the bot"""
        self.running = False
        self.log.info("🛑 Stopping...")

    def pause_toggle(self):
        """Toggle pause state"""
        self.paused = not self.paused
        status = "PAUSED" if self.paused else "RESUMED"
        self.log.info(f"⏸️ {status}")

    def _loop(self):
        """Main bot loop with improved battle and cooldown handling"""
        L, T, W, H = self.window_xywh
        
        consecutive_errors = 0
        max_errors = 5
        
        last_battle_check = 0
        battle_check_interval = 0.5  # Check more frequently
        
        cooldown_end_time = 0
        last_cooldown_log = 0
        
        # Track last click to prevent spam
        last_click_time = 0
        min_click_interval = 2.0

        while self.running:
            try:
                if self.paused:
                    time.sleep(0.5)
                    continue

                if self.overlay:
                    try:
                        self.overlay.update([], [])
                    except:
                        pass

                current_time = time.time()
                
                # Check if in cooldown
                if current_time < cooldown_end_time:
                    remaining = cooldown_end_time - current_time
                    
                    # Log cooldown every 5 seconds
                    if current_time - last_cooldown_log > 5:
                        self.log.info(f"⏳ Cooldown: {remaining:.1f}s remaining")
                        last_cooldown_log = current_time
                    
                    # Update overlay during cooldown
                    if self.overlay:
                        texts = [
                            (10, 10, f"COOLDOWN: {remaining:.0f}s", (255, 255, 0, 220)),
                            (10, 35, f"Battles: {self.stats['encounters']}", (255, 255, 255, 220)),
                            (10, 60, f"Captures: {self.stats['captures']}", (0, 255, 0, 220))
                        ]
                        self.overlay.update([], texts)
                    
                    time.sleep(0.5)
                    continue

                # Battle detection (more frequent checks)
                if self.battle_enabled and current_time - last_battle_check >= battle_check_interval:
                    last_battle_check = current_time
                    
                    if self.battle_manager.check_and_handle_battle():
                        # Battle was handled
                        battle_stats = self.battle_manager.get_statistics()
                        self.stats["encounters"] = battle_stats.get("total_battles", 0)
                        self.stats["captures"] = battle_stats.get("captures_successful", 0)
                        self.stats["skipped"] = battle_stats.get("skipped", 0)
                        self.stats["defeated"] = battle_stats.get("defeated", 0)
                        
                        # Set cooldown
                        cooldown_end_time = current_time + self.cooldown_duration
                        self.log.info(f"⏳ Entering {self.cooldown_duration}s cooldown")
                        last_cooldown_log = current_time
                        continue

                # Spot detection (only if not in cooldown and enough time passed since last click)
                if current_time - last_click_time < min_click_interval:
                    time.sleep(0.2)
                    continue

                # Capture screen
                try:
                    with mss() as sct:
                        frame_bgr = np.array(
                            sct.grab({"left": L, "top": T, "width": W, "height": H})
                        )[:, :, :3]
                except Exception as e:
                    self.log.error(f"Screen capture failed: {e}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        self.log.error("Too many errors, stopping")
                        break
                    time.sleep(1)
                    continue

                consecutive_errors = 0

                # Template matching (multi-scale)
                frame_small = cv2.resize(frame_bgr, (0, 0), fx=0.5, fy=0.5)
                res = cv2.matchTemplate(frame_small, self.tpl_small, cv2.TM_CCOEFF_NORMED)
                _, maxv, _, maxloc = cv2.minMaxLoc(res)

                # Scale coordinates back
                x = int(maxloc[0] * 2)
                y = int(maxloc[1] * 2)
                found = maxv >= self.threshold

                if found:
                    # Calculate center of match
                    cx = x + self.tpl_w // 2
                    cy = y + self.tpl_h // 2
                    
                    # Convert to screen coordinates
                    screen_x = L + cx
                    screen_y = T + cy

                    try:
                        self.io.click_xy(screen_x, screen_y)
                        self.stats["clicks"] += 1
                        self.stats["matches"] += 1
                        last_click_time = current_time
                        
                        self.log.info(f"✓ MATCH [{maxv:.3f}] → clicked ({screen_x},{screen_y})")
                        
                        # Sound alert
                        if self.cfg.get("alerts", {}).get("play_sound", False):
                            try:
                                import winsound
                                winsound.Beep(1000, 200)
                            except:
                                pass
                        
                        # Wait for battle to start
                        if self.battle_enabled:
                            self.log.info("⏳ Waiting for battle...")
                            time.sleep(2.0)
                        
                    except Exception as e:
                        self.log.error(f"Click failed: {e}")
                        self.stats["errors"] += 1

                    # Update overlay
                    if self.overlay:
                        rects = [(x, y, x + self.tpl_w, y + self.tpl_h, (0, 255, 0, 220))]
                        texts = [
                            (x, max(y - 25, 5), f"Match: {maxv:.2f}", (0, 255, 0, 220)),
                            (10, 10, f"Clicks: {self.stats['clicks']}", (255, 255, 255, 220)),
                            (10, 35, f"Battles: {self.stats['encounters']}", (255, 255, 255, 220)),
                            (10, 60, f"Captures: {self.stats['captures']}", (0, 255, 0, 220))
                        ]
                        self.overlay.update(rects, texts)
                else:
                    self.stats["misses"] += 1
                    
                    if self.overlay:
                        texts = [
                            (10, 10, f"Searching... ({maxv:.2f})", (255, 100, 100, 220)),
                            (10, 35, f"Battles: {self.stats['encounters']}", (255, 255, 255, 220)),
                            (10, 60, f"Captures: {self.stats['captures']}", (255, 255, 255, 220))
                        ]
                        self.overlay.update([], texts)

                time.sleep(self.search_delay)

            except KeyboardInterrupt:
                self.log.info("Interrupted")
                break
            except Exception as e:
                self.log.error(f"Unexpected error: {e}", exc_info=True)
                self.stats["errors"] += 1
                time.sleep(2)

        self._cleanup()

    def _cleanup(self):
        """Clean up resources"""
        if self.overlay:
            try:
                self.overlay.destroy()
            except:
                pass

        self.log.info("=" * 60)
        self.log.info("📊 Final Statistics:")
        self.log.info(f"   Spot clicks: {self.stats['clicks']}")
        self.log.info(f"   Matches: {self.stats['matches']}")
        
        if self.battle_enabled and self.battle_manager:
            battle_stats = self.battle_manager.get_statistics()
            self.log.info(f"   Total battles: {battle_stats.get('total_battles', 0)}")
            self.log.info(f"   Captures: {battle_stats.get('captures_successful', 0)}")
            self.log.info(f"   Skipped: {battle_stats.get('skipped', 0)}")
            self.log.info(f"   Defeated: {battle_stats.get('defeated', 0)}")
            
            if battle_stats.get('capture_success_rate', 0) > 0:
                self.log.info(f"   Success rate: {battle_stats['capture_success_rate']:.1f}%")
        
        self.log.info(f"   Errors: {self.stats['errors']}")
        self.log.info("=" * 60)

def setup_hotkeys(bot: Bot, cfg: dict):
    """Setup global hotkeys"""
    try:
        import keyboard
        
        pause_key = cfg.get("hotkeys", {}).get("pause_resume", "f9")
        stop_key = cfg.get("hotkeys", {}).get("stop", "f10")
        
        keyboard.add_hotkey(pause_key, bot.pause_toggle)
        keyboard.add_hotkey(stop_key, bot.stop)
        
        bot.log.info(f"⌨️ Hotkeys: {pause_key}=pause, {stop_key}=stop")
        return True
    except:
        return False