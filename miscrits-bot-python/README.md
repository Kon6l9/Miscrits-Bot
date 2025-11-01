# Miscrits Bot (Python, offline, personal use)

This is a **local, offline** bot skeleton that matches the "Void Loader" style features you described, but simplified and written in Python.
It uses **screen capture + computer vision** + synthetic input. No injection, no network.

> ⚠️ You MUST calibrate Regions of Interest (ROIs) and add tiny template images for your build (buttons, badges, etc.).
> The bot ships with safe defaults and will run, but won't act until you fill those in.

## Features implemented
- Custom spots: record mouse position with hotkey and save to `Coords.json`.
- Search loop with **Cooldown**, **Delay Click**, **Play Sound** (Windows).
- Encounter detection stub (you provide templates).
- Eligibility filter: per-rarity enable + min grade (All/A/A+/S/S+), optional name filter.
- Capture execution flow:
  - HP% gate (Capture %) via HP bar ROI (you set it).
  - Skill(1) chip to threshold, optional Capture Mode → Skill(2) before capturing.
  - Attempts (global tries per battle).
  - If not eligible or attempts exhausted → **defeat** (not flee).
- Level-up bonus allocator stub (plug in your dialog templates).
- Logs to console and file `bot.log`.

## Quick start
1. Install Python 3.10+ on Windows.
2. `pip install -r requirements.txt`
3. Run once to generate files: `python -m src.app --init`
4. Open `config.json`, set your **resolution**, **ROIs**, and **hotkeys**.
5. Place tiny PNG templates under `assets/templates/`:
   - `capture_button.png`, `confirm_button.png`, `skill1.png`, `skill2.png`, `levelup_ok.png`, etc.
6. Start the game in a fixed resolution (e.g., 1920x1080 windowed), **turn off Windows display scaling**.
7. Stand on a resource/spot, press `X` in the bot "Create Spot" mode to record coords.
8. Start farming: `python -m src.app --start`

## CLI
```
python -m src.app --init                 # create default config/coords
python -m src.app --create-spot MyRock   # records mouse pos on hotkey (X) and saves
python -m src.app --start                # runs the bot (press F9 to pause/resume, F10 to stop)
```

## Files
- `config.json` — policies, ROIs, timings, keys.
- `Coords.json` — your saved custom spots.
- `assets/templates/*.png` — small UI anchors (you add).
- `assets/glyphs/*.png` — S, A, B, plus signs (optional, you add).
- `assets/rarity/*.png` — tiny rarity icons or swatches (optional, you add).

## Notes
- If the game ignores `pyautogui`, switch to `pydirectinput` in `input_ctl.py` (toggle in config).
- Sound uses `winsound` (Windows). If it fails, the bot will just print.
- Tesseract is optional (only needed if you want OCR for names). Install it from https://github.com/tesseract-ocr/tesseract.
- Everything runs locally. No data leaves your machine.
