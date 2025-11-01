
import time, os
from typing import Dict, Any
from .utils import rank_ge

class Battle:
    def __init__(self, cfg, vision, input_ctl, log):
        self.cfg = cfg
        self.vision = vision
        self.io = input_ctl
        self.log = log

    def eligible(self, rarity: str, grade: str, name: str) -> bool:
        elig = self.cfg["eligibility"]
        names = elig.get("name_filter", [])
        if names and name and name not in names:
            return False
        rules = elig["per_rarity"].get(rarity or "", None)
        if not rules:
            return False
        if not rules.get("enabled", False):
            return False
        min_grade = rules.get("min_grade","All")
        if min_grade == "All":
            return True
        return rank_ge(grade, min_grade)

    def chip_to_threshold(self):
        threshold = self.cfg["battle"]["capture_hp_percent"]
        for _ in range(10):  # cap to avoid loops
            hp = self.vision.read_hp_percent() or 100.0
            if hp <= threshold: 
                break
            # press/click Skill(1) — you should bind it to a fixed hotkey or button template
            self.io.key("1")
            time.sleep(1.0)

    def capture_flow(self):
        attempts = self.cfg["battle"]["attempts"]
        if self.cfg["battle"]["capture_mode"]:
            self.io.key("2")  # Skill(2) before capture
            time.sleep(0.8)
        for i in range(attempts):
            # press "Capture" — bind to a hotkey if available
            self.io.key("c")
            time.sleep(2.0)
            # TODO: detect success by "confirm" template
        # if failed, finish battle (your game-specific key)
        self.finish_battle()

    def finish_battle(self):
        # defeat fast: use Skill(1) repeatedly as a placeholder
        for _ in range(3):
            self.io.key("1")
            time.sleep(1.0)
