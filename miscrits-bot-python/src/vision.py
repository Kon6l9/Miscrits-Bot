
from typing import Optional, Tuple, Dict
import time, json, os
import numpy as np
import cv2
from mss import mss

RANK_ORDER = ["All","C","C+","B","B+","A","A+","S","S+"]

class Screen:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sct = mss()

    def grab(self, region=None):
        # region: x,y,w,h
        if region is None:
            mon = self.sct.monitors[1]
            grab = self.sct.grab(mon)
        else:
            x,y,w,h = region
            monitor = {"left": x, "top": y, "width": w, "height": h}
            grab = self.sct.grab(monitor)
        img = np.array(grab)
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

def filled_ratio(img_bgr):
    # simple horizontal bar: compute fraction of non-background pixels
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    # assume bar is darker than background OR vice versa; fallback to edge density
    colsum = th.sum(axis=0) / 255.0
    return float((colsum > (0.5*img_bgr.shape[0])).mean())

class Vision:
    def __init__(self, cfg):
        self.cfg = cfg

    def screen_grab_region(self, x, y, w, h):
        """
        Capture live region each time (no cached frame).
        Returns an RGB numpy array.
        """
        with mss.mss() as sct:  # new context each call = live
            monitor = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
            img = sct.grab(monitor)
            # MSS returns BGRA; convert to RGB
            frame = np.array(img)
            rgb = frame[:, :, :3][:, :, ::-1]  # BGRA→RGB
            return rgb