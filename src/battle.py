# src/battle.py
import time
import cv2
import numpy as np
from typing import Optional, Tuple
from .utils import rank_ge

class BattleDetector:
    """Detect when a battle has started"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        
        # Load battle indicators (templates or color patterns)
        self.battle_templates = self._load_battle_templates()
        
    def _load_battle_templates(self):
        """Load templates that indicate battle state"""
        # You would create templates for:
        # - Battle UI elements (HP bars, skill buttons)
        # - "Battle Started" text
        # - Character portrait areas
        import os
        templates = {}
        template_dir = "assets/templates/battle"
        
        if os.path.exists(template_dir):
            for filename in os.listdir(template_dir):
                if filename.endswith('.png'):
                    name = filename.replace('.png', '')
                    path = os.path.join(template_dir, filename)
                    templates[name] = cv2.imread(path)
                    self.log.info(f"Loaded battle template: {name}")
        
        return templates
    
    def is_in_battle(self, frame_bgr) -> bool:
        """
        Check if currently in battle by looking for battle UI elements
        """
        # Method 1: Template matching for battle UI
        if self.battle_templates:
            for name, template in self.battle_templates.items():
                if template is None:
                    continue
                res = cv2.matchTemplate(frame_bgr, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > 0.8:
                    self.log.debug(f"Battle detected via template: {name} ({max_val:.2f})")
                    return True
        
        # Method 2: Check for specific color patterns
        # Example: HP bars are usually specific colors
        hp_roi = self.cfg.get("battle", {}).get("hp_bar_roi", [100, 100, 400, 20])
        if hp_roi and len(hp_roi) == 4:
            x, y, w, h = hp_roi
            if 0 <= x < frame_bgr.shape[1] and 0 <= y < frame_bgr.shape[0]:
                hp_region = frame_bgr[y:y+h, x:x+w]
                if hp_region.size > 0:
                    # Check for green/red pixels (HP bar colors)
                    hsv = cv2.cvtColor(hp_region, cv2.COLOR_BGR2HSV)
                    # Green range for HP
                    green_lower = np.array([40, 50, 50])
                    green_upper = np.array([80, 255, 255])
                    green_mask = cv2.inRange(hsv, green_lower, green_upper)
                    green_ratio = np.count_nonzero(green_mask) / green_mask.size
                    
                    if green_ratio > 0.1:  # At least 10% green pixels
                        self.log.debug(f"Battle detected via HP bar color ({green_ratio:.2%})")
                        return True
        
        # Method 3: Check if battle-specific ROIs contain expected content
        # This is game-specific and needs to be configured
        
        return False
    
    def wait_for_battle_start(self, timeout: float = 5.0) -> bool:
        """
        Wait for battle to start after clicking spot
        Returns True if battle started, False if timeout
        """
        start_time = time.time()
        check_interval = 0.5
        
        self.log.info("Waiting for battle to start...")
        
        while time.time() - start_time < timeout:
            # Capture current frame
            frame = self._get_game_frame()
            if frame is not None and self.is_in_battle(frame):
                self.log.info("✓ Battle started!")
                return True
            
            time.sleep(check_interval)
        
        self.log.warning("Battle did not start within timeout")
        return False
    
    def _get_game_frame(self):
        """Get current game window frame"""
        # This should use the same capture logic as capture_loop
        # For now, return None - needs integration with main loop
        return None


class Battle:
    """Handle battle logic and capture decisions"""
    
    def __init__(self, cfg, vision, input_ctl, log):
        self.cfg = cfg
        self.vision = vision
        self.io = input_ctl
        self.log = log
        self.detector = BattleDetector(cfg, vision, log)

    def eligible(self, rarity: str, grade: str, name: str) -> bool:
        """Check if Miscrit meets eligibility criteria"""
        elig = self.cfg.get("eligibility", {})
        
        # Check name filter
        names = elig.get("name_filter", [])
        if names and name and name not in names:
            self.log.info(f"Rejected: name '{name}' not in filter list")
            return False
        
        # Check rarity rules
        rules = elig.get("per_rarity", {}).get(rarity or "", None)
        if not rules:
            self.log.info(f"Rejected: no rules for rarity '{rarity}'")
            return False
        
        if not rules.get("enabled", False):
            self.log.info(f"Rejected: rarity '{rarity}' is disabled")
            return False
        
        # Check grade requirement
        min_grade = rules.get("min_grade", "All")
        if min_grade == "All":
            self.log.info(f"Accepted: {rarity} (grade {grade}) - All grades allowed")
            return True
        
        if rank_ge(grade, min_grade):
            self.log.info(f"Accepted: {rarity} grade {grade} >= {min_grade}")
            return True
        else:
            self.log.info(f"Rejected: {rarity} grade {grade} < {min_grade}")
            return False

    def detect_miscrit_info(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Detect rarity, grade, and name of encountered Miscrit
        Returns: (rarity, grade, name)
        """
        # Placeholder - needs implementation with OCR or template matching
        # For now, return None values
        return None, None, None

    def chip_to_threshold(self):
        """Reduce enemy HP to capture threshold using Skill 1"""
        threshold = self.cfg.get("battle", {}).get("capture_hp_percent", 45)
        max_attempts = 10
        
        self.log.info(f"Chipping HP to {threshold}%...")
        
        for attempt in range(max_attempts):
            hp = self.vision.read_hp_percent() or 100.0
            self.log.debug(f"Enemy HP: {hp:.1f}%")
            
            if hp <= threshold:
                self.log.info(f"HP threshold reached: {hp:.1f}% <= {threshold}%")
                break
            
            # Use Skill 1
            self.log.debug("Using Skill 1")
            self.io.key("1")
            time.sleep(2.0)  # Wait for animation
        else:
            self.log.warning(f"Could not chip HP after {max_attempts} attempts")

    def capture_flow(self) -> bool:
        """
        Execute capture sequence
        Returns True if capture successful, False otherwise
        """
        attempts = self.cfg.get("battle", {}).get("attempts", 1)
        capture_mode = self.cfg.get("battle", {}).get("capture_mode", False)
        
        self.log.info(f"Starting capture flow ({attempts} attempts)")
        
        # Use Skill 2 if capture mode enabled
        if capture_mode:
            self.log.info("Capture Mode: Using Skill 2")
            self.io.key("2")
            time.sleep(1.5)
        
        # Attempt captures
        for attempt in range(1, attempts + 1):
            self.log.info(f"Capture attempt {attempt}/{attempts}")
            
            # Press capture key (adjust based on your game)
            self.io.key("c")
            time.sleep(2.5)
            
            # Check if capture was successful
            # This needs game-specific detection
            # For now, assume failure and continue
            
        self.log.warning("All capture attempts failed")
        return False

    def defeat_miscrit(self):
        """Quickly defeat the Miscrit using Skill 1"""
        self.log.info("Defeating Miscrit...")
        
        # Spam Skill 1 until battle ends
        for _ in range(5):
            self.io.key("1")
            time.sleep(1.5)
        
        # Click through any end-battle dialogs
        self._dismiss_dialogs()

    def _dismiss_dialogs(self):
        """Click through post-battle dialogs"""
        self.log.debug("Dismissing dialogs...")
        for _ in range(3):
            self.io.key("enter")
            time.sleep(0.5)

    def handle_encounter(self) -> bool:
        """
        Main battle handler
        Returns True if battle was handled successfully
        """
        try:
            # Wait for battle to start
            if not self.detector.wait_for_battle_start(timeout=5.0):
                self.log.error("Battle did not start")
                return False
            
            # Small delay for battle to fully load
            time.sleep(1.0)
            
            # Detect Miscrit info
            rarity, grade, name = self.detect_miscrit_info()
            
            if rarity:
                self.log.info(f"Encountered: {name or 'Unknown'} - {rarity} {grade or '?'}")
            else:
                self.log.warning("Could not detect Miscrit info")
            
            # Check eligibility
            if rarity and not self.eligible(rarity, grade or "", name or ""):
                # Not eligible - defeat it
                if self.cfg.get("battle", {}).get("auto_defeat", True):
                    self.defeat_miscrit()
                else:
                    self.log.info("Auto-defeat disabled, waiting...")
                return True
            
            # Eligible - try to capture
            self.log.info("Eligible Miscrit! Attempting capture...")
            
            # Chip HP
            self.chip_to_threshold()
            
            # Execute capture
            success = self.capture_flow()
            
            if not success:
                # Capture failed - defeat or flee
                if self.cfg.get("battle", {}).get("auto_defeat", True):
                    self.defeat_miscrit()
                else:
                    self.log.info("Capture failed, fleeing...")
                    self.io.key("f")  # Flee key
                    time.sleep(1.0)
            
            return True
            
        except Exception as e:
            self.log.error(f"Error handling encounter: {e}")
            return False


class BattleManager:
    """Manages battle state and transitions"""
    
    def __init__(self, cfg, vision, input_ctl, log):
        self.battle = Battle(cfg, vision, input_ctl, log)
        self.in_battle = False
        self.battle_count = 0
    
    def check_and_handle_battle(self, frame_bgr) -> bool:
        """
        Check if in battle and handle it
        Returns True if battle was handled
        """
        if not self.in_battle:
            if self.battle.detector.is_in_battle(frame_bgr):
                self.in_battle = True
                self.battle_count += 1
                self.battle.log.info(f"=== Battle #{self.battle_count} ===")
                return self.battle.handle_encounter()
        else:
            # Still in battle or waiting for it to end
            if not self.battle.detector.is_in_battle(frame_bgr):
                self.in_battle = False
                self.battle.log.info("Battle ended")
        
        return False