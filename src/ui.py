import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import json, time
from datetime import datetime

from PIL import Image, ImageTk, ImageGrab
from .capture_loop import Bot

BASE_DIR   = os.path.dirname(os.path.dirname(__file__))
CFG_PATH   = os.path.join(BASE_DIR, "config.json")
SPOTS_PATH = os.path.join(BASE_DIR, "Coords.json")

RARITIES = ["Common", "Rare", "Epic", "Exotic", "Legendary"]
GRADES   = ["All", "C", "C+", "B", "B+", "A", "A+", "S", "S+"]

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
        self.bot = None

        self.cfg = _read_json(CFG_PATH, {})

        # timing/alert vars used on Capture tab
        sd_ms = int(self.cfg.get("search", {}).get("search_delay_ms", 0) or 10000)
        if sd_ms == 0:
            sd_ms = 10000
        self.var_search_delay = tk.IntVar(value=max(1, round(sd_ms / 1000)))
        self.var_cooldown     = tk.IntVar(value=int(self.cfg.get("search", {}).get("cooldown_seconds", 25)))
        self.var_delay_click  = tk.IntVar(value=int(self.cfg.get("search", {}).get("delay_click_ms", 10)))
        self.var_sound        = tk.BooleanVar(value=bool(self.cfg.get("alerts", {}).get("play_sound", True)))
        self.var_alert_delay  = tk.IntVar(value=int(self.cfg.get("alerts", {}).get("delay_after_alert_seconds", 0)))
        self.var_show_overlay = tk.BooleanVar(value=bool(self.cfg.get("debug",  {}).get("show_preview", False)))

        # overlayed per-row buttons in the Spots table
        self._row_btns = {}   # iid -> {edit, delete, preview}

        self._build_ui()

    # ---------------- UI BUILD ----------------
    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        self.tab_capture = ttk.Frame(nb)
        self.tab_battle  = ttk.Frame(nb)
        self.tab_spots   = ttk.Frame(nb)
        self.tab_logs    = ttk.Frame(nb)

        nb.add(self.tab_capture, text="Capture Config")
        nb.add(self.tab_battle,  text="Battle Config")
        nb.add(self.tab_spots,   text="Spots")
        nb.add(self.tab_logs,    text="Logs")
        nb.pack(fill="both", expand=True)

        self._build_tab_capture_compact()
        self._build_tab_battle()
        self._build_tab_spots_simple()
        self._build_tab_logs()
        self._build_run_controls()

        footer = ttk.Frame(self.root)
        footer.pack(fill="x")
        self.btn_start   = ttk.Button(footer, text="Start", command=self.start_bot)
        self.btn_stop    = ttk.Button(footer, text="Stop", state="disabled", command=self.stop_bot)
        self.btn_restart = ttk.Button(footer, text="Restart App", command=self.restart_app)
        self.btn_save    = ttk.Button(footer, text="Save Config", command=self.save_cfg)
        self.btn_start.pack(side="left", padx=6, pady=6)
        self.btn_stop.pack(side="left", padx=6, pady=6)
        self.btn_restart.pack(side="right", padx=6, pady=6)
        self.btn_save.pack(side="right", padx=6, pady=6)

    # ---------------- CAPTURE TAB (compact layout) ----------------
    def _build_tab_capture_compact(self):
        frame = self.tab_capture
        frame.grid_columnconfigure(0, weight=1, minsize=420)
        frame.grid_columnconfigure(1, weight=1, minsize=360)
        frame.grid_rowconfigure(1, weight=1)  # let bottom log stretch

        # LEFT: Rarities
        left = ttk.LabelFrame(frame, text="Per-Rarity Rules (optional; doesn’t affect spot clicking)")
        left.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        self.rarity_vars = {}
        self.grade_vars  = {}
        elig = self.cfg.get("eligibility", {}).get("per_rarity", {})
        for row, r in enumerate(RARITIES):
            var_enabled = tk.BooleanVar(value=elig.get(r, {}).get("enabled", False))
            var_grade   = tk.StringVar(value=elig.get(r, {}).get("min_grade", "All"))
            self.rarity_vars[r] = var_enabled
            self.grade_vars[r]  = var_grade
            ttk.Checkbutton(left, text=r, variable=var_enabled).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            ttk.Label(left, text="Min grade:").grid(row=row, column=1, sticky="e", padx=6)
            ttk.Combobox(left, values=GRADES, width=6, textvariable=var_grade, state="readonly").grid(row=row, column=2, sticky="w", padx=6)

        # RIGHT: Timing, Overlay & Alerts
        right = ttk.LabelFrame(frame, text="Timing, Overlay & Alerts")
        right.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)

        ttk.Label(right, text="Spot click delay (seconds):").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(right, from_=1, to=120, textvariable=self.var_search_delay, width=6).grid(row=0, column=1, sticky="w")

        ttk.Checkbutton(right, text="Show overlay (on-top debug)", variable=self.var_show_overlay).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(right, text="Cooldown between battles (seconds):").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(right, from_=0, to=300, textvariable=self.var_cooldown, width=6).grid(row=2, column=1, sticky="w")

        ttk.Label(right, text="Delay click (ms):").grid(row=3, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(right, from_=0, to=500, textvariable=self.var_delay_click, width=6).grid(row=3, column=1, sticky="w")

        ttk.Checkbutton(right, text="Play sound on eligible", variable=self.var_sound).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(right, text="Delay after alert (seconds):").grid(row=5, column=0, sticky="e", padx=6, pady=4)
        ttk.Spinbox(right, from_=0, to=30, textvariable=self.var_alert_delay, width=6).grid(row=5, column=1, sticky="w")

        # BOTTOM: Live Mode Log
        log_frame = ttk.LabelFrame(frame, text="Live Mode Log")
        log_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=(0,6))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.txt_capture_log = tk.Text(log_frame, height=10, wrap="none")
        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_capture_log.yview)
        self.txt_capture_log.configure(yscrollcommand=yscroll.set)
        self.txt_capture_log.grid(row=0, column=0, sticky="nsew", padx=(6,0), pady=6)
        yscroll.grid(row=0, column=1, sticky="ns", padx=(0,6), pady=6)

    def _build_run_controls(self):
        frame = ttk.Frame(self.tab_capture)
        frame.grid(row=99, column=0, columnspan=2, sticky="we", padx=6, pady=(6, 4))
        ttk.Label(frame, text="Spot to farm:").grid(row=0, column=0, sticky="e")
        self.var_spot_choice = tk.StringVar()
        self._reload_spot_choices()
        self.cb_spot = ttk.Combobox(frame, textvariable=self.var_spot_choice, values=self.spot_choices, width=40, state="readonly")
        self.cb_spot.grid(row=0, column=1, sticky="w", padx=6)
        if self.spot_choices:
            self.cb_spot.current(0)
        ttk.Label(frame, text="(Pick one before Start)").grid(row=0, column=2, sticky="w", padx=6)

    def _reload_spot_choices(self):
        self.spot_choices = []
        data = _read_json(SPOTS_PATH, {"spots": []})
        for s in data.get("spots", []):
            self.spot_choices.append(s.get("name", "Spot"))

    # ---------------- BATTLE TAB ----------------
    def _build_tab_battle(self):
        frame = self.tab_battle
        ttk.Label(frame, text="Capture Behavior").grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(6, 2))

        ttk.Label(frame, text="Try capture when enemy HP at or below (%):").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.var_hp_gate = tk.IntVar(value=int(self.cfg.get("battle", {}).get("capture_hp_percent", 45)))
        ttk.Spinbox(frame, from_=1, to=99, textvariable=self.var_hp_gate, width=6).grid(row=1, column=1, sticky="w")

        ttk.Label(frame, text="Capture attempts (per battle):").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        self.var_attempts = tk.IntVar(value=int(self.cfg.get("battle", {}).get("attempts", 1)))
        ttk.Spinbox(frame, from_=1, to=5, textvariable=self.var_attempts, width=6).grid(row=2, column=1, sticky="w")

        self.var_capture_mode = tk.BooleanVar(value=bool(self.cfg.get("battle", {}).get("capture_mode", False)))
        ttk.Checkbutton(frame, text="Enable capture mode (use configured skill/capture flow)", variable=self.var_capture_mode).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="HP bar ROI (x,y,w,h):").grid(row=4, column=0, sticky="e", padx=6, pady=4)
        self.entry_hp_roi = ttk.Entry(frame, width=24)
        self.entry_hp_roi.insert(0, ",".join(map(str, self.cfg.get("battle", {}).get("hp_bar_roi", [100, 100, 400, 20]))))
        self.entry_hp_roi.grid(row=4, column=1, sticky="w", padx=6)

        ttk.Label(frame, text="Grade ROI (x,y,w,h):").grid(row=5, column=0, sticky="e", padx=6, pady=4)
        self.entry_grade_roi = ttk.Entry(frame, width=24)
        self.entry_grade_roi.insert(0, ",".join(map(str, self.cfg.get("battle", {}).get("grade_roi", [100, 100, 120, 40]))))
        self.entry_grade_roi.grid(row=5, column=1, sticky="w", padx=6)

    # ---------------- SPOTS TAB ----------------
    def _build_tab_spots_simple(self):
        frame = self.tab_spots
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        ttk.Label(frame, text="Spots (template + threshold)").grid(row=0, column=0, sticky="w", padx=6, pady=(6, 0))

        tool = ttk.Frame(frame)
        tool.grid(row=1, column=0, sticky="we", padx=6, pady=(6, 4))
        ttk.Button(tool, text="Add New Spot", command=self._popup_add_new_spot).pack(side="left", padx=(0, 6))
        ttk.Button(tool, text="Apply Clipboard", command=self.apply_clipboard_to_selected).pack(side="left", padx=(0, 6))

        style = ttk.Style(self.root)
        style.configure("Spots.Treeview", rowheight=32)
        style.configure("Spots.Treeview.Heading", padding=(6, 4))
        cols = ("name", "th", "preview", "edit", "delete")

        self.tree_spots = ttk.Treeview(frame, columns=cols, show="headings", height=12, style="Spots.Treeview")
        self.tree_spots.heading("name",    text="Name")
        self.tree_spots.heading("th",      text="Threshold")
        self.tree_spots.heading("preview", text="Preview")
        self.tree_spots.heading("edit",    text="Edit")
        self.tree_spots.heading("delete",  text="Delete")
        self.tree_spots.column("name",    width=320, anchor="w")
        self.tree_spots.column("th",      width=90,  anchor="center")
        self.tree_spots.column("preview", width=100, anchor="center")
        self.tree_spots.column("edit",    width=90,  anchor="center")
        self.tree_spots.column("delete",  width=90,  anchor="center")
        self.tree_spots.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)

        for ev in ("<Configure>", "<<TreeviewSelect>>", "<ButtonRelease-1>",
                   "<MouseWheel>", "<KeyRelease-Up>", "<KeyRelease-Down>", "<Map>"):
            self.tree_spots.bind(ev, lambda e: self._refresh_action_buttons())
        self.root.after(50, self._refresh_action_buttons)

        self._reload_spots_tree()

    # ---- Spots helpers/actions ----
    def _resolve_template_abs(self, p: str) -> str:
        if not p:
            return ""
        return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)

    def _has_template(self, spot_dict):
        p = (spot_dict or {}).get("template")
        abs_p = self._resolve_template_abs(p)
        return bool(abs_p and os.path.exists(abs_p))

    def _row_tuple(self, s):
        name = s.get("name", "Spot")
        th   = float(s.get("threshold", 0.85))
        return (name, f"{th:.2f}", "", "", "")

    def _reload_spots_tree(self):
        for iid in self.tree_spots.get_children():
            self.tree_spots.delete(iid)
        for btns in self._row_btns.values():
            for b in btns.values():
                try: b.destroy()
                except: pass
        self._row_btns = {}

        data = _read_json(SPOTS_PATH, {"spots": []})
        for idx, s in enumerate(data.get("spots", [])):
            self.tree_spots.insert("", "end", iid=str(idx), values=self._row_tuple(s))

        self._refresh_action_buttons()
        self._reload_spot_choices()

    def _selected_index(self):
        sel = self.tree_spots.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def _ensure_buttons_for_iid(self, iid):
        if iid in self._row_btns:
            return
        idx = int(iid)

        def on_edit(i=idx):   self._popup_edit_spot(i)
        def on_delete(i=idx): self._delete_spot_by_index(i)
        def on_preview(i=idx):self._open_preview(i)

        edit_btn = ttk.Button(self.tree_spots, text="Edit", width=8, command=on_edit)
        del_btn  = ttk.Button(self.tree_spots, text="Delete", width=8, command=on_delete)
        prev_btn = ttk.Button(self.tree_spots, text="Preview", width=9, command=on_preview)

        self._row_btns[iid] = {"edit": edit_btn, "delete": del_btn, "preview": prev_btn}

    def _place_button_in_cell(self, iid, column_id, btn, minw=74):
        bbox = self.tree_spots.bbox(iid, column_id)
        if not bbox:
            btn.place_forget()
            return
        x, y, w, h = bbox
        wbtn, hbtn = max(minw, 70), 24
        bx = x + (w - wbtn) // 2
        by = y + (h - hbtn) // 2
        btn.place(x=bx, y=by, width=wbtn, height=hbtn)

    def _refresh_action_buttons(self):
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])

        for iid in self.tree_spots.get_children():
            self._ensure_buttons_for_iid(iid)
            i = int(iid)
            has_img = False
            if 0 <= i < len(spots):
                has_img = self._has_template(spots[i])

            btns = self._row_btns[iid]
            try:
                btns["preview"]["state"] = ("normal" if has_img else "disabled")
            except Exception:
                pass

            self._place_button_in_cell(iid, "preview", btns["preview"], minw=80)
            self._place_button_in_cell(iid, "edit",    btns["edit"])
            self._place_button_in_cell(iid, "delete",  btns["delete"])

    # ---------- Popups ----------
    def _center_popup(self, win):
        win.update_idletasks()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        ww, wh = win.winfo_width(), win.winfo_height()
        x = max(0, rx + (rw - ww) // 2)
        y = max(0, ry + (rh - wh) // 2)
        win.geometry(f"+{x}+{y}")

    def _popup_add_new_spot(self):
        win = tk.Toplevel(self.root)
        win.title("Add New Spot")
        win.resizable(False, False)

        ttk.Label(win, text="Spot name:").grid(row=0, column=0, sticky="e", padx=8, pady=8)
        name_var = tk.StringVar()
        ent = ttk.Entry(win, textvariable=name_var, width=28)
        ent.grid(row=0, column=1, sticky="w", padx=8, pady=8)

        def do_create():
            name = (name_var.get() or "").strip() or "Spot"
            self._add_spot_record(name=name, threshold=0.85, template_path=None)
            win.destroy()

        ttk.Button(win, text="Create", command=do_create).grid(row=1, column=1, sticky="e", padx=8, pady=(0,8))
        ent.focus_set()
        win.bind("<Return>", lambda e: do_create())
        self._center_popup(win)
        win.grab_set()

    def _popup_edit_spot(self, idx):
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if not (0 <= idx < len(spots)):
            return
        s = spots[idx]

        win = tk.Toplevel(self.root)
        win.title("Edit Spot")
        win.resizable(False, False)

        ttk.Label(win, text="Spot name:").grid(row=0, column=0, sticky="e", padx=8, pady=(8,4))
        name_var = tk.StringVar(value=s.get("name", "Spot"))
        ent_name = ttk.Entry(win, textvariable=name_var, width=28)
        ent_name.grid(row=0, column=1, sticky="w", padx=8, pady=(8,4))

        ttk.Label(win, text="Threshold (0.10 - 0.98):").grid(row=1, column=0, sticky="e", padx=8, pady=4)
        th_var = tk.StringVar(value=f'{float(s.get("threshold", 0.85)):.2f}')
        ent_th = ttk.Entry(win, textvariable=th_var, width=10)
        ent_th.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        def do_save():
            name = (name_var.get() or "").strip() or "Spot"
            try:
                th = float(th_var.get())
            except Exception:
                th = 0.85
            th = max(0.10, min(0.98, th))
            spots[idx]["name"] = name
            spots[idx]["threshold"] = th
            _write_json(SPOTS_PATH, {"spots": spots})
            self._reload_spots_tree()
            win.destroy()

        ttk.Button(win, text="Save", command=do_save).grid(row=2, column=1, sticky="e", padx=8, pady=(0,8))
        ent_name.focus_set()
        win.bind("<Return>", lambda e: do_save())
        self._center_popup(win)
        win.grab_set()

    def _open_preview(self, idx):
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if not (0 <= idx < len(spots)):
            return
        rel = spots[idx].get("template")
        if not rel:
            return
        path = self._resolve_template_abs(rel)
        if not os.path.exists(path):
            messagebox.showerror("Preview", f"Template not found:\n{path}")
            return
        img = Image.open(path)
        win = tk.Toplevel(self.root)
        win.title(f"Preview: {spots[idx].get('name','Spot')}")
        max_w, max_h = 640, 480
        w, h = img.size
        scale = min(max_w / w, max_h / h, 1.0)
        if scale != 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        tkimg = ImageTk.PhotoImage(img)
        lbl = ttk.Label(win, image=tkimg)
        lbl.image = tkimg
        lbl.pack(padx=10, pady=10)
        self._center_popup(win)
        win.grab_set()

    # ---------- data ops ----------
    def _delete_spot_by_index(self, idx):
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if not (0 <= idx < len(spots)):
            return
        spots.pop(idx)
        _write_json(SPOTS_PATH, {"spots": spots})
        self._reload_spots_tree()

    def _add_spot_record(self, name, threshold=0.85, template_path=None):
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        spots.append({"name": name, "template": template_path, "threshold": float(threshold)})
        _write_json(SPOTS_PATH, {"spots": spots})
        self._reload_spots_tree()

    def apply_clipboard_to_selected(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showwarning("Apply Clipboard", "Select a spot first (click its row).")
            return
        try:
            img = ImageGrab.grabclipboard()
            if img is None:
                raise RuntimeError("Clipboard does not contain an image")
        except Exception as e:
            messagebox.showerror("Apply Clipboard", f"Failed to read image from clipboard: {e}")
            return

        assets_dir = os.path.join(BASE_DIR, "assets", "templates", "spots")
        os.makedirs(assets_dir, exist_ok=True)
        fname = f"{int(time.time()*1000)}.png"
        fpath = os.path.join(assets_dir, fname)
        try:
            img.save(fpath)
        except Exception as e:
            messagebox.showerror("Apply Clipboard", f"Failed to save image: {e}")
            return

        rel = os.path.relpath(fpath, BASE_DIR).replace("\\", "/")
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if 0 <= idx < len(spots):
            spots[idx]["template"] = rel
            _write_json(SPOTS_PATH, {"spots": spots})
            self._reload_spots_tree()

    # ---------------- LOGS TAB ----------------
    def _build_tab_logs(self):
        frame = self.tab_logs
        ttk.Label(frame, text="Logs").grid(row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        self.txt_logs = tk.Text(frame, height=16, width=80, state="disabled")
        self.txt_logs.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

    # ---------------- SAVE CONFIG ----------------
    def save_cfg(self, silent=False):
        self.cfg.setdefault("search", {})
        self.cfg.setdefault("alerts", {})
        self.cfg.setdefault("debug", {})
        self.cfg.setdefault("battle", {})
        self.cfg.setdefault("eligibility", {})

        per = self.cfg["eligibility"].setdefault("per_rarity", {})
        for r in RARITIES:
            per.setdefault(r, {})
            per[r]["enabled"] = bool(self.rarity_vars[r].get())
            per[r]["min_grade"] = self.grade_vars[r].get()

        self.cfg["search"]["search_delay_ms"] = int(self.var_search_delay.get()) * 1000
        self.cfg["search"]["cooldown_seconds"] = int(self.var_cooldown.get())
        self.cfg["search"]["delay_click_ms"]   = int(self.var_delay_click.get())
        self.cfg["alerts"]["play_sound"]       = bool(self.var_sound.get())
        self.cfg["alerts"]["delay_after_alert_seconds"] = int(self.var_alert_delay.get())
        self.cfg["debug"]["show_preview"]      = bool(self.var_show_overlay.get())

        self.cfg["battle"]["capture_hp_percent"] = int(self.var_hp_gate.get())
        self.cfg["battle"]["attempts"]           = int(self.var_attempts.get())
        self.cfg["battle"]["capture_mode"]       = bool(self.var_capture_mode.get())

        def parse_roi(txt, default):
            try:
                parts = [int(p.strip()) for p in txt.split(",")]
                if len(parts) == 4:
                    return parts
            except Exception:
                pass
            return default
        self.cfg["battle"]["hp_bar_roi"] = parse_roi(self.entry_hp_roi.get(), [100, 100, 400, 20])
        self.cfg["battle"]["grade_roi"]  = parse_roi(self.entry_grade_roi.get(), [100, 100, 120, 40])

        try:
            _write_json(CFG_PATH, self.cfg)
        except Exception as e:
            print("Failed to save config:", e)

        if not silent:
            messagebox.showinfo("Saved", "Configuration saved.")

    # ---------------- START/STOP ----------------
    def start_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            messagebox.showwarning("Bot", "Bot already running.")
            return

        spot_name = self.cb_spot.get() if hasattr(self, "cb_spot") else None
        if not spot_name:
            messagebox.showwarning("Start", "Pick a spot in Capture tab (Spot to farm).")
            return

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        try:
            sel_idx = next(i for i, s in enumerate(spots) if s.get("name") == spot_name)
        except StopIteration:
            messagebox.showwarning("Start", "Selected spot not found in Coords.json.")
            return

        if not self._has_template(spots[sel_idx]):
            messagebox.showwarning("Start", "The selected spot has no image yet. Use Apply Clipboard on the Spots tab.")
            return

        cfg = _read_json(CFG_PATH, {})
        cfg.setdefault("run", {})["selected_spot_index"] = int(sel_idx)
        _write_json(CFG_PATH, cfg)

        self.save_cfg(silent=True)

        try:
            self.bot = Bot(CFG_PATH, BASE_DIR, ui_mode_cb=self._bot_mode_event)
        except TypeError as e:
            messagebox.showerror("Start", f"Bot init failed: {e}")
            return

        self.bot_thread = threading.Thread(target=self.run, daemon=True)
        self.bot_thread.start()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._log("[UI] Bot started.")
        self._append_capture_log("INFO", "Bot started")

    def run(self):
        try:
            self.bot.start()
        except Exception as e:
            self._log(f"[Bot] Error: {e}")
            self._append_capture_log("ERROR", f"Bot error: {e}")
        finally:
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self._log("[UI] Bot stopped.")
            self._append_capture_log("INFO", "Bot stopped")

    def stop_bot(self):
        try:
            if self.bot:
                self.bot.stop()
        except Exception:
            pass
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    # -------- Live Capture Log helpers --------
    def _append_capture_log(self, mode: str, line: str):
        def _do():
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.txt_capture_log.insert("end", f"{ts}  {mode:<6}  {line}\n")
            self.txt_capture_log.see("end")
        self.root.after(0, _do)

    def _bot_mode_event(self, mode: str, info: dict):
        run = info.get("run", 0.0)
        tiles = info.get("tiles_count", 0)
        cov = info.get("tiles_coverage", 0.0)
        extra = f"run={run:.0%} tiles={tiles} cov={cov:.1%}"
        rar = info.get("enemy_rarity")
        if rar:
            extra += f"  rarity={rar}"
        self._append_capture_log(mode, extra)

    # ---------------- LOGGING ----------------
    def _tail_log(self):
        pass

    def _log(self, msg):
        try:
            self.txt_logs.configure(state="normal")
            self.txt_logs.insert("end", msg + "\n")
            self.txt_logs.see("end")
            self.txt_logs.configure(state="disabled")
        except Exception:
            print(msg)

    # ---------------- RESTART APP ----------------
    def restart_app(self):
        try:
            self.save_cfg(silent=True)
        except Exception:
            pass
        try:
            self.stop_bot()
        except Exception:
            pass
        try:
            self.root.after(150, self._hard_restart)
        except Exception:
            self._hard_restart()

    def _hard_restart(self):
        try:
            if getattr(sys, 'frozen', False):
                os.execv(sys.executable, [sys.executable] + sys.argv)
                return
            module_name = "src.app"
            args = sys.argv[1:]
            os.execv(sys.executable, [sys.executable, "-m", module_name] + args)
        except Exception:
            try:
                if getattr(sys, 'frozen', False):
                    subprocess.Popen([sys.executable] + sys.argv, close_fds=True)
                else:
                    subprocess.Popen([sys.executable, "-m", "src.app"] + sys.argv[1:], close_fds=True)
            finally:
                os._exit(0)

def launch():
    root = tk.Tk()
    BotUI(root)
    root.mainloop()
