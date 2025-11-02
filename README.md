# Miscrits Auto-Battle Bot

An advanced automation bot for Miscrits (Steam version) with intelligent battle management, auto-capture, and resource farming capabilities.

## Features

### 🎮 Core Features
- **Auto-Resource Farming** - Automatically clicks on resource spots
- **Smart Battle System** - Fully automated battle handling with phase tracking
- **Intelligent Capture Logic** - Captures Miscrits based on rarity and IP rating
- **Cooldown Management** - Handles post-battle cooldowns (24s with trait, 34s without)
- **Non-Intrusive Mode** - DirectInput allows bot to run in background

### ⚔️ Battle System
- **Phase Tracking** - Monitors battle states (turn ready, animations, capture attempts)
- **Skill Management** - Navigates between 3 skill pages (12 total skills)
- **HP Monitoring** - Precise HP tracking for optimal capture timing
- **Capture Detection** - OCR-based capture rate reading with IP/rarity derivation

### 🎯 Capture Configuration
- **Per-Rarity Settings** - Configure capture criteria for each rarity tier
- **IP Rating Filters** - Set minimum IP requirements (S+ to F-)
- **Custom Skills** - Define damage and capture skills per rarity
- **Battle Modes** - Choose between "capture" or "defeat" modes

## Installation

### Prerequisites
- Windows 10/11
- Python 3.10+
- Miscrits (Steam version) at 1152x648 resolution

### Setup
```bash
# Clone repository
git clone https://github.com/yourusername/miscrits-bot
cd miscrits-bot

# Install dependencies
pip install -r requirements.txt

# Optional: Install Tesseract for better OCR
# Download from: https://github.com/tesseract-ocr/tesseract

# Initialize configuration
python -m src.app --init
```

## Quick Start

### 1. Configure Game Settings
- Set Miscrits to **1152x648 resolution** (windowed or borderless)
- Disable Windows display scaling
- Enable cooldown reduction trait if available (-10s cooldown)

### 2. Create Resource Spots
```bash
# Launch GUI
python -m src.app --ui

# Or command line
python -m src.app --create-spot "MySpot"
```

1. Navigate to a resource spot in-game
2. Take screenshot of the resource (Win+Shift+S)
3. In GUI: Spots tab → Add spot → Paste template from clipboard
4. Set threshold (0.80-0.85 recommended)

### 3. Configure Battle Settings
Edit `config.json`:

```json
{
  "battle": {
    "enabled": true,
    "mode": "capture",        // "capture" or "defeat"
    "capture_hp_percent": 10,  // Capture when HP <= this
    "attempts": 3,             // Max capture attempts
    "defeat_skill": "Skill 1", // Strongest skill for defeats
    "use_capture_skill_before": false
  },
  "traits": {
    "cooldown_reduction": true  // Set true if you have -10s trait
  }
}
```

### 4. Set Capture Filters
Configure which Miscrits to capture:

```json
"eligibility": {
  "per_rarity": {
    "Legendary": {
      "enabled": true,
      "min_ip_rating": "A",     // Minimum IP rating
      "damage_skill": "Skill 11", // Weak skill for HP reduction
      "capture_skill": "Skill 12" // Weakest skill
    },
    "Exotic": {
      "enabled": true,
      "min_ip_rating": "S",
      "damage_skill": "Skill 11",
      "capture_skill": "Skill 12"
    }
  }
}
```

### 5. Start Bot
```bash
# GUI mode (recommended)
python -m src.app --ui

# Command line
python -m src.app --start
```

## Controls

### Hotkeys
- **F9** - Pause/Resume bot
- **F10** - Stop bot
- **X** - Record spot position (in create mode)

### Battle Controls
The bot automatically:
1. Detects battle start
2. Reads capture rate to identify Miscrit
3. Checks eligibility based on your filters
4. Either captures (if eligible) or defeats quickly
5. Handles capture dialog (Keep/Release)
6. Clicks Continue after battle
7. Waits for cooldown before next search

## Skill System

Skills are numbered 1-12 based on strength:
- **Skills 1-4**: Page 1 (Strongest)
- **Skills 5-8**: Page 2 (Medium)
- **Skills 9-12**: Page 3 (Weakest)

Navigation uses arrow keys automatically.

## IP Rating & Rarity

### IP Rating Tiers (Strongest to Weakest)
- S+, S, A+, A (Top tier)
- B+, B, C+, C (Mid tier)
- D+, D, F+, F, F- (Low tier)

### Rarity Tiers
- **Legendary** (Yellow) - Rarest
- **Exotic** (Orange)
- **Epic** (Purple)
- **Rare** (Blue)
- **Common** (Gray)

### Capture Rates
Capture rate at 100% HP indicates IP rating and rarity:
- Higher IP = Lower capture rate
- Rarer = Lower capture rate
- Bot automatically derives this from the displayed percentage

## Advanced Configuration

### Input Methods
```json
"input": {
  "backend": "directinput"  // Options: "directinput", "pyautogui", "pydirectinput"
}
```

- **directinput**: Sends inputs directly to window (recommended)
- **pyautogui**: Standard mouse/keyboard (requires focus)
- **pydirectinput**: DirectInput for games (requires focus)

### Debug Options
```json
"debug": {
  "show_preview": true  // Shows overlay with detection boxes
}
```

### Custom ROIs
For different resolutions, adjust ROIs in `battle.py`:
```python
DEFAULT_ROIS = {
  "capture_rate": {"x": 560, "y": 235, "w": 80, "h": 40},
  "enemy_hp_bar": {"x": 755, "y": 205, "w": 70, "h": 8},
  // ... adjust coordinates for your resolution
}
```

## Troubleshooting

### Bot doesn't detect battles
- Ensure game is at 1152x648 resolution
- Check flee button template exists in `assets/templates/battle/`
- Try adjusting battle detection thresholds

### Capture rate not detected
- Install Tesseract OCR for better accuracy
- Ensure capture percentage is clearly visible
- Check ROI alignment for capture_rate region

### Skills not working
- Verify skill page navigation with arrow keys
- Check skill slot ROI coordinates
- Ensure abilities tab is selected (not items)

### Cooldown issues
- Set correct trait status in config
- Default: 24s with trait, 34s without
- Bot includes battle time in cooldown calculation

## Safety Features

- **Phase tracking** prevents action spam
- **Timeout protection** on all wait operations  
- **Error recovery** attempts to complete battles on failure
- **Non-intrusive mode** doesn't interfere with normal PC use

## Contributing

Contributions welcome! Areas for improvement:
- Multi-resolution support
- Additional game features (trading, evolving)
- Machine learning for better detection
- Web dashboard for remote monitoring

## Disclaimer

This bot is for educational purposes only. Use at your own risk. The developers are not responsible for any consequences from using this software. Please respect the game's terms of service.

## License

MIT License - See LICENSE file for details

## Credits

Created by the Miscrits community for personal use with the revived Steam version of Miscrits.