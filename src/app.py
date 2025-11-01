
import argparse, os, json, time, sys
from .config import Config, ensure_files
from .spots import Spots
from .capture_loop import Bot

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

def cmd_init():
    ensure_files(BASE_DIR)
    print("Initialized default files (Coords.json). Edit config.json to set ROIs and templates.")

def cmd_create_spot(name: str):
    from .spots import Spots
    spots = Spots(BASE_DIR)
    print("Place your mouse on the spot center, then press Enter here...")
    input()
    x,y = spots.add_spot_from_mouse(name)
    print(f"Saved spot '{name}' at ({x},{y}).")

def cmd_start():
    bot = Bot(os.path.join(BASE_DIR, "config.json"), BASE_DIR)
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="Create default files")
    ap.add_argument("--create-spot", type=str, help="Record a spot by name")
    ap.add_argument("--start", action="store_true", help="Start the bot")
    ap.add_argument("--ui", action="store_true", help="Launch GUI")
    args = ap.parse_args()

    if args.init:
        cmd_init(); return
    if args.create_spot:
        cmd_create_spot(args.create_spot); return
    if args.start:
        cmd_start(); return
    if args.ui:
        from .ui import launch
        launch(); return
    print("Nothing to do. Use --init / --create-spot <name> / --start.")

if __name__ == "__main__":
    main()
