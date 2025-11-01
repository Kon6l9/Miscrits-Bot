# src/capture_loop.py
import time, os, json
import cv2
import numpy as np
from mss import mss
from .vision import Vision
from .input_ctl import InputCtl
from .logger import setup_logger
from .window import find_window_by_title_substring, get_client_rect_on_screen, rect_to_xywh, bring_to_foreground
from .overlay import Overlay

SPOTS_FILE = "Coords.json"
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

        # ---- set these BEFORE calling _bind_window() ----
        self.show_preview = bool(self.cfg.get("debug", {}).get("show_preview", False))
        self.search_delay = max(
            1.0, float(self.cfg.get("search", {}).get("search_delay_ms", 10000)) / 1000.0
        )
        self.overlay = None
        self.running = False
        self.selected_spot = None
        self.window_rect = None
        self.window_xywh = None
        # --------------------------------------------------

        self._load_selected_spot()
        self._bind_window()
