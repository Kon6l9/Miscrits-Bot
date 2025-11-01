import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, os, time
from PIL import ImageGrab, Image, ImageTk
from .capture_loop import Bot

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CFG_PATH = os.path.join(BASE_DIR, "config.json")
SPOTS_PATH = os.path.join(BASE_DIR, "Coords.json")

RARITIES = ["Common","Rare","Epic","Exotic","Legendary"]
IP_RATINGS = ["S+", "S", "A+", "A", "B+", "B", "C+", "C", "D", "D+", "F", "F+", "B+ and Below"]
SKILLS = [f"Skill {i}" for i in range(1, 13)]  # Skill 1 (strongest) to Skill 12 (weakest)

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
        self.root.title("Miscrits Bot - Enhanced Edition v2.0")
        self.root.geometry("1000x800")
        self.bot_thread = None
        self.bot = None
        self.stats = {"encounters": 0, "captures": 0, "skipped": 0, "runtime": 0}
        self.start_time = None

        self.cfg = _read_json(CFG_PATH, {})
        self._ensure_battle_config()

        # Basic variables
        self.var_search_delay = tk.IntVar(value=self._get_search_delay_seconds())
        self.var_cooldown = tk.IntVar(value=int(self.cfg.get("search", {}).get("cooldown_seconds", 25)))
        self.var_delay_click = tk.IntVar(value=int(self.cfg.get("search", {}).get("delay_click_ms", 10)))
        self.var_sound = tk.BooleanVar(value=bool(self.cfg.get("alerts", {}).get("play_sound", True)))
        self.var_alert_delay = tk.IntVar(value=int(self.cfg.get("alerts", {}).get("delay_after_alert_seconds", 0)))
        self.var_show_overlay = tk.BooleanVar(value=bool(self.cfg.get("debug", {}).get("show_preview", False)))
        
        # Global capture variables
        self.var_hp_gate = tk.IntVar(value=self.cfg.get("battle", {}).get("capture_hp_percent", 45))
        self.var_attempts = tk.IntVar(value=self.cfg.get("battle", {}).get("attempts", 3))
        
        # Skill configuration variables
        bcfg = self.cfg.get("battle", {})
        self.var_capture_skill = tk.StringVar(value=bcfg.get("capture_skill", "Skill 12"))
        self.var_defeat_skill = tk.StringVar(value=bcfg.get("defeat_skill", "Skill 1"))
        self.var_quick_defeat = tk.BooleanVar(value=bcfg.get("quick_defeat", True))
        
        # Rarity filter variables (enabled/disabled + min IP rating + specific skills)
        self.rarity_enabled = {}
        self.rarity_min_ip = {}
        self.rarity_damage_skill = {}
        self.rarity_capture_skill = {}
        
        for rarity in RARITIES:
            rarity_cfg = self.cfg.get("eligibility", {}).get("per_rarity", {}).get(rarity, {})
            self.rarity_enabled[rarity] = tk.BooleanVar(
                value=rarity_cfg.get("enabled", rarity in ["Legendary", "Exotic"])
            )
            self.rarity_min_ip[rarity] = tk.StringVar(
                value=rarity_cfg.get("min_ip_rating", "A")
            )
            self.rarity_damage_skill[rarity] = tk.StringVar(
                value=rarity_cfg.get("damage_skill", "Skill 11")
            )
            self.rarity_capture_skill[rarity] = tk.StringVar(
                value=rarity_cfg.get("capture_skill", "Skill 12")
            )
        
        # Advanced settings
        self.var_use_directinput = tk.BooleanVar(
            value=self.cfg.get("input", {}).get("backend", "directinput") == "directinput"
        )

        self._build_ui()
        self._update_stats_display()

    def _ensure_battle_config(self):
        """Ensure battle configuration has all required fields"""
        bcfg = self.cfg.setdefault("battle", {})
        bcfg.setdefault("capture_skill", "Skill 12")
        bcfg.setdefault("defeat_skill", "Skill 1")
        bcfg.setdefault("quick_defeat", True)
        bcfg.setdefault("capture_hp_percent", 45)
        bcfg.setdefault("attempts", 3)
        
        # Ensure per-rarity configuration
        elig = self.cfg.setdefault("eligibility", {})
        per_rarity = elig.setdefault("per_rarity", {})
        
        for rarity in RARITIES:
            per_rarity.setdefault(rarity, {})
            per_rarity[rarity].setdefault("enabled", rarity in ["Legendary", "Exotic"])
            per_rarity[rarity].setdefault("min_ip_rating", "A")
            per_rarity[rarity].setdefault("damage_skill", "Skill 11")
            per_rarity[rarity].setdefault("capture_skill", "Skill 12")

    def _get_search_delay_seconds(self):
        sd_ms = int(self.cfg.get("search", {}).get("search_delay_ms", 0) or 10000)
        return max(1, round(sd_ms/1000))

    def _build_ui(self):
        # Status bar at top
        self._build_status_bar()
        
        # Main content with tabs
        nb = ttk.Notebook(self.root)
        self.tab_dashboard = ttk.Frame(nb)
        self.tab_spots = ttk.Frame(nb)
        self.tab_battle = ttk.Frame(nb)
        self.tab_eligibility = ttk.Frame(nb)
        self.tab_advanced = ttk.Frame(nb)
        self.tab_logs = ttk.Frame(nb)

        nb.add(self.tab_dashboard, text="📊 Dashboard")
        nb.add(self.tab_spots, text="📍 Spots")
        nb.add(self.tab_battle, text="⚔️ Battle & Skills")
        nb.add(self.tab_eligibility, text="🎯 Rarity Filters")
        nb.add(self.tab_advanced, text="⚙️ Advanced")
        nb.add(self.tab_logs, text="📋 Logs")
        nb.pack(fill="both", expand=True, padx=5, pady=5)

        self._build_tab_dashboard()
        self._build_tab_spots()
        self._build_tab_battle()
        self._build_tab_eligibility()
        self._build_tab_advanced()
        self._build_tab_logs()

        # Footer controls
        self._build_footer()

    def _build_status_bar(self):
        status_frame = ttk.Frame(self.root, relief="sunken", borderwidth=1)
        status_frame.pack(fill="x", side="top")
        
        self.lbl_status = ttk.Label(status_frame, text="● Idle", foreground="gray")
        self.lbl_status.pack(side="left", padx=10, pady=2)
        
        self.lbl_runtime = ttk.Label(status_frame, text="Runtime: 00:00:00")
        self.lbl_runtime.pack(side="right", padx=10, pady=2)

    def _build_tab_dashboard(self):
        frame = self.tab_dashboard
        
        # Quick Start Section
        quick_frame = ttk.LabelFrame(frame, text="⚡ Quick Start", padding=10)
        quick_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(quick_frame, text="Select Spot:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.var_spot_choice = tk.StringVar()
        self._reload_spot_choices()
        self.cb_spot = ttk.Combobox(quick_frame, textvariable=self.var_spot_choice, 
                                     values=self.spot_choices, width=30, state="readonly")
        self.cb_spot.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        if self.spot_choices:
            self.cb_spot.current(0)
        
        ttk.Button(quick_frame, text="🔄", command=self._refresh_dashboard_spots, width=3)\
            .grid(row=0, column=2, sticky="w", padx=2, pady=5)
        
        ttk.Label(quick_frame, text="Click Interval:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        interval_frame = ttk.Frame(quick_frame)
        interval_frame.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        ttk.Spinbox(interval_frame, from_=1, to=120, textvariable=self.var_search_delay, width=8)\
            .pack(side="left")
        ttk.Label(interval_frame, text="seconds").pack(side="left", padx=5)
        
        ttk.Checkbutton(quick_frame, text="Show overlay", 
                       variable=self.var_show_overlay).grid(row=2, column=0, columnspan=3, 
                                                            sticky="w", padx=5, pady=5)
        
        # Statistics Section
        stats_frame = ttk.LabelFrame(frame, text="📈 Session Statistics", padding=10)
        stats_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.lbl_encounters = ttk.Label(stats_frame, text="Encounters: 0", font=("Arial", 12))
        self.lbl_encounters.pack(anchor="w", pady=2)
        
        self.lbl_captures = ttk.Label(stats_frame, text="Captures: 0", font=("Arial", 12))
        self.lbl_captures.pack(anchor="w", pady=2)
        
        self.lbl_skipped = ttk.Label(stats_frame, text="Skipped: 0", font=("Arial", 12))
        self.lbl_skipped.pack(anchor="w", pady=2)
        
        self.lbl_success_rate = ttk.Label(stats_frame, text="Capture Rate: 0%", font=("Arial", 12))
        self.lbl_success_rate.pack(anchor="w", pady=2)
        
        ttk.Button(stats_frame, text="Reset Statistics", command=self._reset_stats)\
            .pack(anchor="w", pady=10)

    def _build_tab_spots(self):
        frame = self.tab_spots
        
        # Left side - list
        left_frame = ttk.Frame(frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        ttk.Label(left_frame, text="Saved Spots:", font=("Arial", 10, "bold")).pack(anchor="w", pady=5)
        
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.listbox_spots = tk.Listbox(list_frame, width=50, height=15, yscrollcommand=scrollbar.set)
        self.listbox_spots.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox_spots.yview)
        self.listbox_spots.bind("<<ListboxSelect>>", self._on_spot_select)
        
        self._reload_spots_listbox()
        
        # Right side - controls
        right_frame = ttk.Frame(frame)
        right_frame.pack(side="right", fill="y", padx=5, pady=5)
        
        ttk.Label(right_frame, text="Spot Management", font=("Arial", 10, "bold")).pack(pady=5)
        
        ttk.Label(right_frame, text="Spot Name:").pack(anchor="w", pady=(10,2))
        self.entry_spot_name = ttk.Entry(right_frame, width=30)
        self.entry_spot_name.insert(0, "NewSpot")
        self.entry_spot_name.pack(anchor="w", pady=2)
        
        ttk.Button(right_frame, text="➕ Add New Spot", command=self.add_spot, width=25)\
            .pack(anchor="w", pady=5)
        
        ttk.Separator(right_frame, orient="horizontal").pack(fill="x", pady=10)
        
        ttk.Label(right_frame, text="Template", font=("Arial", 9, "bold")).pack(pady=5)
        
        ttk.Button(right_frame, text="📋 Paste from Clipboard", command=self.import_template_from_clipboard, width=25)\
            .pack(anchor="w", pady=2)
        
        ttk.Button(right_frame, text="📁 Load from File", command=self.import_template_from_file, width=25)\
            .pack(anchor="w", pady=2)
        
        ttk.Label(right_frame, text="Match Threshold:").pack(anchor="w", pady=(10,2))
        threshold_frame = ttk.Frame(right_frame)
        threshold_frame.pack(anchor="w")
        self.entry_threshold = ttk.Entry(threshold_frame, width=8)
        self.entry_threshold.insert(0, "0.82")
        self.entry_threshold.pack(side="left")
        ttk.Label(threshold_frame, text="(0.70-0.98)").pack(side="left", padx=5)
        
        ttk.Button(right_frame, text="✏️ Update", command=self.edit_threshold_for_selected, width=25)\
            .pack(anchor="w", pady=5)
        
        ttk.Separator(right_frame, orient="horizontal").pack(fill="x", pady=10)
        
        ttk.Label(right_frame, text="Preview:", font=("Arial", 9, "bold")).pack(pady=5)
        self.preview_label = ttk.Label(right_frame, text="No template", relief="solid", borderwidth=1)
        self.preview_label.pack(pady=5)
        
        ttk.Button(right_frame, text="🗑️ Delete", command=self.delete_spot, width=25)\
            .pack(anchor="w", pady=10)

    def _build_tab_battle(self):
        frame = self.tab_battle
        
        # Create scrollable canvas
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # === GLOBAL CAPTURE SETTINGS ===
        global_frame = ttk.LabelFrame(scrollable_frame, text="🎯 Global Capture Settings", padding=10)
        global_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(global_frame, text="Capture HP Threshold:", font=("Arial", 9, "bold"))\
            .grid(row=0, column=0, sticky="e", padx=5, pady=5)
        hp_frame = ttk.Frame(global_frame)
        hp_frame.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Spinbox(hp_frame, from_=1, to=99, textvariable=self.var_hp_gate, width=8).pack(side="left")
        ttk.Label(hp_frame, text="% (Capture when enemy HP ≤ this)").pack(side="left", padx=5)
        
        ttk.Label(global_frame, text="Max Capture Attempts:", font=("Arial", 9, "bold"))\
            .grid(row=1, column=0, sticky="e", padx=5, pady=5)
        ttk.Spinbox(global_frame, from_=1, to=10, textvariable=self.var_attempts, width=8)\
            .grid(row=1, column=1, sticky="w", padx=5, pady=5)
        
        ttk.Label(global_frame, text="Default Capture Skill:", font=("Arial", 9, "bold"))\
            .grid(row=2, column=0, sticky="e", padx=5, pady=5)
        capture_skill_frame = ttk.Frame(global_frame)
        capture_skill_frame.grid(row=2, column=1, sticky="w", padx=5, pady=5)
        ttk.Combobox(capture_skill_frame, textvariable=self.var_capture_skill, 
                     values=SKILLS, width=12, state="readonly").pack(side="left")
        ttk.Label(capture_skill_frame, text="(Skill 12 = weakest damage)").pack(side="left", padx=5)
        
        # === NON-TARGET DEFEAT SETTINGS ===
        defeat_frame = ttk.LabelFrame(scrollable_frame, text="⚔️ Non-Target Defeat Strategy", padding=10)
        defeat_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(defeat_frame, text="Defeat Skill:", font=("Arial", 9, "bold"))\
            .grid(row=0, column=0, sticky="e", padx=5, pady=5)
        defeat_skill_frame = ttk.Frame(defeat_frame)
        defeat_skill_frame.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Combobox(defeat_skill_frame, textvariable=self.var_defeat_skill, 
                     values=SKILLS, width=12, state="readonly").pack(side="left")
        ttk.Label(defeat_skill_frame, text="(Skill 1 = strongest)").pack(side="left", padx=5)
        
        ttk.Checkbutton(defeat_frame, text="Quick defeat (spam skill without checking)", 
                       variable=self.var_quick_defeat)\
            .grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=5)
        
        # === SKILL REFERENCE ===
        ref_frame = ttk.LabelFrame(scrollable_frame, text="📚 Skill Reference", padding=10)
        ref_frame.pack(fill="x", padx=10, pady=10)
        
        ref_text = tk.Text(ref_frame, height=8, width=70, wrap="word", font=("Courier", 9))
        ref_text.pack(fill="x", padx=5, pady=5)
        ref_text.insert("1.0", """
Skill Configuration Guide:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Skills are numbered 1-12 based on in-game position
• Skill 1 = STRONGEST (rightmost in game, after scrolling)
• Skill 12 = WEAKEST (leftmost in game)
• For CAPTURE: Use weakest skill (Skill 11 or 12) to chip HP safely
• For DEFEAT: Use strongest skill (Skill 1 or 2) to end battle quickly
• Navigate skills: Bot will automatically scroll left/right as needed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """.strip())
        ref_text.config(state="disabled")
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_tab_eligibility(self):
        frame = self.tab_eligibility
        
        # Create scrollable canvas
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Header
        header_frame = ttk.Frame(scrollable_frame)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(header_frame, text="🎯 Rarity & IP Rating Filters", 
                 font=("Arial", 12, "bold")).pack(side="left")
        ttk.Label(header_frame, text="Configure which Miscrits to capture based on rarity and IP rating", 
                 font=("Arial", 9)).pack(side="left", padx=20)
        
        # Rarity configurations
        for rarity in RARITIES:
            self._build_rarity_config(scrollable_frame, rarity)
        
        # IP Rating Guide
        guide_frame = ttk.LabelFrame(scrollable_frame, text="📊 IP Rating Guide", padding=10)
        guide_frame.pack(fill="x", padx=10, pady=10)
        
        guide_text = tk.Text(guide_frame, height=4, width=70, wrap="word", font=("Courier", 9))
        guide_text.pack(fill="x", padx=5, pady=5)
        guide_text.insert("1.0", """
IP Ratings (Strongest to Weakest): S+ > S > A+ > A > B+ > B > C+ > C > D+ > D > F+ > F
• Select minimum IP rating for each rarity
• "B+ and Below" captures B+, B, C+, C, D+, D, F+, F
• Bot will only capture Miscrits meeting BOTH rarity enabled AND minimum IP rating
        """.strip())
        guide_text.config(state="disabled")
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_rarity_config(self, parent, rarity):
        """Build configuration section for a single rarity"""
        # Color scheme
        colors = {
            'Common': ('#E5E7EB', '#6B7280'),
            'Rare': ('#DBEAFE', '#2563EB'),
            'Epic': ('#EDE9FE', '#7C3AED'),
            'Exotic': ('#FED7AA', '#EA580C'),
            'Legendary': ('#FEF3C7', '#D97706')
        }
        bg_color, text_color = colors.get(rarity, ('#F3F4F6', '#374151'))
        
        frame = ttk.LabelFrame(parent, text=f"  {rarity}  ", padding=10)
        frame.pack(fill="x", padx=10, pady=5)
        
        # Configure frame background
        style = ttk.Style()
        style.configure(f"{rarity}.TLabelframe", background=bg_color)
        style.configure(f"{rarity}.TLabelframe.Label", background=bg_color, foreground=text_color, font=("Arial", 10, "bold"))
        frame.configure(style=f"{rarity}.TLabelframe")
        
        # Enable checkbox
        check_frame = ttk.Frame(frame)
        check_frame.grid(row=0, column=0, columnspan=4, sticky="w", pady=5)
        
        ttk.Checkbutton(check_frame, text=f"Enable {rarity} capture", 
                       variable=self.rarity_enabled[rarity],
                       command=lambda r=rarity: self._toggle_rarity_config(r))\
            .pack(side="left")
        
        # Configuration options (shown only when enabled)
        config_frame = ttk.Frame(frame)
        config_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=5)
        
        ttk.Label(config_frame, text="Min IP Rating:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        ttk.Combobox(config_frame, textvariable=self.rarity_min_ip[rarity], 
                     values=IP_RATINGS, width=15, state="readonly")\
            .grid(row=0, column=1, sticky="w", padx=5, pady=3)
        
        ttk.Label(config_frame, text="Damage Skill (chip HP):").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        ttk.Combobox(config_frame, textvariable=self.rarity_damage_skill[rarity], 
                     values=SKILLS, width=15, state="readonly")\
            .grid(row=1, column=1, sticky="w", padx=5, pady=3)
        
        ttk.Label(config_frame, text="Capture Skill:").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        ttk.Combobox(config_frame, textvariable=self.rarity_capture_skill[rarity], 
                     values=SKILLS, width=15, state="readonly")\
            .grid(row=2, column=1, sticky="w", padx=5, pady=3)
        
        # Store reference to config frame for toggling
        setattr(self, f"_config_frame_{rarity}", config_frame)
        
        # Initial state
        self._toggle_rarity_config(rarity)

    def _toggle_rarity_config(self, rarity):
        """Show/hide rarity configuration based on enabled state"""
        config_frame = getattr(self, f"_config_frame_{rarity}", None)
        if config_frame:
            if self.rarity_enabled[rarity].get():
                for child in config_frame.winfo_children():
                    child.configure(state="normal")
            else:
                for child in config_frame.winfo_children():
                    if isinstance(child, (ttk.Combobox, ttk.Entry)):
                        child.configure(state="disabled")

    def _build_tab_advanced(self):
        frame = self.tab_advanced
        
        # Timing Settings
        timing_frame = ttk.LabelFrame(frame, text="⏱️ Timing & Delays", padding=10)
        timing_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(timing_frame, text="Cooldown between battles:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        cd_frame = ttk.Frame(timing_frame)
        cd_frame.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Spinbox(cd_frame, from_=0, to=300, textvariable=self.var_cooldown, width=8).pack(side="left")
        ttk.Label(cd_frame, text="seconds").pack(side="left", padx=5)
        
        ttk.Label(timing_frame, text="Click delay:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        delay_frame = ttk.Frame(timing_frame)
        delay_frame.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        ttk.Spinbox(delay_frame, from_=0, to=500, textvariable=self.var_delay_click, width=8).pack(side="left")
        ttk.Label(delay_frame, text="ms").pack(side="left", padx=5)
        
        # Alert Settings
        alert_frame = ttk.LabelFrame(frame, text="🔔 Alert Settings", padding=10)
        alert_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Checkbutton(alert_frame, text="Play sound on eligible Miscrit", 
                       variable=self.var_sound).pack(anchor="w", pady=5)
        
        ttk.Label(alert_frame, text="Delay after alert:").pack(anchor="w", pady=2)
        alert_delay_frame = ttk.Frame(alert_frame)
        alert_delay_frame.pack(anchor="w")
        ttk.Spinbox(alert_delay_frame, from_=0, to=30, textvariable=self.var_alert_delay, width=8).pack(side="left")
        ttk.Label(alert_delay_frame, text="seconds").pack(side="left", padx=5)
        
        # Input Method
        input_frame = ttk.LabelFrame(frame, text="🖱️ Input Method", padding=10)
        input_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Checkbutton(input_frame, text="Use DirectInput (recommended for games)", 
                       variable=self.var_use_directinput).pack(anchor="w", pady=5)
        
        ttk.Label(input_frame, text="DirectInput sends inputs directly to game window,\nallowing you to use mouse/keyboard normally.", 
                 font=("Arial", 8), foreground="gray").pack(anchor="w", pady=5)

    def _build_tab_logs(self):
        frame = self.tab_logs
        
        # Toolbar
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(toolbar, text="Clear", command=self._clear_logs).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Export", command=self._export_logs).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Refresh", command=self._refresh_logs).pack(side="left", padx=2)
        
        # Log display
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.txt_logs = tk.Text(log_frame, width=100, height=20, yscrollcommand=scrollbar.set,
                               font=("Consolas", 9))
        self.txt_logs.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.txt_logs.yview)
        
        self.txt_logs.insert("end", "Logs will appear here when bot is running.\n")
        self.txt_logs.insert("end", "=" * 80 + "\n\n")

    def _build_footer(self):
        footer = ttk.Frame(self.root, relief="raised", borderwidth=1)
        footer.pack(fill="x", side="bottom")
        
        self.btn_start = ttk.Button(footer, text="▶ Start Bot", command=self.start_bot, width=15)
        self.btn_stop = ttk.Button(footer, text="⏹ Stop Bot", command=self.stop_bot, state="disabled", width=15)
        self.btn_save = ttk.Button(footer, text="💾 Save Config", command=self.save_cfg, width=15)
        
        self.btn_start.pack(side="left", padx=10, pady=8)
        self.btn_stop.pack(side="left", padx=10, pady=8)
        self.btn_save.pack(side="right", padx=10, pady=8)

    # ============ Helper Methods ============
    
    def _reload_spots_listbox(self):
        self.listbox_spots.delete(0, "end")
        data = _read_json(SPOTS_PATH, {"spots": []})
        for s in data.get("spots", []):
            name = s.get("name","Spot")
            tpl = s.get("template","")
            thr = s.get("threshold", 0.82)
            status = "✓" if tpl else "✗"
            self.listbox_spots.insert("end", f"{status} {name}  —  thr={thr:.2f}")

    def _reload_spot_choices(self):
        """Load spots that have templates for dashboard dropdown"""
        self.spot_choices = []
        data = _read_json(SPOTS_PATH, {"spots": []})
        for s in data.get("spots", []):
            name = s.get("name","Spot")
            tpl = s.get("template","")
            if tpl:
                self.spot_choices.append(name)

    def _on_spot_select(self, event):
        """Show template preview when spot is selected"""
        idxs = self.listbox_spots.curselection()
        if not idxs:
            return
        sel = idxs[0]
        
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel >= len(spots):
            return
        
        spot = spots[sel]
        tpl_path = spot.get("template", "")
        
        if tpl_path:
            full_path = os.path.join(BASE_DIR, tpl_path)
            if os.path.exists(full_path):
                try:
                    img = Image.open(full_path)
                    img.thumbnail((150, 150))
                    photo = ImageTk.PhotoImage(img)
                    self.preview_label.config(image=photo, text="")
                    self.preview_label.image = photo
                except Exception:
                    self.preview_label.config(text="Preview\nfailed", image="")
            else:
                self.preview_label.config(text="File not\nfound", image="")
        else:
            self.preview_label.config(text="No template", image="")
        
        self.entry_threshold.delete(0, "end")
        self.entry_threshold.insert(0, str(spot.get("threshold", 0.82)))

    def _update_stats_display(self):
        """Update statistics labels"""
        self.lbl_encounters.config(text=f"Encounters: {self.stats['encounters']}")
        self.lbl_captures.config(text=f"Captures: {self.stats['captures']}")
        self.lbl_skipped.config(text=f"Skipped: {self.stats['skipped']}")
        
        if self.stats['encounters'] > 0:
            rate = (self.stats['captures'] / self.stats['encounters']) * 100
            self.lbl_success_rate.config(text=f"Capture Rate: {rate:.1f}%")
        else:
            self.lbl_success_rate.config(text="Capture Rate: 0%")

    def _reset_stats(self):
        self.stats = {"encounters": 0, "captures": 0, "skipped": 0, "runtime": 0}
        self._update_stats_display()
        messagebox.showinfo("Reset", "Session statistics reset.")

    def _update_runtime(self):
        """Update runtime display"""
        if self.start_time:
            elapsed = int(time.time() - self.start_time)
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            self.lbl_runtime.config(text=f"Runtime: {hours:02d}:{minutes:02d}:{seconds:02d}")
            self.root.after(1000, self._update_runtime)

    def _refresh_dashboard_spots(self):
        """Refresh spot dropdown in dashboard"""
        self._reload_spot_choices()
        self.cb_spot['values'] = self.spot_choices
        if self.spot_choices:
            current = self.var_spot_choice.get()
            if current in self.spot_choices:
                self.cb_spot.set(current)
            else:
                self.cb_spot.current(0)
        else:
            self.cb_spot.set('')
        messagebox.showinfo("Refreshed", f"Found {len(self.spot_choices)} spot(s) with templates.")

    def _clear_logs(self):
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.insert("end", "Logs cleared.\n" + "=" * 80 + "\n\n")

    def _export_logs(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.txt_logs.get("1.0", "end"))
            messagebox.showinfo("Exported", f"Logs exported to:\n{filepath}")

    def _refresh_logs(self):
        self._tail_log()

    # ============ Configuration Methods ============

    def save_cfg(self, silent: bool = False):
        # Battle settings
        bcfg = self.cfg.setdefault("battle", {})
        bcfg["capture_hp_percent"] = int(self.var_hp_gate.get())
        bcfg["attempts"] = int(self.var_attempts.get())
        bcfg["capture_skill"] = self.var_capture_skill.get()
        bcfg["defeat_skill"] = self.var_defeat_skill.get()
        bcfg["quick_defeat"] = bool(self.var_quick_defeat.get())
        
        # Eligibility - per rarity
        per_rarity = self.cfg.setdefault("eligibility", {}).setdefault("per_rarity", {})
        for rarity in RARITIES:
            per_rarity.setdefault(rarity, {})
            per_rarity[rarity]["enabled"] = bool(self.rarity_enabled[rarity].get())
            per_rarity[rarity]["min_ip_rating"] = self.rarity_min_ip[rarity].get()
            per_rarity[rarity]["damage_skill"] = self.rarity_damage_skill[rarity].get()
            per_rarity[rarity]["capture_skill"] = self.rarity_capture_skill[rarity].get()

        # Timing/alerts
        self.cfg.setdefault("search", {})["cooldown_seconds"] = int(self.var_cooldown.get())
        self.cfg["search"]["delay_click_ms"] = int(self.var_delay_click.get())
        self.cfg["search"]["search_delay_ms"] = int(self.var_search_delay.get()) * 1000
        self.cfg.setdefault("alerts", {})["play_sound"] = bool(self.var_sound.get())
        self.cfg["alerts"]["delay_after_alert_seconds"] = int(self.var_alert_delay.get())

        # Overlay
        self.cfg.setdefault("debug", {})["show_preview"] = bool(self.var_show_overlay.get())

        # Input method
        backend = "directinput" if self.var_use_directinput.get() else "pyautogui"
        self.cfg.setdefault("input", {})["backend"] = backend

        _write_json(CFG_PATH, self.cfg)
        if not silent:
            messagebox.showinfo("Saved", "Configuration saved successfully!")

    # ============ Spot Management Methods ============

    def add_spot(self):
        name = self.entry_spot_name.get().strip() or "Spot"
        data = _read_json(SPOTS_PATH, {"spots": []})
        
        existing_names = [s.get("name", "") for s in data.get("spots", [])]
        if name in existing_names:
            messagebox.showwarning("Duplicate", f"Spot '{name}' already exists.")
            return
        
        data.setdefault("spots", []).append({
            "name": name,
            "template": "",
            "threshold": 0.82,
            "roi": [0,0,0,0]
        })
        _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        
        self.listbox_spots.selection_clear(0, "end")
        self.listbox_spots.selection_set("end")
        self.listbox_spots.see("end")
        
        messagebox.showinfo("Added", f"Added '{name}'.\nSelect it and add a template.")

    def _clipboard_to_template_file(self):
        """Save clipboard image to project folder and return relative path"""
        img = ImageGrab.grabclipboard()
        if img is None:
            return None, "Clipboard doesn't contain an image.\n\nUse Win+Shift+S to capture."

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
            messagebox.showerror("No Selection", "Select a spot first.")
            return
        sel = idxs[0]

        rel, err = self._clipboard_to_template_file()
        if err:
            messagebox.showerror("Error", err)
            return

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel >= len(spots):
            return

        s = spots[sel]
        s["template"] = rel

        try:
            th = float(self.entry_threshold.get())
            if 0.5 <= th <= 0.99:
                s["threshold"] = th
        except Exception:
            pass

        _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        self._on_spot_select(None)
        
        messagebox.showinfo("Saved", f"Template saved for '{s.get('name')}'.\nRefresh Dashboard to use it.")

    def import_template_from_file(self):
        idxs = self.listbox_spots.curselection()
        if not idxs:
            messagebox.showerror("No Selection", "Select a spot first.")
            return
        sel = idxs[0]

        filepath = filedialog.askopenfilename(
            title="Select Template Image",
            filetypes=[("PNG files", "*.png"), ("All images", "*.png *.jpg *.jpeg")]
        )
        
        if not filepath:
            return

        try:
            img = Image.open(filepath)
            tpl_dir = os.path.join(BASE_DIR, "assets", "templates", "spots")
            os.makedirs(tpl_dir, exist_ok=True)
            
            ts = int(time.time())
            tpl_path = os.path.join(tpl_dir, f"spot_{ts}.png")
            img.save(tpl_path)
            rel = os.path.relpath(tpl_path, BASE_DIR).replace("\\", "/")
            
            data = _read_json(SPOTS_PATH, {"spots": []})
            spots = data.get("spots", [])
            if sel >= len(spots):
                return

            s = spots[sel]
            s["template"] = rel
            
            try:
                th = float(self.entry_threshold.get())
                if 0.5 <= th <= 0.99:
                    s["threshold"] = th
            except Exception:
                pass

            _write_json(SPOTS_PATH, data)
            self._reload_spots_listbox()
            self._on_spot_select(None)
            
            messagebox.showinfo("Saved", f"Template imported for '{s.get('name')}'.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import:\n{str(e)}")

    def edit_threshold_for_selected(self):
        idxs = self.listbox_spots.curselection()
        if not idxs:
            messagebox.showerror("No Selection", "Select a spot first.")
            return
        sel = idxs[0]
        
        try:
            th = float(self.entry_threshold.get())
        except Exception:
            messagebox.showerror("Invalid", "Enter valid number (e.g., 0.82)")
            return
        
        if not (0.5 <= th <= 0.99):
            messagebox.showerror("Invalid", "Must be between 0.50 and 0.99")
            return

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel >= len(spots):
            return

        spots[sel]["threshold"] = th
        _write_json(SPOTS_PATH, data)
        self._reload_spots_listbox()
        messagebox.showinfo("Updated", f"Threshold updated to {th:.2f}")

    def delete_spot(self):
        idxs = self.listbox_spots.curselection()
        if not idxs:
            messagebox.showwarning("No Selection", "Select a spot to delete.")
            return
        sel = idxs[0]

        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        if sel < len(spots):
            spot_name = spots[sel].get("name", "Spot")
            if messagebox.askyesno("Confirm", f"Delete '{spot_name}'?"):
                spots.pop(sel)
                data["spots"] = spots
                _write_json(SPOTS_PATH, data)
                self._reload_spots_listbox()
                self.preview_label.config(text="No template", image="")
                messagebox.showinfo("Deleted", f"Deleted '{spot_name}'")

    # ============ Bot Control Methods ============

    def start_bot(self):
        if self.bot_thread and self.bot_thread.is_alive():
            messagebox.showwarning("Running", "Bot is already running.")
            return

        if not hasattr(self, "cb_spot") or not self.cb_spot.get():
            messagebox.showerror("No Spot", "Select a spot from Dashboard.")
            return

        self.save_cfg(silent=True)

        chosen_name = self.cb_spot.get()
        data = _read_json(SPOTS_PATH, {"spots": []})
        spots = data.get("spots", [])
        sel_idx = 0
        found = False
        for i, s in enumerate(spots):
            if s.get("name","Spot") == chosen_name:
                sel_idx = i
                found = True
                break

        if not found:
            messagebox.showerror("Invalid", "Selected spot not found.")
            return

        if not spots[sel_idx].get("template"):
            messagebox.showerror("No Template", f"'{chosen_name}' has no template.")
            return

        cfg = _read_json(CFG_PATH, {})
        cfg.setdefault("run", {})["selected_spot_index"] = sel_idx
        _write_json(CFG_PATH, cfg)

        self._log("=" * 80)
        self._log(f"Starting bot with spot: {chosen_name}")
        self._log("Initializing...")
        
        try:
            self.bot = Bot(CFG_PATH, BASE_DIR)
        except Exception as e:
            self._log(f"ERROR: {str(e)}")
            messagebox.showerror("Error", f"Failed to start:\n{str(e)}")
            return

        def run():
            try:
                self.bot.start()
            except Exception as e:
                self._log(f"ERROR: {str(e)}")
                self.root.after(0, lambda: messagebox.showerror("Bot Error", str(e)))
            finally:
                self._log("Bot stopped.")
                self._log("=" * 80 + "\n")
                self.root.after(0, self._on_bot_stopped)

        self.bot_thread = threading.Thread(target=run, daemon=True)
        self.bot_thread.start()
        
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="● Running", foreground="green")
        
        self.start_time = time.time()
        self._update_runtime()
        self.root.after(1000, self._tail_log)

    def stop_bot(self):
        if self.bot:
            self._log("Stop requested...")
            self.bot.stop()
        self._on_bot_stopped()

    def _on_bot_stopped(self):
        """Called when bot stops"""
        self.btn_stop.config(state="disabled")
        self.btn_start.config(state="normal")
        self.lbl_status.config(text="● Idle", foreground="gray")
        self.start_time = None

    def _tail_log(self):
        """Update log display"""
        log_path = os.path.join(BASE_DIR, "bot.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-30:]
                self.txt_logs.delete("1.0", "end")
                for ln in lines:
                    self.txt_logs.insert("end", ln)
                self.txt_logs.see("end")
            except Exception:
                pass
        
        if self.bot_thread and self.bot_thread.is_alive():
            self.root.after(1000, self._tail_log)

    def _log(self, msg: str):
        """Append to log display"""
        try:
            self.txt_logs.insert("end", msg + "\n")
            self.txt_logs.see("end")
        except Exception:
            pass


def launch():
    """Launch the enhanced UI"""
    root = tk.Tk()
    app = BotUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch()