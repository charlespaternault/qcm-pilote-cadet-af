#!/usr/bin/env python3
"""Capture la dernière zone sélectionnée de l'écran à intervalle régulier."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab

SCRIPT_DIR = Path(__file__).resolve().parent
REGION_FILE = SCRIPT_DIR / ".last_region.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "screenshots"
SYSTEM_PYTHON = Path("/usr/bin/python3")

# Exécuté par le Python système (tkinter dispo sur macOS).
_SELECTION_SCRIPT = r"""
import json
import sys
import tkinter as tk

root = tk.Tk()
root.withdraw()
scale = float(root.tk.call("tk", "scaling"))
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
root.destroy()

selector = tk.Tk()
selector.attributes("-fullscreen", True)
selector.attributes("-alpha", 0.25)
selector.attributes("-topmost", True)
selector.configure(cursor="crosshair", bg="black")
selector.overrideredirect(True)

canvas = tk.Canvas(selector, highlightthickness=0, bg="black", cursor="crosshair")
canvas.pack(fill=tk.BOTH, expand=True)

start = {}
rect_id = None
result = None

def on_press(event):
    global rect_id
    start["x"], start["y"] = event.x, event.y
    if rect_id is not None:
        canvas.delete(rect_id)
    rect_id = canvas.create_rectangle(
        event.x, event.y, event.x, event.y, outline="#00ff88", width=2
    )

def on_drag(event):
    if rect_id is not None and "x" in start:
        canvas.coords(rect_id, start["x"], start["y"], event.x, event.y)

def on_release(event):
    global result
    if "x" not in start:
        return
    x1, y1 = start["x"], start["y"]
    x2, y2 = event.x, event.y
    left, top = min(x1, x2), min(y1, y2)
    right, bottom = max(x1, x2), max(y1, y2)
    if right - left < 5 or bottom - top < 5:
        selector.destroy()
        return
    result = {
        "x": int(left * scale),
        "y": int(top * scale),
        "w": int((right - left) * scale),
        "h": int((bottom - top) * scale),
    }
    selector.destroy()

def on_escape(_):
    selector.destroy()

canvas.bind("<ButtonPress-1>", on_press)
canvas.bind("<B1-Motion>", on_drag)
canvas.bind("<ButtonRelease-1>", on_release)
selector.bind("<Escape>", on_escape)
selector.mainloop()

if result is None:
    sys.exit(1)
print(json.dumps(result))
"""


def select_region() -> dict[str, int]:
    """Sélection interactive plein écran via le Python système (tkinter)."""
    if not SYSTEM_PYTHON.is_file():
        print(
            "Python système introuvable pour la sélection graphique.",
            file=sys.stderr,
        )
        sys.exit(1)

    proc = subprocess.run(
        [str(SYSTEM_PYTHON), "-c", _SELECTION_SCRIPT],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("Sélection annulée.", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        print("Erreur lors de la sélection de zone.", file=sys.stderr)
        sys.exit(1)


def load_region() -> dict[str, int] | None:
    if not REGION_FILE.exists():
        return None
    try:
        data = json.loads(REGION_FILE.read_text())
        if all(k in data for k in ("x", "y", "w", "h")):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_region(region: dict[str, int]) -> None:
    REGION_FILE.write_text(json.dumps(region, indent=2) + "\n")


def capture_region(region: dict[str, int], output_dir: Path) -> Path:
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    bbox = (x, y, x + w, y + h)
    image = ImageGrab.grab(bbox=bbox)

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".png"
    path = output_dir / filename
    image.save(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture la dernière zone sélectionnée de l'écran à intervalle régulier."
    )
    parser.add_argument(
        "--select",
        action="store_true",
        help="Forcer une nouvelle sélection de zone (sinon réutilise la dernière).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Intervalle entre captures en secondes (défaut : 1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Dossier de sortie (défaut : {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Une seule capture puis quitter.",
    )
    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval doit être > 0")

    region = None if args.select else load_region()
    if region is None:
        print("Sélectionnez une zone à l'écran (glisser, Échap pour annuler)…")
        region = select_region()
        save_region(region)
        print(
            f"Zone enregistrée : x={region['x']} y={region['y']} "
            f"{region['w']}×{region['h']} px"
        )
    else:
        print(
            f"Zone chargée : x={region['x']} y={region['y']} "
            f"{region['w']}×{region['h']} px  (fichier {REGION_FILE.name})"
        )

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False
        print("\nArrêt…")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print(f"Captures → {args.output.resolve()}  (Ctrl+C pour arrêter)")
    count = 0

    while running:
        t0 = time.monotonic()
        path = capture_region(region, args.output)
        count += 1
        print(f"[{count}] {path.name}")

        if args.once:
            break

        elapsed = time.monotonic() - t0
        sleep_for = args.interval - elapsed
        if sleep_for > 0 and running:
            time.sleep(sleep_for)

    print(f"Terminé — {count} capture(s).")


if __name__ == "__main__":
    main()
