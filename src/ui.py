import threading
import tkinter as tk
from tkinter import ttk, messagebox
import json, os, time

from PIL import ImageGrab  # clipboard image import
from .capture_loop import Bot

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CFG_PATH = os.path.join(BASE_DIR, "config.json")
SPOTS_PATH = os.path.join(BASE_DIR, "Coords.json")  # stores spots (template-only; no coords)

RARITIES = ["Common","Rare","Epic","Exotic","Legendary"]
GRADES = ["All","C","C+","B","B+","A","A+","S","S+"]

def _read_json(path, default_obj):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_obj

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

class BotUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Miscrits Bot (Python)")
        self.bot_thread = None
        self.bot: Bot | None = None

        self.cfg = _read_json(CFG_PATH, {})

        # ----- shared timing/alert vars used in Capture & Settings -----
        # Default spot-click delay → 10s if config has 0/missing
        sd_ms = int(self.cfg.get("search", {}).get("search_delay_ms", 0) or 10000)
        if sd_ms == 0:
            sd_ms = 10000
        self.var_search_delay = tk.IntVar(value=max(1, round(sd_ms/1000)))  # seconds UI

        self.var_cooldown = tk.IntVar(value=int(self.cfg.get("search", {}).get("cooldown_seconds", 25)))
        self.var_delay_click = tk.IntVar(value=int(self.cfg.get("search", {}).get("delay_click_ms", 10)))
        self.var_sound = tk.BooleanVar(value=bool(self.cfg.get("alerts", {}).get("play_sound", True)))
        self.var_alert_delay = tk.IntVar(value=int(self.cfg.get("alerts", {}).get("delay_after_alert_seconds", 0)))

        # Overlay toggle (replaces old debug viewer)
        self.var_show_overlay = tk.BooleanVar(value=bool(self.cfg.get("debug", {}).get("show_preview", False)))

        self._build_ui()

    # ---------------- UI BUILD ----------------
    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        self.tab_capture = ttk.Frame(nb)
        self.tab_battle = ttk.Frame(nb)
        self.tab_spots  = ttk.Frame(nb)
        self.tab_settings = ttk.Frame(nb)
        self.tab_logs = ttk.Frame(nb)

        nb.add(self.tab_capture, text="Capture Config")
        nb.add(self.tab_battle, text="Battle Config")
        nb.add(self.tab_spots,  text="Spots")
        nb.add(self.tab_settings, text="Settings")
        nb.add(self.tab_logs, text="Logs")
        nb.pack(fill="both", expand=True)

        self._build_tab_capture()
        self._build_tab_battle()
        self._build_tab_spots()
        self._build_tab_settings()
        self._build_tab_logs()
        self._build_run_controls()  # spot picker in capture tab

        # Footer controls
        footer = ttk.Frame(self.root)
        footer.pack(fill="x")
        self.btn_start = ttk.Button(footer, text="Start", command=self.start_bot)
        self.btn_stop  = ttk.Button(footer, text="Stop", command=self.stop_bot, state="disabled")
        self.btn_save  = ttk.Button(footer, text="Save Config", command=self.save_cfg)
        self.btn_start.pack(side="left", padx=6, pady=6)
        self.btn_stop.pack(side="left", padx=6, pady=6)
        self.btn_save.pack(side="right", padx=6, pady=6)

    def _build_tab_capture(self):
        frame = self.tab_capture
        ttk.Label(frame, text="Per-Rarity Rules (optional; doesn’t affect spot clicking)").grid(row=0, column=0, columnspan=4, sticky="w", pady=(6,2))

        # Mirror structure (kept for future eligibility checks)
        self.rarity_vars = {}
        self.grade_vars = {}
        row = 1
        elig = self.cfg.get("eligibility", {}).get("per_rarity", {})
        for r in RARITIES:
            var_enabled = tk.BooleanVar(value=elig.get(r,{}).get("enabled", False))
            var_grade = tk.StringVar(value=elig.get(r,{}).get("min_grade","All"))
            self.rarity_vars[r] = var_enabled
            self.grade_vars[r] = var_grade

            ttk.Checkbutton(frame, text=r, variable=var_enabled).grid(row=row, column=0, sticky="w", padx=6, pady=2)
            ttk.Label(frame, text="Min grade:").grid(row=row, column=1, sticky="e", padx=6)
            cb = ttk.Combobox(frame, values=GRADES, width=6, textvariable=var_grade, state="readonly")
            cb.grid(row=row, column=2, sticky="w", padx=6)
            row += 1

        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="we", pady=6); row += 1

        names = ",".join(self.cfg.get("eligibility", {}).get("name_filter", []))
        ttk.Label(frame, text="Optional name filter (comma-separated):").grid(row=row, column=0, columnspan=4, sticky="w", padx=6)
        row += 1
        self.entry_names = ttk.Entry(frame, width=50)
        self.entry_names.insert(0, names)
        self.entry_names.grid(row=row, column=0, columnspan=4, sticky="w", padx=6, pady=(0,10))
        row += 1

        # ----- Timing, Overlay & Alerts -----
        ttk.Label(frame, text="Timing, Overlay & Alerts").grid(row=row, column=0, columnspan=4, sticky="w", padx=6)
        row += 1

        ttk.Label(frame, text="Spot click delay (seconds):").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(frame, from_=1, to=120, textvariable=self.var_search_delay, width=6)\
            .grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Checkbutton(frame, text="Show overlay (on-top debug)", variable=self.var_show_overlay)\
            .grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(frame, text="Cooldown between battles (seconds):").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(frame, from_=0, to=300, textvariable=self.var_cooldown, width=6)\
            .grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(frame, text="Delay click (ms):").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(frame, from_=0, to=500, textvariable=self.var_delay_click, width=6)\
            .grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Checkbutton(frame, text="Play sound on eligible", variable=self.var_sound)\
            .grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        row += 1

        ttk.Label(frame, text="Delay after alert (seconds):").grid(row=row, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(frame, from_=0, to=30, textvariable=self.var_alert_delay, width=6)\
            .grid(row=row, column=1, sticky="w")

    def _build_run_controls(self):
        # Spot selector at the bottom of the Capture tab
        frame = ttk.Frame(self.tab_capture)
        frame.grid(row=99, column=0, columnspan=4, sticky="we", padx=6, pady=(12,6))
        ttk.Label(frame, text="Spot to farm:").grid(row=0, column=0, sticky="e")
        self.var_spot_choice = tk.StringVar()
        self._reload_spot_choices()
        self.cb_spot = ttk.Combobox(frame, textvariable=self.var_spot_choice, values=self.spot_choices, width=36, state="readonly")
        self.cb_spot.grid(row=0, column=1, sticky="w", padx=6)
        if self.spot_choices:
            self.cb_spot.current(0)
        ttk.Label(frame, text="(Pick one before Start)").grid(row=0, column=2, sticky="w", padx=6)

    def _reload_spot_choices(self):
        self.spot_choices = []
        data = _read_json(SPOTS_PATH, {"spots": []})
        for s in data.get("spots", []):
            self.spot_choices.append(s.get("name","Spot"))

    def _build_tab_battle(self):
        frame = self.tab_battle
        bcfg = self.cfg.get("battle", {})

        ttk.Label(frame, text="Capture HP % gate:").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        self.var_hp_gate = tk.IntVar(value=bcfg.get("capture_hp_percent",45))
        ttk.Spinbox(frame, from_=1, to=99, textvariable=self.var_hp_gate, width=5).grid(row=0, column=1, sticky="w")

        ttk.Label(frame, text="Attempts per battle:").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        self.var_attempts = tk.IntVar(value=bcfg.get("attempts",1))
        ttk.Spinbox(frame, from_=1, to=5, textvariable=self.var_attempts, width=5).grid(row=1, column=1, sticky="w")

        self.var_capture_mode = tk.BooleanVar(value=bcfg.get("capture_mode", False))
        ttk.Checkbutton(frame, text="Capture Mode (use Skill 2)", variable=self.var_capture_mode).grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        ttk.Label(frame, text="HP bar ROI (x,y,w,h):").grid(row=3, column=0, sticky="e", padx=6, pady=6)
        self.entry_hp_roi = ttk.Entry(frame, width=24)
        self.entry_hp_roi.insert(0, ",".join(map(str, bcfg.get("hp_bar_roi",[100,100,400,20]))))
        self.entry_hp_roi.grid(row=3, column=1, sticky="w")

        ttk.Label(frame, text="Grade ROI (x,y,w,h):").grid(row=4, column=0, sticky="e", padx=6, pady=6)
        self.entry_grade_roi = ttk.Entry(frame, width=24)
        self.entry_grade_roi.insert(0, ",".join(map(str, bcfg.get("grade_roi",[520,140,90,40]))))
        self.entry_grade_roi.grid(row=4, column=1, sticky="w")

        ttk.Label(frame, text="Templates (PNG in assets/templates):").grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(12,0))
        ttk.Label(frame, text="skill1.png, skill2.png, capture_button.png, confirm_button.png, finish_button.png").grid(row=6, column=0, columnspan=2, sticky="w", padx=12)

    def _build_tab_spots(self):
        frame = self.tab_spots
        ttk.Label(frame, text="Saved spots (template only):").grid(row=0, column=0, sticky="w", padx=6)
        self.listbox_spots = tk.Listbox(frame, width=52, height=12)
        self.listbox_spots.grid(row=1, column=0, rowspan=8, sticky="nsw", padx=6, pady=6)
        self._reload_spots_listbox()

        right = ttk.Frame(frame); right.grid(row=1, column=1, sticky="n")
        self.entry_spot_name = ttk.Entry(right, width=30)
        self.entry_spot_name.insert(0, "NewSpot")
        self.entry_spot_name.pack(anchor="w", pady=(0,6))
        ttk.Button(right, text="Add New Spot (name only)", command=self.add_spot).pack(anchor="w", pady=2)
        ttk.Button(right, text="Use clipboard image as template", command=self.import_template_from_clipboard).pack(anchor="w", pady=2)
        ttk.Button(right, text="Replace template from clipboard", command=self.replace_template_from_clipboard).pack(anchor="w", pady=2)
        ttk.Button(right, text="Edit threshold of selected", command=self.edit_threshold_for_selected).pack(anchor="w", pady=6)
        ttk.Button(right, text="Delete Selected", command=self.delete_spot).pack(anchor="w", pady=2)

        ttk.Label(right, text="Threshold (0.70–0.98):").pack(anchor="w", pady=(10,2))
        self.entry_threshold = ttk.Entry(right, width=10)
        self.entry_threshold.insert(0, "0.82")
        self.entry_threshold.pack(anchor="w")

    def _build_tab_settings(self):
        frame = self.tab_settings
        ttk.Label(frame, text="Cooldown (seconds):").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        ttk.Spinbox(frame, from_=0, to=300, textvariable=self.var_cooldown, width=6).grid(row=0, column=1, sticky="w")

        ttk.Label(frame, text="Delay click (ms):").grid(row=1, column=0, sticky="e", padx=6, pady=6)
        ttk.Spinbox(frame, from_=0, to=500, textvariable=self.var_delay_click, width=6).grid(row=1, column=1, sticky="w")

        ttk.Label(frame, text="Spot click delay (seconds):").grid(row=2, column=0, sticky="e", padx=6, pady=6)
        ttk.Spinbox(frame, from_=1, to=120, textvariable=self.var_search_delay, width=6).grid(row=2, column=1, sticky="w")

        ttk.Checkbutton(frame, text="Play sound on eligible", variable=self.var_sound).grid(row=3, column=0, columnspan=2, sticky="w", padx=6)

        ttk.Label(frame, text="Delay after alert (seconds):").grid(row=4, column=0, sticky="e", padx=6, pady=6)
        ttk.Spinbox(frame, from_=0, to=30, textvariable=self.var_alert_delay, width=6).grid(row=4, column=1, sticky="w")

        # Optional: bind to current foreground window (if you added helpers)
        ttk.Button(frame, text="Bind to current window", command=self.bind_current_window)\
            .grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(6,0))

    def _build_tab_logs(self):
        frame = self.tab_logs
        self.txt_logs = tk.Text(frame, width=96, height=18)
        self.txt_logs.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_logs.insert("end", "Logs will appear here while running.\n")

    # ---------------- list helpers ----------------
    def _reload_spots_listbox(self):
        self.listbox_spots.delete(0, "end")
        data = _read_json(SPOTS_PATH, {"spots": []})
        for s in data.get("spots", []):
            name = s.get("name","Spot")
            tpl = s.get("template","(no template)")
            thr = s.get("threshold", 0.82)
            self.listbox_spots.insert("end", f"{name}  —  {tpl}  —  thr={thr:.2f}")

    def _reload_spot_choices(self):
        self.spot_choices = []
        data = _read_json(SPOTS_PATH, {"spots": []})
        for s in data.get("spots", []):
            self.spot_choices.append(s.get("name","Spot"))

    # ---------------- actions ----------------
    def save_cfg(self, silent: bool = False):
        # capture tab → rarity settings
        per_rarity = self.cfg.setdefault("eligibility", {}).setdefault("per_rarity", {})
        for r in RARITIES:
            per_rarity.setdefault(r, {})
            per_rarity[r]["enabled"] = bool(self.rarity_vars[r].get())
            per_rarity[r]["min_grade"] = self.grade_vars[r].get()

        names = [n.strip() for n in self.entry_names.get().split(",") if n.strip()]
        self.cfg.setdefault("eligibility", {})["name_filter"] = names

        # shared timing/alerts + overlay debug
        self.cfg.setdefault("search", {})["cooldown_seconds"] = int(self.var_cooldown.get())
        self.cfg["search"]["delay_click_ms"] = int(self.var_delay_click.get())
        self.cfg["search"]["search_delay_ms"] = int(self.var_search_delay.get()) * 1000  # seconds → ms
        self.cfg.setdefault("alerts", {})["play_sound"] = bool(self.var_sound.get())
        self.cfg["alerts"]["delay_after_alert_seconds"] = int(self.var_alert_delay.get())

        # IMPORTANT: store under debug.show_preview (capture_loop reads this)
        self.cfg.setdefault("debug", {})["show_preview"] = bool(self.var_show_overlay.get())

        # battle
        self.cfg.setdefault("battle", {})
        self.cfg["battle"]["capture_hp_percent"] = int(getattr(self, "var_hp_gate").get())
        self.cfg["battle"]["attempts"] = int(getattr(self, "var_attempts").get())
        self.cfg["battle"]["capture_mode"] = bool(getattr(self, "var_capture_mode").get())
        self.cfg["battle"]["hp_bar_roi"] = [int(x) for x in self.entry_hp_roi.get().split(",")]
        self.cfg["battle"]["grade_roi"] = [int(x) for x in self.entry_grade_roi.get().split(",")]

        _write_json(CFG_PATH, self.cfg)
        if not silent:
            messagebox.showinfo("Saved", "Configuration saved.")

    def add_spot(self):
        name = self.entry_spot_name.get().strip() or "Spot"
        data = _read_json(SPOTS_PATH, {"spots": []})
        data.setdefault("spots", []).append({
            "name": name,
            "template": "",
            "threshold": 0.82,
            "roi": [0,0,0,0]
        })
        _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        self._reload_spot_choices()
        messagebox.showinfo("Spot added", f"Added '{name}'. Now attach a template from clipboard.")

    def _clipboard_to_template_file(self):
        """Save clipboard image into our project folder and return relative path."""
        img = ImageGrab.grabclipboard()
        if img is None:
            return None, "Clipboard doesn't contain an image. Press Win+Shift+S to snip, then try again."

        tpl_dir = os.path.join(BASE_DIR, "assets", "templates", "spots")
        os.makedirs(tpl_dir, exist_ok=True)

        ts = int(time.time())
        tpl_path = os.path.join(tpl_dir, f"spot_{ts}.png")
        img.save(tpl_path)
        rel = os.path.relpath(tpl_path, BASE_DIR).replace("\\", "/")
        return rel, None

    def import_template_from_clipboard(self):
        idxs = self.listbox_spots.curselection()
        if not idxs:
            messagebox.showerror("No spot selected", "Select a saved spot on the left, then try again.")
            return
        sel = idxs[0]

        rel, err = self._clipboard_to_template_file()
        if err:
            messagebox.showerror("No image", err); return

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel >= len(spots):
            messagebox.showerror("Out of range", "Bad selection index."); return

        s = spots[sel]
        s["template"] = rel

        # optional override threshold from entry if valid
        try:
            th = float(self.entry_threshold.get())
            if 0.5 <= th <= 0.99:
                s["threshold"] = th
        except Exception:
            pass

        _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        messagebox.showinfo("Template saved", f"Saved template file at:\n{rel}\nAttached to spot: {s.get('name','Spot')}")

    def replace_template_from_clipboard(self):
        self.import_template_from_clipboard()

    def edit_threshold_for_selected(self):
        idxs = self.listbox_spots.curselection()
        if not idxs:
            messagebox.showerror("No selection", "Select a spot first."); return
        sel = idxs[0]
        try:
            th = float(self.entry_threshold.get())
        except Exception:
            messagebox.showerror("Invalid", "Enter a number like 0.82"); return
        if not (0.5 <= th <= 0.99):
            messagebox.showerror("Invalid", "Threshold should be between 0.50 and 0.99"); return

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel >= len(spots):
            messagebox.showerror("Out of range", "Bad selection index."); return

        spots[sel]["threshold"] = th
        _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        messagebox.showinfo("Updated", f"Threshold updated to {th:.2f} for selected spot.")

    def delete_spot(self):
        idx = self.listbox_spots.curselection()
        if not idx: return
        sel = idx[0]

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel < len(spots):
            spots.pop(sel)
            data["spots"] = spots
            _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        self._reload_spot_choices()

    def bind_current_window(self):
        # Optional; only works if you added helpers in window.py
        try:
            from .window import get_foreground_hwnd, is_window_valid, get_process_image
        except Exception:
            messagebox.showerror("Missing feature", "Bind requires window helpers present.")
            return
        hwnd = get_foreground_hwnd()
        if not is_window_valid(hwnd):
            messagebox.showerror("Bind failed", "No valid foreground window detected."); return
        exe = get_process_image(hwnd) or "(unknown exe)"
        self.cfg.setdefault("run", {})["bound_hwnd"] = int(hwnd)
        _write_json(CFG_PATH, self.cfg)
        messagebox.showinfo("Bound", f"Bound to HWND={hwnd}\nEXE: {exe}")

    def start_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            messagebox.showwarning("Running", "Bot already running."); return

        # save without popup
        self.save_cfg(silent=True)

        # ensure a spot is chosen
        if not hasattr(self, "cb_spot") or not self.cb_spot.get():
            messagebox.showerror("Pick a spot", "Choose a spot in 'Spot to farm' before Start.")
            return

        # store selected spot index into config
        chosen_name = self.cb_spot.get()
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        sel_idx = 0
        for i, s in enumerate(spots):
            if s.get("name","Spot") == chosen_name:
                sel_idx = i; break

        cfg = _read_json(CFG_PATH, {})
        cfg.setdefault("run", {})["selected_spot_index"] = sel_idx
        _write_json(CFG_PATH, cfg)

        self._log("Starting bot… (focusing Miscrits and scanning for the chosen template)")
        self.bot = Bot(CFG_PATH, BASE_DIR)

        def run():
            try:
                self.bot.start()
            except Exception as e:
                self._log(f"ERROR: {e}")
            finally:
                self._log("Bot stopped.")
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")

        self.bot_thread = threading.Thread(target=run, daemon=True)
        self.bot_thread.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.root.after(1000, self._tail_log)

    def stop_bot(self):
        if self.bot:
            self.bot.stop()
        self.btn_stop.config(state="disabled")
        self.btn_start.config(state="normal")

    def _tail_log(self):
        log_path = os.path.join(BASE_DIR, "bot.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-18:]
                self.txt_logs.delete("1.0", "end")
                for ln in lines:
                    self.txt_logs.insert("end", ln)
            except Exception:
                pass
        if self.bot_thread and self.bot_thread.is_alive():
            self.root.after(1000, self._tail_log)

    def _log(self, msg: str):
        try:
            self.txt_logs.insert("end", msg + "\n")
            self.txt_logs.see("end")
        except Exception:
            pass

def launch():
    root = tk.Tk()
    BotUI(root)
    root.mainloop()
