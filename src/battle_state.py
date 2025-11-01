# src/battle_state.py (RUN BUTTON DETECTION)
"""
Battle state detection using the run button template.
"""
import cv2
import numpy as np
from enum import Enum, auto
from typing import Tuple
import time
import os


class BotState(Enum):
    """Bot operational states"""
    SEARCHING = auto()
    IN_BATTLE = auto()
    COOLDOWN = auto()


class BattleDetector:
    """
    Detects battle state by looking for the run button.
    Simple and reliable!
    """
    
    def __init__(self, cfg: dict, base_dir: str):
        self.cfg = cfg
        self.base_dir = base_dir
        
        # State tracking
        self.current_state = BotState.SEARCHING
        self.state_confidence = 0.0
        self.state_entered_time = time.time()
        self.consecutive_detections = 0
        
        # Require N consecutive detections before state change
        self.required_consecutive = 2
        
        # Detection threshold for run button
        self.run_button_threshold = 0.75
        
        # Load run button template
        run_button_path = os.path.join(base_dir, "assets", "templates", "battle", "run_button.png")
        
        if os.path.exists(run_button_path):
            self.run_button_template = cv2.imread(run_button_path, cv2.IMREAD_COLOR)
            if self.run_button_template is not None:
                h, w = self.run_button_template.shape[:2]
                print(f"[STATE] Run button template loaded: {w}x{h} pixels")
            else:
                print(f"[STATE] ERROR: Failed to read run button template at {run_button_path}")
                self.run_button_template = None
        else:
            print(f"[STATE] WARNING: Run button template not found at {run_button_path}")
            self.run_button_template = None
        
        print("[STATE] BattleDetector initialized (RUN BUTTON MODE)")
    
    def detect_state(self, frame_bgr: np.ndarray) -> Tuple[BotState, float]:
        """
        Analyze frame and determine if we're in battle by looking for run button.
        """
        if self.run_button_template is None:
            # No template loaded, stay in current state
            return self.current_state, 0.5
        
        # Look for run button in the frame
        found, confidence = self._find_run_button(frame_bgr)
        
        # Determine state
        if found:
            detected = BotState.IN_BATTLE
        else:
            detected = BotState.SEARCHING
        
        # Update with hysteresis (prevent flickering)
        if detected == self.current_state:
            self.consecutive_detections += 1
        else:
            self.consecutive_detections = 1
        
        # Change state after consecutive detections
        if self.consecutive_detections >= self.required_consecutive:
            if detected != self.current_state:
                old_state = self.current_state
                self.current_state = detected
                self.state_entered_time = time.time()
                
                # LOG STATE CHANGE
                print(f"\n{'='*60}")
                print(f"[STATE CHANGE] {old_state.name} --> {detected.name}")
                print(f"[STATE CHANGE] Confidence: {confidence:.2%}")
                print(f"{'='*60}\n")
        
        self.state_confidence = confidence
        return self.current_state, confidence
    
    def _find_run_button(self, frame: np.ndarray) -> Tuple[bool, float]:
        """
        Search for run button in the frame using template matching.
        Returns (found, confidence_score)
        """
        # Search in bottom-left area where run button typically appears
        h, w = frame.shape[:2]
        
        # Define search region (left 1/3 of screen, bottom 1/3)
        search_y_start = int(h * 0.66)
        search_x_end = int(w * 0.33)
        search_region = frame[search_y_start:h, 0:search_x_end]
        
        # DEBUG: Print search info every 30 frames
        if not hasattr(self, '_debug_counter'):
            self._debug_counter = 0
        self._debug_counter += 1
        
        if self._debug_counter % 30 == 0:
            print(f"[DEBUG] Frame size: {w}x{h}, Search region: {search_x_end}x{h-search_y_start}")
            print(f"[DEBUG] Template size: {self.run_button_template.shape[1]}x{self.run_button_template.shape[0]}")
        
        if search_region.size == 0:
            print("[DEBUG] ERROR: Search region is empty!")
            return False, 0.0
        
        # Perform template matching
        try:
            result = cv2.matchTemplate(search_region, self.run_button_template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        except Exception as e:
            print(f"[DEBUG] Template matching error: {e}")
            return False, 0.0
        
        # DEBUG: Show best match score periodically
        if self._debug_counter % 30 == 0:
            print(f"[DEBUG] Best match score: {max_val:.3f} (threshold: {self.run_button_threshold})")
        
        # Check if match is good enough
        found = max_val >= self.run_button_threshold
        
        if found:
            # Calculate position in full frame
            btn_x = max_loc[0]
            btn_y = max_loc[1] + search_y_start
            print(f"[STATE] ✓ Run button detected at ({btn_x}, {btn_y}) - score: {max_val:.3f}")
        
        return found, max_val
    
    def get_state_duration(self) -> float:
        """How long we've been in current state (seconds)"""
        return time.time() - self.state_entered_time
    
    def force_state(self, state: BotState):
        """Manually set state (for testing)"""
        if state != self.current_state:
            print(f"[FORCE STATE] {self.current_state.name} -> {state.name}")
            self.current_state = state
            self.state_entered_time = time.time()
            self.consecutive_detections = self.required_consecutive
    
    def get_debug_info(self) -> dict:
        """Get debug information about current detection"""
        return {
            "state": self.current_state.name,
            "confidence": self.state_confidence,
            "duration": self.get_state_duration(),
            "consecutive": self.consecutive_detections,
            "has_template": self.run_button_template is not None,
        }