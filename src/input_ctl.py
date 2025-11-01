# src/input_ctl.py
import time, random, json
import pyautogui as pag

class InputCtl:
    def __init__(self, cfg):
        self.cfg = cfg or {}
        pag.FAILSAFE = True  # move mouse to a corner to emergency stop

        inp = self.cfg.get("input", {})
        self.hover_ms = int(inp.get("hover_delay_ms", 250))
        self.move_min, self.move_max = inp.get("move_duration_range", [0.04, 0.11])
        self.click_min, self.click_max = inp.get("click_delay_ms_range", [80, 180])
        self.move_delay_min, self.move_delay_max = inp.get("move_delay_ms_range", [60, 140])

    def _rand(self, a, b):
        return random.uniform(a, b)

    def move_xy(self, x, y):
        """Smooth move with a tiny random delay after arriving."""
        dur = self._rand(self.move_min, self.move_max)
        pag.moveTo(x, y, duration=dur)
        time.sleep(self._rand(self.move_delay_min, self.move_delay_max) / 1000.0)

    def click_xy(self, x, y, button="left"):
        """
        Move → brief hover → click.
        The hover helps the game register an interactable target.
        """
        self.move_xy(x, y)
        if self.hover_ms > 0:
            time.sleep(self.hover_ms / 1000.0)

        # Small randomized press length so it looks human and avoids misses
        down_up_gap = self._rand(self.click_min, self.click_max) / 1000.0
        pag.mouseDown(x=x, y=y, button=button)
        time.sleep(down_up_gap)
        pag.mouseUp(x=x, y=y, button=button)
