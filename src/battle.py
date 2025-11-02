# src/battle.py - Enhanced Battle System with Phase Tracking
import time
import cv2
import numpy as np
import re
from enum import Enum
from typing import Optional, Tuple, Dict, List
from .utils import ip_rating_meets_minimum

# ============================================================================
# BATTLE PHASES
# ============================================================================

class BattlePhase(Enum):
    NOT_IN_BATTLE = "not_in_battle"
    BATTLE_START = "battle_start"
    TURN_WAITING = "turn_waiting"
    TURN_READY = "turn_ready"
    SKILL_ANIMATION = "skill_animation"
    CAPTURE_ATTEMPT = "capture_attempt"
    CAPTURE_SUCCESS = "capture_success"
    CAPTURE_FAILED = "capture_failed"
    BATTLE_WON = "battle_won"
    BATTLE_LOST = "battle_lost"
    BATTLE_END = "battle_end"

# ============================================================================
# CONSTANTS & DATA TABLES
# ============================================================================

IP_RATINGS_ORDER = ["S+", "S", "A+", "A", "B+", "B", "C+", "C", "D+", "D", "F+", "F", "F-"]

# Updated capture rate table from the provided image
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

CAPTURE_RATE_TABLE_1HP = {
    "C+": {"Legendary": 95},
    "B": {"Legendary": 93},
    "B+": {"Legendary": 92},
    "A": {"Exotic": 99, "Legendary": 90},
    "A+": {"Exotic": 99, "Legendary": 89},
    "S": {"Exotic": 97, "Legendary": 87},
    "S+": {"Exotic": 96, "Legendary": 86},
}

# ROI Definitions for 1152x648 resolution
DEFAULT_ROIS = {
    "capture_rate": {"x": 560, "y": 235, "w": 80, "h": 40},
    "enemy_hp_bar": {"x": 755, "y": 205, "w": 70, "h": 8},
    "enemy_hp_text": {"x": 750, "y": 210, "w": 80, "h": 20},
    "player_hp_bar": {"x": 390, "y": 205, "w": 85, "h": 8},
    "turn_indicator": {"x": 450, "y": 580, "w": 250, "h": 30},
    "skills_bar": {"x": 340, "y": 600, "w": 540, "h": 70},
    "abilities_tab": {"x": 380, "y": 585, "w": 80, "h": 25},
    "items_tab": {"x": 470, "y": 585, "w": 80, "h": 25},
    "skill_slot_1": {"x": 405, "y": 628},
    "skill_slot_2": {"x": 488, "y": 628},
    "skill_slot_3": {"x": 655, "y": 628},
    "skill_slot_4": {"x": 738, "y": 628},
    "skill_arrow_left": {"x": 330, "y": 628},
    "skill_arrow_right": {"x": 865, "y": 628},
    "continue_button": {"x": 576, "y": 580, "w": 100, "h": 40},
    "victory_text": {"x": 400, "y": 200, "w": 350, "h": 80},
    "capture_dialog": {"x": 400, "y": 300, "w": 350, "h": 200},
    "keep_button": {"x": 410, "y": 450, "w": 80, "h": 30},
    "release_button": {"x": 550, "y": 450, "w": 80, "h": 30},
    "battle_circles": {"x": 350, "y": 250, "w": 180, "h": 40},
}

def estimate_ip_rating_from_capture_rate(capture_rate: int, possible_rarities=None) -> Tuple[Optional[str], Optional[str]]:
    """Estimate IP rating and rarity from capture rate at 100% HP"""
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
    
    if best_match and best_diff <= 3:
        return best_match
    return (None, None)

# ============================================================================
# PHASE TRACKER
# ============================================================================

class PhaseTracker:
    """Tracks current battle phase and transitions"""
    
    def __init__(self, log):
        self.log = log
        self.current_phase = BattlePhase.NOT_IN_BATTLE
        self.phase_start_time = time.time()
        self.phase_history = []
        
    def transition_to(self, new_phase: BattlePhase):
        """Transition to a new phase"""
        if self.current_phase == new_phase:
            return
        
        duration = time.time() - self.phase_start_time
        self.phase_history.append({
            "phase": self.current_phase,
            "duration": duration
        })
        
        self.log.debug(f"Phase transition: {self.current_phase.value} -> {new_phase.value} (took {duration:.1f}s)")
        self.current_phase = new_phase
        self.phase_start_time = time.time()
    
    def get_phase_duration(self) -> float:
        """Get duration of current phase"""
        return time.time() - self.phase_start_time
    
    def is_phase(self, phase: BattlePhase) -> bool:
        """Check if currently in specified phase"""
        return self.current_phase == phase
    
    def reset(self):
        """Reset phase tracker"""
        self.current_phase = BattlePhase.NOT_IN_BATTLE
        self.phase_start_time = time.time()
        self.phase_history = []

# ============================================================================
# BATTLE DETECTOR
# ============================================================================

class BattleDetector:
    """Enhanced battle detection with phase awareness"""
    
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
        
        continue_path = os.path.join(self.base_dir, "assets", "templates", "battle", "continue_button.png")
        if os.path.exists(continue_path):
            self.continue_template = cv2.imread(continue_path, cv2.IMREAD_COLOR)
    
    def detect_battle_phase(self) -> BattlePhase:
        """Detect current battle phase from screen"""
        # Check for victory screen
        if self._detect_victory_screen():
            return BattlePhase.BATTLE_WON
        
        # Check for capture dialog
        if self._detect_capture_dialog():
            return BattlePhase.CAPTURE_SUCCESS
        
        # Check for turn indicator
        if self._detect_turn_ready():
            return BattlePhase.TURN_READY
        
        # Check for battle indicators (HP bars, skills visible)
        if self._detect_battle_ui():
            return BattlePhase.TURN_WAITING
        
        return BattlePhase.NOT_IN_BATTLE
    
    def _detect_battle_ui(self) -> bool:
        """Detect if battle UI is present"""
        try:
            from mss import mss
            roi = self.rois["skills_bar"]
            
            with mss() as sct:
                monitor = {
                    "left": roi["x"],
                    "top": roi["y"], 
                    "width": roi["w"],
                    "height": roi["h"]
                }
                grab = sct.grab(monitor)
                frame = np.array(grab)[:, :, :3]
            
            if frame.size == 0:
                return False
            
            # Check for skill bar colors
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = np.count_nonzero(edges) / edges.size
            
            return edge_ratio > 0.05
        except Exception:
            return False
    
    def _detect_turn_ready(self) -> bool:
        """Detect 'It's your turn!' indicator"""
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
                frame = np.array(grab)[:, :, :3]
            
            if frame.size == 0:
                return False
            
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
            
            # Blue banner detection
            blue_lower = np.array([100, 50, 50])
            blue_upper = np.array([130, 255, 255])
            blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)
            blue_ratio = np.count_nonzero(blue_mask) / blue_mask.size
            
            return blue_ratio > 0.15
        except Exception:
            return False
    
    def _detect_victory_screen(self) -> bool:
        """Detect 'You Win!' victory screen"""
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
                frame = np.array(grab)[:, :, :3]
            
            if frame.size == 0:
                return False
            
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
            
            # Green victory banner
            green_lower = np.array([40, 50, 50])
            green_upper = np.array([80, 255, 255])
            green_mask = cv2.inRange(hsv, green_lower, green_upper)
            green_ratio = np.count_nonzero(green_mask) / green_mask.size
            
            return green_ratio > 0.1
        except Exception:
            return False
    
    def _detect_capture_dialog(self) -> bool:
        """Detect capture success dialog with Keep/Release buttons"""
        try:
            from mss import mss
            roi = self.rois["capture_dialog"]
            
            with mss() as sct:
                monitor = {
                    "left": roi["x"],
                    "top": roi["y"],
                    "width": roi["w"],
                    "height": roi["h"]
                }
                grab = sct.grab(monitor)
                frame = np.array(grab)[:, :, :3]
            
            if frame.size == 0:
                return False
            
            # Look for orange/yellow capture dialog
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
            
            # Orange/yellow dialog detection
            orange_lower = np.array([10, 100, 100])
            orange_upper = np.array([30, 255, 255])
            orange_mask = cv2.inRange(hsv, orange_lower, orange_upper)
            orange_ratio = np.count_nonzero(orange_mask) / orange_mask.size
            
            return orange_ratio > 0.15
        except Exception:
            return False

# ============================================================================
# SKILL MANAGER
# ============================================================================

class SkillManager:
    """Enhanced skill management with page tracking"""
    
    def __init__(self, cfg, io, log):
        self.cfg = cfg
        self.io = io
        self.log = log
        self.rois = DEFAULT_ROIS
        self.current_page = 1
        self.visible_skills = [1, 2, 3, 4]
    
    def reset_to_page_1(self):
        """Reset to page 1 (strongest skills)"""
        self.current_page = 1
        self.visible_skills = [1, 2, 3, 4]
    
    def get_page_for_skill(self, skill_num: int) -> int:
        """Get which page a skill is on (1-3)"""
        return ((skill_num - 1) // 4) + 1
    
    def navigate_to_skill(self, skill_num: int):
        """Navigate to page containing target skill using arrow keys"""
        if not (1 <= skill_num <= 12):
            self.log.error(f"Invalid skill number: {skill_num}")
            return False
        
        target_page = self.get_page_for_skill(skill_num)
        
        if target_page == self.current_page:
            return True
        
        # Calculate navigation
        if target_page > self.current_page:
            # Press right arrow
            for _ in range(target_page - self.current_page):
                self.io.key("right")
                time.sleep(0.3)
        else:
            # Press left arrow
            for _ in range(self.current_page - target_page):
                self.io.key("left")
                time.sleep(0.3)
        
        self.current_page = target_page
        self._update_visible_skills()
        
        return True
    
    def _update_visible_skills(self):
        """Update list of currently visible skills"""
        start_skill = ((self.current_page - 1) * 4) + 1
        self.visible_skills = [start_skill + i for i in range(4)]
    
    def use_skill(self, skill_num: int) -> bool:
        """Use a skill by number (1-12)"""
        if not self.navigate_to_skill(skill_num):
            return False
        
        position = ((skill_num - 1) % 4) + 1
        slot_key = f"skill_slot_{position}"
        roi = self.rois[slot_key]
        
        self.log.info(f"⚔️ Using Skill {skill_num}")
        self.io.click_xy(roi["x"], roi["y"])
        time.sleep(0.5)
        
        return True

# ============================================================================
# HP MONITOR
# ============================================================================

class HPMonitor:
    """Monitor HP with improved accuracy"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        self.rois = DEFAULT_ROIS
    
    def get_hp_percent(self) -> Optional[float]:
        """Read enemy HP percentage from HP bar"""
        try:
            roi = self.rois["enemy_hp_bar"]
            frame = self.vision.screen_grab_region(roi["x"], roi["y"], roi["w"], roi["h"])
            
            if frame.size == 0:
                return None
            
            hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
            
            # Detect all HP bar colors
            green_mask = cv2.inRange(hsv, np.array([40, 50, 50]), np.array([80, 255, 255]))
            yellow_mask = cv2.inRange(hsv, np.array([20, 50, 50]), np.array([40, 255, 255]))
            red_mask = cv2.inRange(hsv, np.array([0, 50, 50]), np.array([10, 255, 255]))
            
            hp_mask = green_mask | yellow_mask | red_mask
            
            if hp_mask.sum() == 0:
                return 0.0
            
            # Calculate fill percentage
            filled_cols = []
            for row in range(hp_mask.shape[0]):
                row_pixels = np.where(hp_mask[row] > 0)[0]
                if len(row_pixels) > 0:
                    filled_cols.append(row_pixels[-1])
            
            if not filled_cols:
                return 0.0
            
            avg_rightmost = np.mean(filled_cols)
            percent = (avg_rightmost / frame.shape[1]) * 100
            
            return min(100.0, max(0.0, percent))
        except Exception as e:
            self.log.error(f"HP reading error: {e}")
            return None

# ============================================================================
# CAPTURE RATE DETECTOR
# ============================================================================

class CaptureRateDetector:
    """Detect capture rate and derive Miscrit info"""
    
    def __init__(self, cfg, vision, log):
        self.cfg = cfg
        self.vision = vision
        self.log = log
        self.rois = DEFAULT_ROIS
        
        try:
            import pytesseract
            self.has_ocr = True
        except ImportError:
            self.has_ocr = False
    
    def detect_capture_rate(self) -> Optional[int]:
        """Read capture rate percentage"""
        try:
            roi = self.rois["capture_rate"]
            frame = self.vision.screen_grab_region(roi["x"], roi["y"], roi["w"], roi["h"])
            
            if frame.size == 0:
                return None
            
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            if thresh[0, 0] < 128:
                thresh = cv2.bitwise_not(thresh)
            
            thresh = cv2.resize(thresh, (0, 0), fx=2, fy=2)
            
            if self.has_ocr:
                import pytesseract
                text = pytesseract.image_to_string(
                    thresh,
                    config='--psm 7 -c tessedit_char_whitelist=0123456789%'
                ).strip()
                
                match = re.search(r'(\d+)', text)
                if match:
                    rate = int(match.group(1))
                    if 0 <= rate <= 100:
                        return rate
            
            return None
        except Exception as e:
            self.log.error(f"Capture rate detection error: {e}")
            return None
    
    def get_miscrit_info(self) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        """Detect capture rate and derive IP rating + rarity"""
        capture_rate = self.detect_capture_rate()
        
        if capture_rate is None:
            return (None, None, None)
        
        ip_rating, rarity = estimate_ip_rating_from_capture_rate(capture_rate)
        
        if ip_rating and rarity:
            self.log.info(f"📊 {rarity} {ip_rating} (Capture: {capture_rate}%)")
            return (capture_rate, ip_rating, rarity)
        
        return (capture_rate, None, None)

# ============================================================================
# BATTLE CONTROLLER
# ============================================================================

class Battle:
    """Enhanced battle controller with phase management"""
    
    def __init__(self, cfg, vision, input_ctl, log, base_dir):
        self.cfg = cfg
        self.vision = vision
        self.io = input_ctl
        self.log = log
        self.base_dir = base_dir
        
        # Initialize subsystems
        self.detector = BattleDetector(cfg, vision, log, base_dir)
        self.skill_mgr = SkillManager(cfg, input_ctl, log)
        self.hp_monitor = HPMonitor(cfg, vision, log)
        self.capture_detector = CaptureRateDetector(cfg, vision, log)
        self.phase_tracker = PhaseTracker(log)
        
        # ADD THIS LINE - Store reference to rois for easy access
        self.rois = self.detector.rois
        
        # Battle mode configuration
        self.battle_mode = cfg.get("battle", {}).get("mode", "capture")
        
        # Statistics
        self.stats = {
            "total_battles": 0,
            "captures_attempted": 0,
            "captures_successful": 0,
            "skipped": 0,
            "defeated": 0
        }
    
    def is_eligible(self, rarity: str, ip_rating: str) -> bool:
        """Check if Miscrit meets capture criteria"""
        if self.battle_mode == "defeat":
            return False
        
        if not rarity:
            return False
        
        elig = self.cfg.get("eligibility", {}).get("per_rarity", {})
        rarity_cfg = elig.get(rarity, {})
        
        if not rarity_cfg.get("enabled", False):
            return False
        
        min_ip = rarity_cfg.get("min_ip_rating", "A")
        
        if not ip_rating:
            return False
        
        if min_ip == "B+ and Below":
            if ip_rating not in ["B+", "B", "C+", "C", "D+", "D", "F+", "F", "F-"]:
                return False
        else:
            if not ip_rating_meets_minimum(ip_rating, min_ip):
                return False
        
        self.log.info(f"✅ ELIGIBLE: {rarity} {ip_rating}")
        return True
    
    def wait_for_turn(self, timeout: float = 8.0) -> bool:
        """Wait for turn to be ready"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            phase = self.detector.detect_battle_phase()
            
            if phase == BattlePhase.TURN_READY:
                self.phase_tracker.transition_to(BattlePhase.TURN_READY)
                return True
            
            time.sleep(0.3)
        
        return False
    
    def chip_hp_to_threshold(self, rarity: str, target_hp: float) -> bool:
        """Reduce enemy HP to target threshold"""
        max_attempts = 15
        
        rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
        damage_skill_str = rarity_cfg.get("damage_skill", "Skill 11")
        
        try:
            damage_skill = int(damage_skill_str.split()[-1])
        except:
            damage_skill = 11
        
        self.log.info(f"💥 Reducing HP to {target_hp:.1f}%")
        
        for attempt in range(1, max_attempts + 1):
            hp = self.hp_monitor.get_hp_percent()
            
            if hp is not None and hp <= target_hp:
                self.log.info(f"✓ Target HP reached: {hp:.1f}%")
                return True
            
            self.wait_for_turn(5.0)
            self.skill_mgr.use_skill(damage_skill)
            self.phase_tracker.transition_to(BattlePhase.SKILL_ANIMATION)
            time.sleep(2.5)
        
        return False
    
    def attempt_capture(self, rarity: str, max_attempts: int) -> bool:
        """Execute capture sequence"""
        rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
        capture_skill_str = rarity_cfg.get("capture_skill", "Skill 12")
        
        try:
            capture_skill = int(capture_skill_str.split()[-1])
        except:
            capture_skill = 12
        
        self.log.info(f"🎯 Capture attempts: {max_attempts}")
        
        for attempt in range(1, max_attempts + 1):
            self.log.info(f"📦 Attempt {attempt}/{max_attempts}")
            
            self.wait_for_turn(5.0)
            
            if self.cfg.get("battle", {}).get("use_capture_skill_before", False):
                self.skill_mgr.use_skill(capture_skill)
                time.sleep(2.0)
                self.wait_for_turn(5.0)
            
            self.io.key("c")
            self.phase_tracker.transition_to(BattlePhase.CAPTURE_ATTEMPT)
            time.sleep(3.5)
            
            phase = self.detector.detect_battle_phase()
            
            if phase == BattlePhase.CAPTURE_SUCCESS:
                self.log.info("✅ CAPTURE SUCCESSFUL!")
                self.phase_tracker.transition_to(BattlePhase.CAPTURE_SUCCESS)
                
                time.sleep(1.0)
                # FIXED: Use self.detector.rois instead of self.rois
                keep_roi = self.detector.rois["keep_button"]
                self.io.click_xy(keep_roi["x"], keep_roi["y"])
                self.stats["captures_successful"] += 1
                
                time.sleep(2.0)
                return True
            
            self.log.warning(f"❌ Attempt {attempt} failed")
        
        self.stats["captures_attempted"] += max_attempts
        return False
    
    def defeat_quickly(self):
        """Defeat Miscrit using strongest skills"""
        defeat_skill_str = self.cfg.get("battle", {}).get("defeat_skill", "Skill 1")
        
        try:
            defeat_skill = int(defeat_skill_str.split()[-1])
        except:
            defeat_skill = 1
        
        self.log.info(f"⚔️ Quick defeat with Skill {defeat_skill}")
        
        for i in range(1, 8):
            phase = self.detector.detect_battle_phase()
            
            if phase in [BattlePhase.BATTLE_WON, BattlePhase.BATTLE_END]:
                break
            
            self.wait_for_turn(5.0)
            self.skill_mgr.use_skill(defeat_skill)
            time.sleep(2.0)
        
        self.stats["defeated"] += 1
    
    def click_continue(self):
        """Click Continue button after battle"""
        time.sleep(1.5)
        roi = self.rois["continue_button"]
        self.io.click_xy(roi["x"], roi["y"])
        self.log.info("✓ Clicked Continue")
        time.sleep(1.5)
    
    def handle_encounter(self) -> bool:
        """Main battle handler with phase tracking"""
        try:
            self.stats["total_battles"] += 1
            self.phase_tracker.reset()
            self.phase_tracker.transition_to(BattlePhase.BATTLE_START)
            
            time.sleep(2.0)
            self.skill_mgr.reset_to_page_1()
            
            # Wait for first turn
            if not self.wait_for_turn(10.0):
                self.log.warning("Turn timeout")
            
            # Detect Miscrit info
            capture_rate, ip_rating, rarity = self.capture_detector.get_miscrit_info()
            
            if not rarity or not ip_rating:
                self.log.warning("Could not detect Miscrit info")
                self.defeat_quickly()
                self.click_continue()
                return True
            
            self.log.info("═" * 50)
            self.log.info(f"🎮 {rarity} {ip_rating} (Rate: {capture_rate}%)")
            self.log.info("═" * 50)
            
            # Check eligibility
            if not self.is_eligible(rarity, ip_rating):
                self.log.info("⏭️ Not eligible - defeating")
                self.stats["skipped"] += 1
                self.defeat_quickly()
            else:
                # Capture sequence
                self.log.info("🎯 TARGET DETECTED - Capture mode")
                
                hp_threshold = self.cfg.get("battle", {}).get("capture_hp_percent", 10)
                max_attempts = self.cfg.get("battle", {}).get("attempts", 3)
                
                # Chip HP
                if not self.chip_hp_to_threshold(rarity, float(hp_threshold)):
                    self.log.warning("Failed to reduce HP")
                
                # Attempt capture
                if not self.attempt_capture(rarity, max_attempts):
                    self.log.warning("Capture failed - defeating")
                    self.defeat_quickly()
            
            # Wait for battle end
            time.sleep(2.0)
            phase = self.detector.detect_battle_phase()
            
            if phase == BattlePhase.BATTLE_WON:
                self.click_continue()
            
            self.phase_tracker.transition_to(BattlePhase.BATTLE_END)
            return True
            
        except Exception as e:
            self.log.error(f"Battle error: {e}", exc_info=True)
            try:
                self.defeat_quickly()
                self.click_continue()
            except:
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
# BATTLE MANAGER
# ============================================================================

class BattleManager:
    """Manages battle detection and handling with cooldown tracking"""
    
    def __init__(self, cfg, vision, input_ctl, log, base_dir):
        self.battle = Battle(cfg, vision, input_ctl, log, base_dir)
        self.in_battle = False
        self.battle_count = 0
        self.log = log
        self.last_battle_end = 0
        self.cooldown_duration = 24.0  # Default cooldown (reduced by trait)
        
        # Check for cooldown reduction trait
        if cfg.get("traits", {}).get("cooldown_reduction", False):
            self.cooldown_duration = 24.0  # 24s with trait
        else:
            self.cooldown_duration = 34.0  # 34s without trait
    
    def check_and_handle_battle(self) -> bool:
        """Check for battle and handle if detected"""
        phase = self.battle.detector.detect_battle_phase()
        
        if not self.in_battle and phase != BattlePhase.NOT_IN_BATTLE:
            self.in_battle = True
            self.battle_count += 1
            
            self.log.info("")
            self.log.info("╔" + "═" * 50 + "╗")
            self.log.info(f"║  BATTLE #{self.battle_count}" + " " * 39 + "║")
            self.log.info("╚" + "═" * 50 + "╝")
            
            result = self.battle.handle_encounter()
            
            self.in_battle = False
            self.last_battle_end = time.time()
            
            # Show stats
            stats = self.battle.get_stats()
            self.log.info("📊 Session Stats:")
            self.log.info(f"   Battles: {stats['total_battles']}")
            self.log.info(f"   Captures: {stats['captures_successful']}")
            self.log.info(f"   Skipped: {stats['skipped']}")
            self.log.info(f"   Defeated: {stats['defeated']}")
            
            return result
        
        return False
    
    def get_cooldown_remaining(self) -> float:
        """Get remaining cooldown time"""
        if self.last_battle_end == 0:
            return 0
        
        elapsed = time.time() - self.last_battle_end
        remaining = max(0, self.cooldown_duration - elapsed)
        return remaining
    
    def get_statistics(self) -> Dict:
        """Get battle statistics"""
        return self.battle.get_stats()

# ROI helper for UI calibration
def save_rois_to_config(cfg_path: str, custom_rois: Dict = None):
    """Save ROI configuration"""
    import json
    
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    rois = custom_rois if custom_rois else DEFAULT_ROIS
    cfg['battle']['rois'] = rois
    
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)