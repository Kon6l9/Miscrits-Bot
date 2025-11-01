# src/battle.py
import time
import cv2
import numpy as np
from typing import Optional, Tuple, Dict
from .utils import ip_rating_meets_minimum
import re

# IP Rating order from strongest to weakest
IP_RATINGS_ORDER = ["S+", "S", "A+", "A", "B+", "B", "C+", "C", "D+", "D", "F+", "F"]

# Capture rate table at 100% HP (from image)
CAPTURE_RATE_TABLE = {
    # Rating: {Rarity: capture_rate_percent}
    "F-": {"Common": 45, "Rare": 35, "Epic": 25, "Exotic": 15},
    "F": {"Common": 43, "Rare": 33, "Epic": 23, "Exotic": 13},
    "F+": {"Common": 42, "Rare": 32, "Epic": 22, "Exotic": 12},
    "D": {"Common": 40, "Rare": 30, "Epic": 20, "Exotic": 10},
    "D+": {"Common": 39, "Rare": 29, "Epic": 19, "Exotic": 9},
    "C": {"Common": 37, "Rare": 27, "Epic": 17, "Exotic": 7},
    "C+": {"Common": 36, "Rare": 26, "Epic": 16, "Exotic": 6, "Legendary": 95},
    "B": {"Common": 34, "Rare": 24, "Epic": 14, "Exotic": 4, "Legendary": 93},
    "B+": {"Common": 33, "Rare": 23, "Epic": 13, "Exotic": 3, "Legendary": 92},
    "A": {"Common": 31, "Rare": 21, "Epic": 11, "Exotic": 1, "Legendary": 90},
    "A+": {"Common": 30, "Rare": 20, "Epic": 10, "Exotic": 1, "Legendary": 89},
    "S": {"Common": 28, "Rare": 18, "Epic": 8, "Exotic": 1, "Legendary": 87},
    "S+": {"Common": 27, "Rare": 17, "Epic": 7, "Exotic": 1, "Legendary": 86},
}

# Reverse lookup: given capture rate and possible rarities, determine IP rating
def estimate_ip_rating_from_capture_rate(capture_rate: int, possible_rarities=None) -> Tuple[str, str]:
    """
    Estimate IP rating and rarity from capture rate percentage
    
    Args:
        capture_rate: The detected capture rate (e.g., 27, 35, 90)
        possible_rarities: Optional list of rarities to consider
    
    Returns:
        Tuple of (ip_rating, rarity) - best match
    """
    if possible_rarities is None:
        possible_rarities = ["Common", "Rare", "Epic", "Exotic", "Legendary"]
    
    best_match = None
    best_diff = 999
    
    for rating, rarity_rates in CAPTURE_RATE_TABLE.items():
        for rarity, expected_rate in rarity_rates.items():
            if rarity not in possible_rarities:
                continue
            
            diff = abs(expected_rate - capture_rate)
            
            if diff < best_diff:
                best_diff = diff
                best_match = (rating, rarity)
    
    if best_match and best_diff <= 3:  # Within 3% tolerance
        return best_match
    
    return (None, None)


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
        """Check if currently in battle by looking for battle UI elements"""
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
        
        # Method 2: Check for HP bar colors
        hp_roi = self.cfg.get("battle", {}).get("hp_bar_roi", [100, 100, 400, 20])
        if hp_roi and len(hp_roi) == 4:
            x, y, w, h = hp_roi
            if 0 <= x < frame_bgr.shape[1] and 0 <= y < frame_bgr.shape[0]:
                hp_region = frame_bgr[y:y+h, x:x+w]
                if hp_region.size > 0:
                    hsv = cv2.cvtColor(hp_region, cv2.COLOR_BGR2HSV)
                    # Green range for HP
                    green_lower = np.array([40, 50, 50])
                    green_upper = np.array([80, 255, 255])
                    green_mask = cv2.inRange(hsv, green_lower, green_upper)
                    green_ratio = np.count_nonzero(green_mask) / green_mask.size
                    
                    if green_ratio > 0.1:
                        self.log.debug(f"Battle detected via HP bar ({green_ratio:.2%})")
                        return True
        
        return False
    
    def wait_for_battle_start(self, timeout: float = 5.0) -> bool:
        """Wait for battle to start after clicking spot"""
        start_time = time.time()
        check_interval = 0.5
        
        self.log.info("Waiting for battle to start...")
        
        while time.time() - start_time < timeout:
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
        return None


class SkillManager:
    """Manages skill selection and navigation (Skills 1-12)"""
    
    def __init__(self, cfg, io, log):
        self.cfg = cfg
        self.io = io
        self.log = log
        self.current_visible_skills = [1, 2, 3, 4]  # Assume 4 skills visible at once
        
    def use_skill(self, skill_name: str):
        """
        Use a specific skill (e.g., "Skill 1", "Skill 12")
        Navigates skill carousel if needed
        """
        try:
            skill_num = int(skill_name.split()[-1])
        except (ValueError, IndexError):
            self.log.error(f"Invalid skill name: {skill_name}")
            return False
        
        if not (1 <= skill_num <= 12):
            self.log.error(f"Skill number {skill_num} out of range (1-12)")
            return False
        
        self.log.info(f"Using {skill_name} (strength: {'high' if skill_num <= 3 else 'medium' if skill_num <= 8 else 'low'})")
        
        # Navigate to skill if not visible
        if not self._is_skill_visible(skill_num):
            self._navigate_to_skill(skill_num)
        
        # Click the skill
        self._click_skill(skill_num)
        
        # Wait for skill animation
        time.sleep(2.0)
        return True
    
    def _is_skill_visible(self, skill_num: int) -> bool:
        """Check if skill is currently visible on screen"""
        return skill_num in self.current_visible_skills
    
    def _navigate_to_skill(self, skill_num: int):
        """Navigate skill carousel to make target skill visible"""
        # Determine which "page" the skill is on
        # Page 1: Skills 1-4, Page 2: Skills 5-8, Page 3: Skills 9-12
        target_page = ((skill_num - 1) // 4) + 1
        current_page = ((self.current_visible_skills[0] - 1) // 4) + 1
        
        self.log.debug(f"Navigating from page {current_page} to page {target_page}")
        
        if target_page > current_page:
            # Scroll right (toward weaker skills)
            clicks_needed = target_page - current_page
            for _ in range(clicks_needed):
                self.io.key("right")  # Or click right arrow
                time.sleep(0.3)
                self.current_visible_skills = [
                    s + 4 for s in self.current_visible_skills
                ]
        elif target_page < current_page:
            # Scroll left (toward stronger skills)
            clicks_needed = current_page - target_page
            for _ in range(clicks_needed):
                self.io.key("left")  # Or click left arrow
                time.sleep(0.3)
                self.current_visible_skills = [
                    s - 4 for s in self.current_visible_skills
                ]
    
    def _click_skill(self, skill_num: int):
        """Click the skill button"""
        # Find position within visible skills
        if skill_num not in self.current_visible_skills:
            self.log.error(f"Skill {skill_num} not visible, navigation failed")
            return
        
        position = self.current_visible_skills.index(skill_num)
        
        # Press key based on position (1-4)
        key = str(position + 1)
        self.io.key(key)
        self.log.debug(f"Clicked skill position {position + 1} (Skill {skill_num})")


class HPMonitor:
    """Monitor enemy HP percentage"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        self.hp_roi = cfg.get("battle", {}).get("hp_bar_roi", [100, 100, 400, 20])
    
    def get_hp_percent(self) -> Optional[float]:
        """
        Read enemy HP percentage from HP bar
        Returns: HP as percentage (0-100), or None if unreadable
        """
        try:
            x, y, w, h = self.hp_roi
            hp_region = self.vision.screen_grab_region(x, y, w, h)
            
            if hp_region.size == 0:
                return None
            
            # Convert to HSV for color detection
            hsv = cv2.cvtColor(hp_region, cv2.COLOR_RGB2HSV)
            
            # Detect green/yellow/red HP bar
            green_mask = cv2.inRange(hsv, np.array([40, 50, 50]), np.array([80, 255, 255]))
            yellow_mask = cv2.inRange(hsv, np.array([20, 50, 50]), np.array([40, 255, 255]))
            red_mask = cv2.inRange(hsv, np.array([0, 50, 50]), np.array([10, 255, 255]))
            
            # Combine masks
            hp_mask = green_mask | yellow_mask | red_mask
            
            # Calculate filled percentage based on horizontal fill
            if hp_mask.sum() > 0:
                # Find rightmost filled pixel
                cols_sum = hp_mask.sum(axis=0)
                filled_cols = np.where(cols_sum > 0)[0]
                if len(filled_cols) > 0:
                    rightmost = filled_cols[-1]
                    percent = (rightmost / w) * 100
                    return min(100.0, max(0.0, percent))
            
            return None
            
        except Exception as e:
            self.log.error(f"HP reading error: {e}")
            return None


class CaptureRateDetector:
    """Detect capture rate percentage and derive IP rating + rarity"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        # ROI where capture rate percentage is displayed (e.g., "35%", "90%")
        self.capture_rate_roi = cfg.get("battle", {}).get("capture_rate_roi", [500, 300, 100, 40])
        
        # Try to import OCR
        try:
            import pytesseract
            self.has_ocr = True
        except ImportError:
            self.has_ocr = False
            self.log.warning("pytesseract not available - capture rate detection will be limited")
    
    def detect_capture_rate(self) -> Optional[int]:
        """
        Read capture rate percentage from screen
        Returns: Integer percentage (e.g., 35, 90) or None
        """
        try:
            x, y, w, h = self.capture_rate_roi
            rate_region = self.vision.screen_grab_region(x, y, w, h)
            
            if rate_region.size == 0:
                return None
            
            # Convert to grayscale
            gray = cv2.cvtColor(rate_region, cv2.COLOR_RGB2GRAY)
            
            # Apply preprocessing for better OCR
            # Threshold to get white text on black background
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Invert if needed (OCR works better with dark text on light bg)
            if thresh[0, 0] < 128:
                thresh = cv2.bitwise_not(thresh)
            
            if self.has_ocr:
                # Use OCR to read percentage
                import pytesseract
                text = pytesseract.image_to_string(
                    thresh, 
                    config='--psm 7 -c tessedit_char_whitelist=0123456789%'
                ).strip()
                
                # Extract number from text
                match = re.search(r'(\d+)', text)
                if match:
                    rate = int(match.group(1))
                    if 0 <= rate <= 100:
                        self.log.info(f"Detected capture rate: {rate}%")
                        return rate
                    else:
                        self.log.warning(f"Capture rate out of range: {rate}%")
                else:
                    self.log.warning(f"Could not parse capture rate from: '{text}'")
            else:
                # Fallback: Try to estimate from visual patterns
                # This is less reliable but works without OCR
                self.log.warning("OCR not available, using visual estimation")
                return self._estimate_from_visual(thresh)
            
            return None
            
        except Exception as e:
            self.log.error(f"Capture rate detection error: {e}", exc_info=True)
            return None
    
    def _estimate_from_visual(self, thresh) -> Optional[int]:
        """Fallback method: estimate capture rate from visual patterns"""
        # Count white pixels as rough estimate
        # This is very approximate and game-specific
        white_ratio = np.count_nonzero(thresh) / thresh.size
        
        # Very rough estimation (needs calibration per game)
        if white_ratio > 0.7:
            return 90  # High percentage has more digits
        elif white_ratio > 0.5:
            return 35  # Medium
        else:
            return 10  # Low
    
    def get_miscrit_info(self) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        """
        Detect capture rate and derive IP rating + rarity
        Returns: (capture_rate, ip_rating, rarity)
        """
        capture_rate = self.detect_capture_rate()
        
        if capture_rate is None:
            return (None, None, None)
        
        # Estimate IP rating and rarity from capture rate
        ip_rating, rarity = estimate_ip_rating_from_capture_rate(capture_rate)
        
        if ip_rating and rarity:
            self.log.info(f"📊 Capture Rate: {capture_rate}% → {rarity} {ip_rating}")
            return (capture_rate, ip_rating, rarity)
        else:
            self.log.warning(f"Could not determine IP/rarity from capture rate {capture_rate}%")
            return (capture_rate, None, None)


class Battle:
    """Handle battle logic and capture decisions"""
    
    def __init__(self, cfg, vision, input_ctl, log):
        self.cfg = cfg
        self.vision = vision
        self.io = input_ctl
        self.log = log
        
        self.detector = BattleDetector(cfg, vision, log)
        self.skill_mgr = SkillManager(cfg, input_ctl, log)
        self.hp_monitor = HPMonitor(cfg, vision, log)
        self.capture_detector = CaptureRateDetector(cfg, vision, log)

    def is_eligible(self, rarity: str, ip_rating: str) -> bool:
        """Check if Miscrit meets capture criteria"""
        if not rarity:
            self.log.warning("No rarity detected, cannot determine eligibility")
            return False
        
        elig = self.cfg.get("eligibility", {}).get("per_rarity", {})
        rarity_cfg = elig.get(rarity, {})
        
        # Check if rarity is enabled
        if not rarity_cfg.get("enabled", False):
            self.log.info(f"❌ {rarity} is disabled in config")
            return False
        
        # Check IP rating requirement
        min_ip = rarity_cfg.get("min_ip_rating", "A")
        
        if not ip_rating:
            self.log.warning(f"No IP rating detected for {rarity}, rejecting")
            return False
        
        # Handle "B+ and Below" special case
        if min_ip == "B+ and Below":
            if ip_rating not in ["B+", "B", "C+", "C", "D+", "D", "F+", "F", "F-"]:
                self.log.info(f"❌ {rarity} {ip_rating} not in 'B+ and Below' range")
                return False
        else:
            # Normal comparison
            if not ip_rating_meets_minimum(ip_rating, min_ip):
                self.log.info(f"❌ {rarity} {ip_rating} < minimum {min_ip}")
                return False
        
        self.log.info(f"✅ ELIGIBLE: {rarity} {ip_rating} meets criteria (min: {min_ip})")
        return True

    def chip_hp_to_threshold(self, rarity: str):
        """Chip HP down using appropriate skill for this rarity"""
        threshold = self.cfg.get("battle", {}).get("capture_hp_percent", 45)
        max_attempts = 15
        
        # Get rarity-specific damage skill
        rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
        damage_skill = rarity_cfg.get("damage_skill", "Skill 11")
        
        self.log.info(f"Chipping HP to {threshold}% using {damage_skill}...")
        
        for attempt in range(max_attempts):
            hp = self.hp_monitor.get_hp_percent()
            
            if hp is None:
                self.log.warning("Cannot read HP, using skill anyway")
                hp = 100.0
            else:
                self.log.debug(f"Enemy HP: {hp:.1f}%")
            
            if hp <= threshold:
                self.log.info(f"✓ HP threshold reached: {hp:.1f}% <= {threshold}%")
                break
            
            # Use configured damage skill
            self.skill_mgr.use_skill(damage_skill)
            time.sleep(2.5)  # Wait for damage and animation
        else:
            self.log.warning(f"Could not chip HP after {max_attempts} attempts")

    def attempt_capture(self, rarity: str) -> bool:
        """Attempt to capture using rarity-specific capture skill"""
        attempts = self.cfg.get("battle", {}).get("attempts", 3)
        
        # Get rarity-specific capture skill
        rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
        capture_skill = rarity_cfg.get("capture_skill", "Skill 12")
        
        self.log.info(f"Attempting capture with {capture_skill} ({attempts} attempts)")
        
        for attempt in range(1, attempts + 1):
            self.log.info(f"Capture attempt {attempt}/{attempts}")
            
            # Use capture skill (optional, for effects)
            # self.skill_mgr.use_skill(capture_skill)
            # time.sleep(1.0)
            
            # Press capture button (C key or click button)
            self.io.key("c")
            time.sleep(3.0)  # Wait for capture animation
            
            # TODO: Check if capture was successful by detecting success/failure dialog
            # For now, assume failure and continue
        
        self.log.warning("All capture attempts failed")
        return False

    def defeat_miscrit(self):
        """Quickly defeat non-target Miscrit"""
        defeat_skill = self.cfg.get("battle", {}).get("defeat_skill", "Skill 1")
        quick_defeat = self.cfg.get("battle", {}).get("quick_defeat", True)
        
        self.log.info(f"Defeating Miscrit with {defeat_skill}...")
        
        if quick_defeat:
            # Spam strongest skill without checking
            for _ in range(5):
                self.skill_mgr.use_skill(defeat_skill)
                time.sleep(1.5)
        else:
            # Check HP and stop when defeated
            for _ in range(10):
                hp = self.hp_monitor.get_hp_percent()
                if hp is not None and hp <= 0:
                    break
                self.skill_mgr.use_skill(defeat_skill)
                time.sleep(1.5)
        
        # Click through end-battle dialogs
        self._dismiss_dialogs()

    def _dismiss_dialogs(self):
        """Click through post-battle dialogs"""
        self.log.debug("Dismissing dialogs...")
        for _ in range(3):
            self.io.key("enter")
            time.sleep(0.5)

    def handle_encounter(self) -> bool:
        """Main battle handler - returns True if handled successfully"""
        try:
            # Wait for battle to start
            if not self.detector.wait_for_battle_start(timeout=5.0):
                self.log.error("Battle did not start")
                return False
            
            # Wait for UI to stabilize and capture rate to appear
            time.sleep(2.0)
            
            # Detect Miscrit info from capture rate
            capture_rate, ip_rating, rarity = self.capture_detector.get_miscrit_info()
            
            if not rarity or not ip_rating:
                self.log.warning("Could not detect Miscrit info from capture rate")
                # Default to defeat
                self.defeat_miscrit()
                return True
            
            self.log.info(f"═══ Encountered: {rarity} {ip_rating} ({capture_rate}% catch rate) ═══")
            
            # Check eligibility
            if not self.is_eligible(rarity, ip_rating):
                # Not a target - defeat it
                self.defeat_miscrit()
                return True
            
            # Target Miscrit - attempt capture!
            self.log.info(f"🎯 TARGET MISCRIT! {rarity} {ip_rating} - Initiating capture...")
            
            # Chip HP to threshold
            self.chip_hp_to_threshold(rarity)
            
            # Attempt capture
            success = self.attempt_capture(rarity)
            
            if not success:
                # Capture failed - defeat
                self.log.warning("Capture failed, defeating...")
                self.defeat_miscrit()
            else:
                self.log.info("✅ Capture successful!")
            
            return True
            
        except Exception as e:
            self.log.error(f"Error handling encounter: {e}", exc_info=True)
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
                self.battle.log.info(f"═══ Battle #{self.battle_count} Started ═══")
                return self.battle.handle_encounter()
        else:
            # Check if battle ended
            if not self.battle.detector.is_in_battle(frame_bgr):
                self.in_battle = False
                self.battle.log.info("═══ Battle Ended ═══")
        
        return False