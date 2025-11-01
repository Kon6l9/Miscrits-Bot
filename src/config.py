
import json, os
from dataclasses import dataclass
from typing import Any, Dict

class Config:
    def __init__(self, path: str):
        self.path = path
        with open(path, "r", encoding="utf-8") as f:
            self.data: Dict[str, Any] = json.load(f)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

def ensure_files(base_dir: str):
    # create empty coords if missing
    coords = os.path.join(base_dir, "Coords.json")
    if not os.path.exists(coords):
        with open(coords, "w", encoding="utf-8") as f:
            json.dump({"spots": []}, f, indent=2)
