
import time, random, os
from typing import Tuple
import pyautogui

try:
    import pydirectinput
    HAS_PDI = True
except Exception:
    HAS_PDI = False

def _jitter(a, b):
    return a + random.random() * (b - a)

class InputCtl:
    def __init__(self, cfg):
        self.cfg = cfg
        pyautogui.PAUSE = 0

    def _sleep_ms(self, ms):
        time.sleep(ms/1000.0)

    def move_to(self, x: int, y: int):
        d = _jitter(*self.cfg["input"]["move_duration_range"])
        pyautogui.moveTo(x, y, duration=d)
        self._sleep_ms(_jitter(*self.cfg["input"]["move_delay_ms_range"]))

    def click(self):
        pyautogui.click()
        self._sleep_ms(_jitter(*self.cfg["input"]["click_delay_ms_range"]))

    def click_xy(self, x: int, y: int):
        self.move_to(x, y); self.click()

    def key(self, key: str):
        backend = self.cfg["input"]["backend"]
        if backend == "pydirectinput" and HAS_PDI:
            pydirectinput.press(key)
        else:
            pyautogui.press(key)
        self._sleep_ms(_jitter(*self.cfg["input"]["click_delay_ms_range"]))
