
import json, os, time
from typing import Dict, List
import pyautogui

class Spots:
    def __init__(self, base_dir: str):
        self.path = os.path.join(base_dir, "Coords.json")
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"spots":[]}, f)
        with open(self.path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def add_spot_from_mouse(self, name: str):
        x,y = pyautogui.position()
        self.data["spots"].append({"name": name, "x": int(x), "y": int(y)})
        self.save()
        return x,y

    def list(self):
        return self.data.get("spots", [])
