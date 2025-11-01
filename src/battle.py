# src/battle.py - Complete Auto-Battle & Auto-Capture System
import time
import cv2
import numpy as np
import re
from typing import Optional, Tuple, Dict, List
from .utils import ip_rating_meets_minimum

# ============================================================================
# CONSTANTS & DATA TABLES
# ============================================================================

# IP Rating order from strongest to weakest
IP_RATINGS_ORDER = ["S+", "S", "A+", "A", "B+", "B", "C+", "C", "D+", "D", "F+", "F", "F-"]

# Capture rate table at 100% HP (from image 3)
CAPTURE_RATE_TABLE_100HP = {
    "F-": {"Common": 45, "Rare": 35, "Epic": 25, "Exotic": 15, "Legendary": 100},
    "F": {"Common": 43, "Rare": 33, "Epic": 23, "Exotic": 13, "Legendary": 100},
    "F+": {"Common": 42, "Rare": 32, "Epic": 22, "Exotic": 12, "Legendary": 100},
    "D": {"Common": 40, "Rare": 30, "Epic": 20, "Exotic": 10, "Legendary": 100},
    "D+": {"Common": 39, "Rare": 29, "Epic": 19, "Exotic": 9, "Legendary": 100},
    "C": {"Common": 37, "Rare": 27, "Epic": 17, "Exotic": 7, "Legendary": 100},
    "C+": {"Common": 36, "Rare": 26, "Epic": 16, "Exotic": 6, "Legendary": 95},
    "B": {"Common": 34, "Rare": 24, "Epic": 14, "Exotic": 4, "Legendary": 93},
    "B+": {"Common": 33, "Rare": 23, "Epic": 13, "Exotic": 3, "Legendary": 92},
    "A": {"Common": 31, "Rare": 21, "Epic": 11, "Exotic": 1, "Legendary": 90},
    "A+": {"Common": 30, "Rare": 20, "Epic": 10, "Exotic": 1, "Legendary": 89},
    "S": {"Common": 28, "Rare": 18, "Epic": 8, "Exotic": 1, "Legendary": 87},
    "S+": {"Common": 27, "Rare": 17, "Epic": 7, "Exotic": 1, "Legendary": 86},
}

# Capture rate table at 1% HP (from image 3)
CAPTURE_RATE_TABLE_1HP = {
    "C+": {"Legendary": 95},
    "B": {"Legendary": 93},
    "B+": {"Legendary": 92},
    "A": {"Legendary": 90},
    "A+": {"Exotic": 99, "Legendary": 89},
    "S": {"Exotic": 97, "Legendary": 87},
    "S+": {"Exotic": 96, "Legendary": 86},
}

# ============================================================================
# ROI DEFINITIONS (Based on 1152x648 game window - ACTUAL SCREENSHOTS)
# ============================================================================

# All coordinates relative to game client area (0,0 = top-left of game window)
# CALIBRATED FROM REAL GAME SCREENSHOTS PROVIDED BY USER
DEFAULT_ROIS = {
    # Capture percentage (top center) - "31%" visible in screenshot
    "capture_rate": {
        "x": 560,
        "y": 235,
        "w": 80,
        "h": 40,
        "description": "Capture percentage display above 'Capture!' text"
    },
    
    # Enemy HP bar (top right) - thin green bar below "Kopper"
    "enemy_hp_bar": {
        "x": 755,
        "y": 205,
        "w": 70,
        "h": 8,
        "description": "Enemy HP bar - thin green/yellow/red fill"
    },
    
    # Enemy HP text
    "enemy_hp_text": {
        "x": 750,
        "y": 210,
        "w": 80,
        "h": 20,
        "description": "Enemy HP text (e.g., '127/127')"
    },
    
    # Player HP bar (top left) - below "Chamille Machla"
    "player_hp_bar": {
        "x": 390,
        "y": 205,
        "w": 85,
        "h": 8,
        "description": "Player HP bar - thin green/yellow/red fill"
    },
    
    # Turn indicator - "It's your turn!" banner
    "turn_indicator": {
        "x": 450,
        "y": 580,
        "w": 250,
        "h": 30,
        "description": "Turn indicator banner above skills"
    },
    
    # Skills bar (bottom) - "Abilities" tab with 4 visible skills
    "skills_bar": {
        "x": 340,
        "y": 600,
        "w": 540,
        "h": 70,
        "description": "Skills bar area with visible abilities"
    },
    
    # Abilities/Items tabs
    "abilities_tab": {
        "x": 380,
        "y": 585,
        "w": 80,
        "h": 25,
        "description": "Abilities tab button"
    },
    
    "items_tab": {
        "x": 470,
        "y": 585,
        "w": 80,
        "h": 25,
        "description": "Items tab button"
    },
    
    # Individual skill slots (centers for clicking)
    # From screenshot: FOIL LIGHTNING BARB, KILOBLITZ, HYPER-POWER, VOLTAGE
    "skill_slot_1": {"x": 405, "y": 628, "description": "First visible skill (leftmost)"},
    "skill_slot_2": {"x": 488, "y": 628, "description": "Second skill"},
    "skill_slot_3": {"x": 655, "y": 628, "description": "Third skill"},
    "skill_slot_4": {"x": 738, "y": 628, "description": "Fourth skill (rightmost visible)"},
    
    # Skill navigation arrows
    "skill_arrow_left": {"x": 330, "y": 628, "description": "Left arrow - scroll to previous skills"},
    "skill_arrow_right": {"x": 865, "y": 628, "description": "Right arrow - scroll to next skills"},
    
    # Battle end screens
    "continue_button": {
        "x": 576,
        "y": 580,
        "w": 100,
        "h": 40,
        "description": "Continue button after battle"
    },
    
    "victory_text": {
        "x": 400,
        "y": 200,
        "w": 350,
        "h": 80,
        "description": "Victory/defeat message area"
    },
    
    # Additional helpful ROIs
    "capture_text": {
        "x": 530,
        "y": 230,
        "w": 100,
        "h": 30,
        "description": "'Capture!' text indicator"
    },
    
    "battle_circles": {
        "x": 350,
        "y": 250,
        "w": 180,
        "h": 40,
        "description": "Four circles indicator (battle status)"
    },
}


def estimate_ip_rating_from_capture_rate(capture_rate: int, possible_rarities=None) -> Tuple[Optional[str], Optional[str]]:
    """
    Estimate IP rating and rarity from capture rate percentage at battle start (100% HP)
    
    Args:
        capture_rate: The detected capture rate (e.g., 27, 35, 90)
        possible_rarities: Optional list of rarities to consider
    
    Returns:
        Tuple of (ip_rating, rarity) - best match or (None, None)
    """
    if possible_rarities is None:
        possible_rarities = ["Common", "Rare", "Epic", "Exotic", "Legendary"]
    
    best_match = None
    best_diff = 999
    
    for rating, rarity_rates in CAPTURE_RATE_TABLE_100HP.items():
        for rarity, expected_rate in rarity_rates.items():
            if rarity not in possible_rarities:
                continue
            
            diff = abs(expected_rate - capture_rate)
            
            if diff < best_diff:
                best_diff = diff
                best_match = (rating, rarity)
    
    # Accept match if within 3% tolerance
    if best_match and best_diff <= 3:
        return best_match
    
    return (None, None)


# ============================================================================
# BATTLE DETECTION
# ============================================================================

class BattleDetector:
    """Detect when a battle has started and ended using flee and continue button icons"""
    
    def __init__(self, cfg, vision, log, base_dir):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        self.base_dir = base_dir
        self.rois = DEFAULT_ROIS
        self.flee_template = None
        self.continue_template = None
        self._load_templates()
    
    def _load_templates(self):
        import os
        flee_path = os.path.join(self.base_dir, "assets", "templates", "battle", "flee_button.png")
        if os.path.exists(flee_path):
            self.flee_template = cv2.imread(flee_path, cv2.IMREAD_COLOR)
            self.log.debug("Loaded flee template")
        
        continue_path = os.path.join(self.base_dir, "assets", "templates", "battle", "continue_button.png")
        if os.path.exists(continue_path):
            self.continue_template = cv2.imread(continue_path, cv2.IMREAD_COLOR)
            self.log.debug("Loaded continue template")
    
    def is_in_battle(self) -> bool:
        """Check if currently in battle by detecting flee button or turn indicator"""
        # First try template matching if available
        if self.flee_template is not None:
            found, _, _, _ = self._match_template(self.flee_template, 0.7)
            if found:
                return True
        
        # Fallback: check turn indicator using color detection
        try:
            from mss import mss
            
            roi = self.rois["turn_indicator"]
            
            with mss() as sct:
                monitor = {
                    "left": roi["x"],
                    "top": roi["y"],
                    "width": roi["w"],
                    "height": roi["h"]
                }
                grab = sct.grab(monitor)
                frame = np.array(grab)[:, :, :3]  # Get RGB
            
            if frame.size == 0:
                return False
            
            # Convert to HSV for better detection
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
            
            # Look for blue banner color (turn indicator is blue)
            blue_lower = np.array([100, 50, 50])
            blue_upper = np.array([130, 255, 255])
            blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)
            
            blue_ratio = np.count_nonzero(blue_mask) / blue_mask.size
            
            # If significant blue detected, we're in battle
            return blue_ratio > 0.15
            
        except Exception as e:
            self.log.error(f"Battle detection error: {e}")
            return False
    
    def is_battle_ended(self) -> bool:
        """Check if battle has ended using continue button or victory screen"""
        # First try template matching if available
        if self.continue_template is not None:
            found, _, _, _ = self._match_template(self.continue_template, 0.7)
            if found:
                return True
        
        # Fallback: check victory text area
        try:
            from mss import mss
            
            roi = self.rois["victory_text"]
            
            with mss() as sct:
                monitor = {
                    "left": roi["x"],
                    "top": roi["y"],
                    "width": roi["w"],
                    "height": roi["h"]
                }
                grab = sct.grab(monitor)
                frame = np.array(grab)[:, :, :3]  # Get RGB
            
            if frame.size == 0:
                return False
            
            # Look for "You Win!" or victory screen indicators
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
            
            # Green victory banner
            green_lower = np.array([40, 50, 50])
            green_upper = np.array([80, 255, 255])
            green_mask = cv2.inRange(hsv, green_lower, green_upper)
            
            green_ratio = np.count_nonzero(green_mask) / green_mask.size
            
            return green_ratio > 0.1
            
        except Exception as e:
            self.log.error(f"Battle end detection error: {e}")
            return False
    
    def _match_template(self, template, threshold):
        """Match template on full screen"""
        try:
            from mss import mss
            with mss() as sct:
                monitor = sct.monitors[1]
                grab = sct.grab(monitor)
                screen = np.array(grab)[:, :, :3]
            
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val >= threshold:
                return True, max_loc[0], max_loc[1], max_val
            return False, 0, 0, max_val
        except:
            return False, 0, 0, 0.0
    
    def wait_for_battle_start(self, timeout: float = 8.0) -> bool:
        """Wait for battle to start after clicking spot"""
        start_time = time.time()
        check_interval = 0.3
        
        self.log.info("⏳ Waiting for battle to start...")
        
        while time.time() - start_time < timeout:
            if self.is_in_battle():
                self.log.info("✓ Battle started!")
                return True
            time.sleep(check_interval)
        
        self.log.warning("⚠ Battle did not start within timeout")
        return False
    
    def wait_for_battle_end(self, timeout: float = 30.0) -> bool:
        """Wait for battle to end"""
        start_time = time.time()
        check_interval = 0.5
        
        while time.time() - start_time < timeout:
            if self.is_battle_ended():
                self.log.info("✓ Battle ended!")
                return True
            time.sleep(check_interval)
        
        self.log.warning("⚠ Battle did not end within timeout")
        return False


# ============================================================================
# SKILL MANAGEMENT SYSTEM
# ============================================================================

class SkillManager:
    """
    Manages skill selection and navigation
    
    Skill Layout:
    - 12 total skills across 3 pages
    - Page 1: Skills 1-4 (Skill 1 = strongest, leftmost after battle starts)
    - Page 2: Skills 5-8
    - Page 3: Skills 9-12 (Skill 12 = weakest)
    - Navigate with left/right arrows
    """
    
    def __init__(self, cfg, io, log):
        self.cfg = cfg
        self.io = io
        self.log = log
        self.rois = DEFAULT_ROIS
        
        # Track current page (1, 2, or 3)
        self.current_page = 1
        
        # Skills visible on current page
        self.visible_skills = [1, 2, 3, 4]
    
    def reset_to_page_1(self):
        """Reset to page 1 (strongest skills) at battle start"""
        self.current_page = 1
        self.visible_skills = [1, 2, 3, 4]
        self.log.debug("Skill manager reset to page 1 (Skills 1-4)")
    
    def get_page_for_skill(self, skill_num: int) -> int:
        """Get which page a skill is on"""
        return ((skill_num - 1) // 4) + 1
    
    def navigate_to_skill(self, skill_num: int):
        """Navigate to the page containing the target skill"""
        if not (1 <= skill_num <= 12):
            self.log.error(f"Invalid skill number: {skill_num}")
            return False
        
        target_page = self.get_page_for_skill(skill_num)
        
        if target_page == self.current_page:
            self.log.debug(f"Skill {skill_num} already visible on page {self.current_page}")
            return True
        
        # Navigate to target page
        if target_page > self.current_page:
            # Scroll right (toward weaker skills)
            clicks_needed = target_page - self.current_page
            self.log.debug(f"Scrolling right {clicks_needed} page(s) to reach Skill {skill_num}")
            
            for _ in range(clicks_needed):
                self._click_right_arrow()
                time.sleep(0.3)
                self.current_page += 1
                self._update_visible_skills()
        
        elif target_page < self.current_page:
            # Scroll left (toward stronger skills)
            clicks_needed = self.current_page - target_page
            self.log.debug(f"Scrolling left {clicks_needed} page(s) to reach Skill {skill_num}")
            
            for _ in range(clicks_needed):
                self._click_left_arrow()
                time.sleep(0.3)
                self.current_page -= 1
                self._update_visible_skills()
        
        self.log.debug(f"Now on page {self.current_page}, visible skills: {self.visible_skills}")
        return True
    
    def _update_visible_skills(self):
        """Update list of currently visible skills based on page"""
        start_skill = ((self.current_page - 1) * 4) + 1
        self.visible_skills = [start_skill + i for i in range(4)]
    
    def _click_left_arrow(self):
        """Click left arrow to scroll to stronger skills"""
        roi = self.rois["skill_arrow_left"]
        self.io.click_xy(roi["x"], roi["y"])
        self.log.debug("← Clicked left arrow")
    
    def _click_right_arrow(self):
        """Click right arrow to scroll to weaker skills"""
        roi = self.rois["skill_arrow_right"]
        self.io.click_xy(roi["x"], roi["y"])
        self.log.debug("→ Clicked right arrow")
    
    def use_skill(self, skill_num: int) -> bool:
        """
        Use a specific skill (1-12)
        Automatically navigates if needed
        """
        if not (1 <= skill_num <= 12):
            self.log.error(f"Invalid skill number: {skill_num}")
            return False
        
        # Navigate to correct page
        if not self.navigate_to_skill(skill_num):
            return False
        
        # Find position in visible skills (1-4)
        if skill_num not in self.visible_skills:
            self.log.error(f"Skill {skill_num} not visible after navigation")
            return False
        
        position = self.visible_skills.index(skill_num) + 1  # 1-based
        
        # Click the skill slot
        slot_key = f"skill_slot_{position}"
        roi = self.rois[slot_key]
        
        strength = self._get_skill_strength_label(skill_num)
        self.log.info(f"⚔️ Using Skill {skill_num} ({strength})")
        
        self.io.click_xy(roi["x"], roi["y"])
        time.sleep(0.5)  # Wait for skill animation to start
        
        return True
    
    def _get_skill_strength_label(self, skill_num: int) -> str:
        """Get human-readable strength label"""
        if skill_num <= 3:
            return "STRONGEST"
        elif skill_num <= 6:
            return "STRONG"
        elif skill_num <= 9:
            return "MODERATE"
        else:
            return "WEAK"
    
    def wait_for_turn(self, timeout: float = 10.0) -> bool:
        """Wait for player's turn (animation/enemy turn to complete)"""
        start_time = time.time()
        check_interval = 0.5
        
        self.log.debug("Waiting for turn...")
        
        # Wait for turn indicator to appear
        while time.time() - start_time < timeout:
            try:
                roi = self.rois["turn_indicator"]
                # Use the vision instance from io's parent (Bot class will have it)
                # But we don't have direct access here, so we'll use mss directly
                from mss import mss
                
                with mss() as sct:
                    monitor = {
                        "left": roi["x"],
                        "top": roi["y"],
                        "width": roi["w"],
                        "height": roi["h"]
                    }
                    grab = sct.grab(monitor)
                    frame = np.array(grab)[:, :, :3]  # Get RGB
                    
                    if frame.size > 0:
                        # Look for blue turn indicator
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
                        blue_lower = np.array([100, 50, 50])
                        blue_upper = np.array([130, 255, 255])
                        blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)
                        blue_ratio = np.count_nonzero(blue_mask) / blue_mask.size
                        
                        if blue_ratio > 0.15:
                            self.log.debug("✓ Turn ready")
                            return True
            except Exception as e:
                self.log.debug(f"Turn check error: {e}")
                pass
            
            time.sleep(check_interval)
        
        self.log.warning("Turn timeout - proceeding anyway")
        return False


# ============================================================================
# HP MONITORING
# ============================================================================

class HPMonitor:
    """Monitor enemy HP percentage with high precision"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        self.rois = DEFAULT_ROIS
    
    def get_hp_percent(self) -> Optional[float]:
        """
        Read enemy HP percentage from HP bar
        Returns: HP as percentage (0-100), or None if unreadable
        """
        try:
            roi = self.rois["enemy_hp_bar"]
            frame = self.vision.screen_grab_region(roi["x"], roi["y"], roi["w"], roi["h"])
            
            if frame.size == 0:
                return None
            
            # Convert to HSV for color detection
            hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
            
            # Detect HP bar colors (green/yellow/red)
            green_mask = cv2.inRange(hsv, np.array([40, 50, 50]), np.array([80, 255, 255]))
            yellow_mask = cv2.inRange(hsv, np.array([20, 50, 50]), np.array([40, 255, 255]))
            red_mask = cv2.inRange(hsv, np.array([0, 50, 50]), np.array([10, 255, 255]))
            
            # Combine all HP colors
            hp_mask = green_mask | yellow_mask | red_mask
            
            if hp_mask.sum() == 0:
                return None
            
            # Calculate filled percentage based on horizontal fill
            # Find rightmost filled pixel in each row
            filled_cols = []
            for row in range(hp_mask.shape[0]):
                row_pixels = np.where(hp_mask[row] > 0)[0]
                if len(row_pixels) > 0:
                    filled_cols.append(row_pixels[-1])
            
            if not filled_cols:
                return 0.0
            
            # Average rightmost position across rows
            avg_rightmost = np.mean(filled_cols)
            percent = (avg_rightmost / frame.shape[1]) * 100
            
            return min(100.0, max(0.0, percent))
            
        except Exception as e:
            self.log.error(f"HP reading error: {e}")
            return None
    
    def get_hp_text(self) -> Optional[str]:
        """
        Read HP as text (e.g., "127/127") using OCR
        Returns: HP text or None
        """
        try:
            import pytesseract
            
            roi = self.rois["enemy_hp_text"]
            frame = self.vision.screen_grab_region(roi["x"], roi["y"], roi["w"], roi["h"])
            
            if frame.size == 0:
                return None
            
            # Preprocess for OCR
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Read text
            text = pytesseract.image_to_string(
                thresh,
                config='--psm 7 -c tessedit_char_whitelist=0123456789/'
            ).strip()
            
            # Validate format (e.g., "127/127")
            if '/' in text:
                return text
            
            return None
            
        except ImportError:
            self.log.debug("pytesseract not available for text HP reading")
            return None
        except Exception as e:
            self.log.error(f"HP text reading error: {e}")
            return None


# ============================================================================
# CAPTURE RATE DETECTION
# ============================================================================

class CaptureRateDetector:
    """Detect capture rate percentage and derive IP rating + rarity"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        self.rois = DEFAULT_ROIS
        
        # Check OCR availability
        try:
            import pytesseract
            self.has_ocr = True
        except ImportError:
            self.has_ocr = False
            self.log.warning("⚠ pytesseract not available - using visual estimation for capture rate")
    
    def detect_capture_rate(self) -> Optional[int]:
        """
        Read capture rate percentage from screen (e.g., "37%")
        Returns: Integer percentage (0-100) or None
        """
        try:
            roi = self.rois["capture_rate"]
            frame = self.vision.screen_grab_region(roi["x"], roi["y"], roi["w"], roi["h"])
            
            if frame.size == 0:
                return None
            
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            
            # Preprocess for OCR (white text on dark/colored background)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Invert if needed (OCR works best with dark text on light bg)
            if thresh[0, 0] < 128:
                thresh = cv2.bitwise_not(thresh)
            
            # Scale up for better OCR
            thresh = cv2.resize(thresh, (0, 0), fx=2, fy=2)
            
            if self.has_ocr:
                import pytesseract
                
                # Read text
                text = pytesseract.image_to_string(
                    thresh,
                    config='--psm 7 -c tessedit_char_whitelist=0123456789%'
                ).strip()
                
                # Extract number
                match = re.search(r'(\d+)', text)
                if match:
                    rate = int(match.group(1))
                    if 0 <= rate <= 100:
                        self.log.debug(f"Detected capture rate: {rate}%")
                        return rate
                    else:
                        self.log.warning(f"Capture rate out of range: {rate}%")
                else:
                    self.log.warning(f"Could not parse capture rate from: '{text}'")
            else:
                # Fallback: visual estimation (less accurate)
                return self._estimate_from_visual(thresh)
            
            return None
            
        except Exception as e:
            self.log.error(f"Capture rate detection error: {e}")
            return None
    
    def _estimate_from_visual(self, thresh) -> Optional[int]:
        """Fallback: estimate capture rate from visual patterns"""
        # Count white pixels (more digits = higher number)
        white_ratio = np.count_nonzero(thresh) / thresh.size
        
        # Very rough estimation
        if white_ratio > 0.4:
            return 90  # "100%" or high number
        elif white_ratio > 0.25:
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
            self.log.warning(f"⚠ Could not determine IP/rarity from capture rate {capture_rate}%")
            return (capture_rate, None, None)


# ============================================================================
# MAIN BATTLE CONTROLLER
# ============================================================================

class Battle:
    """Main battle logic controller - handles combat and capture decisions"""
    
    def __init__(self, cfg, vision, input_ctl, log, base_dir):
        self.cfg = cfg
        self.vision = vision
        self.io = input_ctl
        self.log = log
        self.base_dir = base_dir
        
        # Initialize sub-systems
        self.detector = BattleDetector(cfg, vision, log, base_dir)
        self.skill_mgr = SkillManager(cfg, input_ctl, log)
        self.hp_monitor = HPMonitor(cfg, vision, log)
        self.capture_detector = CaptureRateDetector(cfg, vision, log)
        
        # Statistics
        self.stats = {
            "total_battles": 0,
            "captures_attempted": 0,
            "captures_successful": 0,
            "skipped": 0,
            "defeated": 0
        }
    
    def is_eligible(self, rarity: str, ip_rating: str) -> bool:
        """Check if Miscrit meets capture criteria based on config"""
        if not rarity:
            self.log.warning("⚠ No rarity detected, cannot determine eligibility")
            return False
        
        # Get rarity configuration
        elig = self.cfg.get("eligibility", {}).get("per_rarity", {})
        rarity_cfg = elig.get(rarity, {})
        
        # Check if rarity is enabled for capture
        if not rarity_cfg.get("enabled", False):
            self.log.info(f"❌ {rarity} capture is disabled in config")
            return False
        
        # Check IP rating requirement
        min_ip = rarity_cfg.get("min_ip_rating", "A")
        
        if not ip_rating:
            self.log.warning(f"⚠ No IP rating detected for {rarity}, rejecting")
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
    
    def chip_hp_safely(self, rarity: str, target_hp_percent: float) -> bool:
        """
        Chip HP down to target percentage using appropriate skill
        
        Args:
            rarity: Rarity of Miscrit (determines which skill to use)
            target_hp_percent: Target HP percentage (e.g., 10.0 for 10%)
        
        Returns:
            True if successful, False if failed
        """
        max_attempts = 20  # Safety limit
        
        # Get rarity-specific damage skill
        rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
        damage_skill_str = rarity_cfg.get("damage_skill", "Skill 12")
        
        # Extract skill number
        try:
            damage_skill = int(damage_skill_str.split()[-1])
        except (ValueError, IndexError):
            self.log.error(f"Invalid damage skill config: {damage_skill_str}")
            damage_skill = 12  # Default to weakest
        
        self.log.info(f"💥 Chipping HP to {target_hp_percent:.1f}% using Skill {damage_skill}")
        
        for attempt in range(1, max_attempts + 1):
            # Read current HP
            hp = self.hp_monitor.get_hp_percent()
            
            if hp is None:
                self.log.warning(f"⚠ Cannot read HP (attempt {attempt}/{max_attempts}), attacking anyway")
                hp = 100.0  # Assume full HP if unreadable
            else:
                self.log.debug(f"Enemy HP: {hp:.1f}%")
            
            # Check if target reached
            if hp <= target_hp_percent:
                self.log.info(f"✓ HP threshold reached: {hp:.1f}% ≤ {target_hp_percent:.1f}%")
                return True
            
            # Use damage skill
            if not self.skill_mgr.use_skill(damage_skill):
                self.log.error(f"Failed to use Skill {damage_skill}")
                return False
            
            # Wait for damage animation and turn
            time.sleep(2.0)
            self.skill_mgr.wait_for_turn(timeout=8.0)
        
        self.log.warning(f"⚠ Could not chip HP after {max_attempts} attempts")
        return False
    
    def attempt_capture(self, rarity: str, max_attempts: int) -> bool:
        """
        Attempt to capture Miscrit
        
        Args:
            rarity: Rarity of Miscrit (determines capture skill)
            max_attempts: Maximum capture attempts
        
        Returns:
            True if capture successful, False otherwise
        """
        # Get rarity-specific capture skill
        rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
        capture_skill_str = rarity_cfg.get("capture_skill", "Skill 12")
        
        # Extract skill number
        try:
            capture_skill = int(capture_skill_str.split()[-1])
        except (ValueError, IndexError):
            self.log.error(f"Invalid capture skill config: {capture_skill_str}")
            capture_skill = 12  # Default to weakest
        
        self.log.info(f"🎯 Attempting capture using Skill {capture_skill} ({max_attempts} attempts max)")
        
        for attempt in range(1, max_attempts + 1):
            self.log.info(f"📦 Capture attempt {attempt}/{max_attempts}")
            
            # Use capture skill before capture attempt (optional, some strategies use this)
            # self.skill_mgr.use_skill(capture_skill)
            # time.sleep(1.5)
            
            # Click capture button (assuming 'C' key or specific position)
            # NOTE: This needs to be configured based on actual game UI
            self.io.key("c")  # Press C for capture
            time.sleep(3.5)  # Wait for capture animation
            
            # Check if capture was successful
            # In a real implementation, we'd detect success/failure dialog
            # For now, we'll check if battle ended
            if self.detector.is_battle_ended():
                self.log.info("✅ CAPTURE SUCCESSFUL!")
                self.stats["captures_successful"] += 1
                return True
            
            # If still in battle, capture failed
            self.log.warning(f"❌ Capture attempt {attempt} failed")
            
            # Wait for turn before next attempt
            self.skill_mgr.wait_for_turn(timeout=5.0)
        
        self.log.warning(f"❌ All {max_attempts} capture attempts failed")
        self.stats["captures_attempted"] += max_attempts
        return False
    
    def defeat_miscrit(self, quick_mode: bool = True):
        """
        Defeat non-target Miscrit quickly
        
        Args:
            quick_mode: If True, spam strongest skill without checking HP
        """
        defeat_skill_str = self.cfg.get("battle", {}).get("defeat_skill", "Skill 1")
        
        # Extract skill number
        try:
            defeat_skill = int(defeat_skill_str.split()[-1])
        except (ValueError, IndexError):
            self.log.error(f"Invalid defeat skill config: {defeat_skill_str}")
            defeat_skill = 1  # Default to strongest
        
        self.log.info(f"⚔️ Defeating Miscrit with Skill {defeat_skill} (quick={quick_mode})")
        
        if quick_mode:
            # Spam strongest skill without checking (faster)
            for i in range(1, 8):  # Max 7 attacks should be enough
                if self.detector.is_battle_ended():
                    self.log.info("✓ Miscrit defeated!")
                    break
                
                self.log.debug(f"Attack {i}/7")
                self.skill_mgr.use_skill(defeat_skill)
                time.sleep(1.8)  # Wait for animation
        else:
            # Check HP after each attack (safer but slower)
            for i in range(1, 12):  # Max 11 attacks
                hp = self.hp_monitor.get_hp_percent()
                
                if hp is not None and hp <= 0:
                    self.log.info("✓ Miscrit defeated (HP = 0)")
                    break
                
                if self.detector.is_battle_ended():
                    self.log.info("✓ Miscrit defeated!")
                    break
                
                hp_str = f"{hp:.1f}%" if hp is not None else "unknown"
                self.log.debug(f"Attack {i}/11 (Enemy HP: {hp_str})")
                self.skill_mgr.use_skill(defeat_skill)
                time.sleep(1.8)
                self.skill_mgr.wait_for_turn(timeout=6.0)
        
        # Wait for battle end screen
        self.detector.wait_for_battle_end(timeout=5.0)
        self.stats["defeated"] += 1
    
    def click_continue(self) -> bool:
        """Click Continue button after battle ends"""
        self.log.info("Clicking Continue...")
        
        # Wait a moment for button to be clickable
        time.sleep(1.0)
        
        roi = DEFAULT_ROIS["continue_button"]
        self.io.click_xy(roi["x"], roi["y"])
        
        time.sleep(1.5)  # Wait for transition
        
        self.log.info("✓ Clicked Continue")
        return True
    
    def handle_encounter(self) -> bool:
        """
        Main battle handler - complete battle flow
        
        Returns:
            True if handled successfully, False on error
        """
        try:
            self.stats["total_battles"] += 1
            
            # Wait for battle UI to stabilize
            time.sleep(1.5)
            
            # Reset skill manager to page 1 (strongest skills visible)
            self.skill_mgr.reset_to_page_1()
            
            # Wait for turn
            self.skill_mgr.wait_for_turn(timeout=10.0)
            time.sleep(0.5)
            
            # Detect Miscrit info from capture rate
            capture_rate, ip_rating, rarity = self.capture_detector.get_miscrit_info()
            
            if not rarity or not ip_rating:
                self.log.warning("⚠ Could not detect Miscrit info - defaulting to defeat")
                self.defeat_miscrit(quick_mode=True)
                time.sleep(1.0)
                self.click_continue()
                return True
            
            self.log.info("═" * 70)
            self.log.info(f"🎮 ENCOUNTER: {rarity} {ip_rating} (Base capture rate: {capture_rate}%)")
            self.log.info("═" * 70)
            
            # Check eligibility
            if not self.is_eligible(rarity, ip_rating):
                self.log.info("⏭️  Not eligible - defeating quickly")
                self.stats["skipped"] += 1
                
                # Quick defeat
                quick_defeat = self.cfg.get("battle", {}).get("quick_defeat", True)
                self.defeat_miscrit(quick_mode=quick_defeat)
                time.sleep(1.0)
                self.click_continue()
                return True
            
            # TARGET MISCRIT - Begin capture sequence!
            self.log.info("🎯 TARGET MISCRIT DETECTED! Initiating capture protocol...")
            self.log.info("═" * 70)
            
            # Get capture configuration for this rarity
            rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
            
            # Get HP threshold (can be rarity-specific or global)
            hp_threshold = rarity_cfg.get("capture_hp_percent", 
                                         self.cfg.get("battle", {}).get("capture_hp_percent", 10))
            
            # Get max capture attempts
            max_attempts = self.cfg.get("battle", {}).get("attempts", 3)
            
            self.log.info(f"📋 Capture Plan:")
            self.log.info(f"   • Target HP: {hp_threshold}%")
            self.log.info(f"   • Max attempts: {max_attempts}")
            self.log.info(f"   • Damage skill: {rarity_cfg.get('damage_skill', 'Skill 12')}")
            self.log.info(f"   • Capture skill: {rarity_cfg.get('capture_skill', 'Skill 12')}")
            
            # Step 1: Chip HP to threshold
            self.log.info("📉 Step 1: Reducing enemy HP...")
            if not self.chip_hp_safely(rarity, float(hp_threshold)):
                self.log.error("⚠ Failed to chip HP - attempting capture anyway")
            
            time.sleep(1.0)
            
            # Step 2: Attempt capture
            self.log.info("🎯 Step 2: Attempting capture...")
            success = self.attempt_capture(rarity, max_attempts)
            
            if not success:
                # Capture failed - defeat it
                self.log.warning("❌ Capture failed - defeating Miscrit")
                self.defeat_miscrit(quick_mode=True)
            
            # Step 3: Click continue
            time.sleep(1.5)
            self.click_continue()
            
            self.log.info("═" * 70)
            if success:
                self.log.info("✅ ENCOUNTER COMPLETE: Capture successful!")
            else:
                self.log.info("⚠️  ENCOUNTER COMPLETE: Capture failed, Miscrit defeated")
            self.log.info("═" * 70)
            
            return True
            
        except Exception as e:
            self.log.error(f"❌ Error handling encounter: {e}", exc_info=True)
            
            # Emergency cleanup - try to end battle
            try:
                self.defeat_miscrit(quick_mode=True)
                time.sleep(1.5)
                self.click_continue()
            except Exception:
                pass
            
            return False
    
    def get_stats(self) -> Dict:
        """Get battle statistics"""
        stats = self.stats.copy()
        
        if stats["captures_attempted"] > 0:
            stats["capture_success_rate"] = (
                stats["captures_successful"] / stats["captures_attempted"] * 100
            )
        else:
            stats["capture_success_rate"] = 0.0
        
        return stats


# ============================================================================
# BATTLE MANAGER (Integration with main bot loop)
# ============================================================================

class BattleManager:
    """
    Manages battle state and transitions
    Integrates with main bot loop in capture_loop.py
    """
    
    def __init__(self, cfg, vision, input_ctl, log, base_dir):
        self.battle = Battle(cfg, vision, input_ctl, log, base_dir)
        self.in_battle = False
        self.battle_count = 0
        self.log = log
    
    def check_and_handle_battle(self) -> bool:
        """
        Check if in battle and handle it if needed
        
        Returns:
            True if battle was handled, False if no battle detected
        """
        # Check if battle started
        if not self.in_battle:
            if self.battle.detector.is_in_battle():
                self.in_battle = True
                self.battle_count += 1
                
                self.log.info("")
                self.log.info("╔" + "═" * 68 + "╗")
                self.log.info(f"║  🎮 BATTLE #{self.battle_count} STARTED" + " " * 42 + "║")
                self.log.info("╚" + "═" * 68 + "╝")
                self.log.info("")
                
                # Handle the battle
                result = self.battle.handle_encounter()
                
                self.in_battle = False
                
                # Show stats
                stats = self.battle.get_stats()
                self.log.info("")
                self.log.info("📊 Session Statistics:")
                self.log.info(f"   • Total battles: {stats['total_battles']}")
                self.log.info(f"   • Captures: {stats['captures_successful']}")
                self.log.info(f"   • Skipped: {stats['skipped']}")
                self.log.info(f"   • Defeated: {stats['defeated']}")
                if stats['capture_success_rate'] > 0:
                    self.log.info(f"   • Success rate: {stats['capture_success_rate']:.1f}%")
                self.log.info("")
                
                return result
        
        return False
    
    def get_statistics(self) -> Dict:
        """Get battle statistics for UI display"""
        return self.battle.get_stats()


# ============================================================================
# ROI CONFIGURATION HELPER
# ============================================================================

def save_rois_to_config(cfg_path: str, custom_rois: Dict = None):
    """
    Save ROI configuration to config.json
    
    Args:
        cfg_path: Path to config.json
        custom_rois: Custom ROI dictionary (if None, uses defaults)
    """
    import json
    
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    rois = custom_rois if custom_rois else DEFAULT_ROIS
    
    cfg['battle']['rois'] = rois
    
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    
    print(f"✓ Saved {len(rois)} ROIs to {cfg_path}")


def print_roi_guide():
    """Print guide for configuring ROIs"""
    print("=" * 80)
    print("ROI CONFIGURATION GUIDE")
    print("=" * 80)
    print()
    print("Default ROIs are configured for 1152x648 game window.")
    print("If your game resolution is different, you may need to adjust ROIs.")
    print()
    print("Key ROIs to verify:")
    print()
    
    for key, roi in DEFAULT_ROIS.items():
        if isinstance(roi, dict) and 'description' in roi:
            print(f"  {key}:")
            print(f"    Description: {roi['description']}")
            if 'x' in roi:
                print(f"    Position: ({roi['x']}, {roi['y']}) Size: {roi.get('w', 'N/A')}x{roi.get('h', 'N/A')}")
            else:
                print(f"    Position: ({roi['x']}, {roi['y']})")
            print()
    
    print("=" * 80)
    print()


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    print("Miscrits Auto-Battle System - Enhanced Edition")
    print()
    print_roi_guide()
    print()
    print("This module provides:")
    print("  • Automatic battle detection")
    print("  • Skill navigation (12 skills across 3 pages)")
    print("  • HP monitoring with precision")
    print("  • Capture rate detection and IP/Rarity identification")
    print("  • Intelligent capture decision making")
    print("  • Automatic battle completion and continuation")
    print()
    print("Integration:")
    print("  1. Import BattleManager in capture_loop.py")
    print("  2. Initialize: battle_mgr = BattleManager(cfg, vision, input_ctl, log, base_dir)")
    print("  3. In main loop: battle_mgr.check_and_handle_battle()")
    print()
    print("Configuration:")
    print("  • Set capture criteria in config.json -> eligibility -> per_rarity")
    print("  • Configure skills: damage_skill (for HP chip), capture_skill (before capture)")
    print("  • Set HP thresholds per rarity: capture_hp_percent")
    print("  • Choose defeat strategy: defeat_skill, quick_defeat")
    print()