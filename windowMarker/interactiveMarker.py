#!/usr/bin/env python3
"""
interactiveMarker.py – Interaktive Fenster-/Glasflaechen-Markierung per Klick (CLI/OpenCV-Variante).

Fuer die grafische Variante mit Drag & Drop, Ordnerliste und automatischer
OpenAI-Erkennung siehe windowTool.py.

Ablauf:
  1. Bild an OpenAI schicken (gruene Fensterrahmen + rote Glasflaechen-Linien),
     Ergebnis wird neben dem Bild gecacht (siehe calcImages.get_annotated).
  2. Rot-/Gruenmaske aus dem annotierten Bild extrahieren.
  3. Fenster oeffnen und klicken:
       - Klick in eine Glasflaeche flutfuellt den durch ROTE Linien begrenzten
         Bereich und passt das groesste einbeschriebene Rechteck ein
         -> das wird als Glasscheibe fuer die SVG-Ausgabe gemerkt.
       - Derselbe Klick flutfuellt zusaetzlich den durch GRUENE Linien
         begrenzten Bereich -> Bounding-Box = Fensterrahmen. Liegt der Klick
         im Bereich eines bereits erfassten Fensterrahmens, wird kein neuer
         Fenstereintrag angelegt (nur die Glasscheibe kommt dazu).
  4. Nach jedem Klick werden JSON (Fensterrahmen, flache Liste wie im
     bestehenden Format {"name","windows":[{"x","y","w","h"}, ...]}) und SVG
     (alle Glasscheiben als <rect>) automatisch gespeichert.

Tasten im Bildfenster:
  u        letzte Aktion rueckgaengig machen
  r        alles zuruecksetzen
  q / Esc  beenden

Verwendung:
  python interactiveMarker.py bild.jpg
  python interactiveMarker.py bild.jpg --force   (OpenAI-Annotation neu anfordern)
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from calcImages import (
    OPENAI_PROMPT, OPENAI_MODEL, GreenParams,
    get_annotated, _extract_color_mask, save_json,
    prep_wall, flood_region, largest_rectangle_in_region, grow_rect_through_wall,
)

# Klicks, die mehr als diesen Anteil der Bildflaeche fuellen, gelten als
# "kein geschlossener Bereich" und werden verworfen.
MAX_FILL_AREA_FRACTION = 0.6


class InteractiveMarker:
    def __init__(self, img_path: Path, prompt: str, model: str, force: bool):
        self.img_path = img_path
        self.svg_path = img_path.with_suffix('.svg')

        bgr = cv2.imread(str(img_path))
        if bgr is None:
            print(f'Fehler: Kann Bild nicht lesen: {img_path}')
            sys.exit(1)
        self.bgr = bgr
        self.h, self.w = bgr.shape[:2]

        print('Hole annotiertes Bild ...')
        self.annotated = get_annotated(img_path, bgr, prompt, force=force, model=model)

        p = GreenParams()
        self.red_wall = prep_wall(_extract_color_mask(self.annotated, True, p.green_thresh) > 0)
        self.green_wall = prep_wall(_extract_color_mask(self.annotated, False, p.green_thresh) > 0)

        self.windows: list = []   # [{'x','y','w','h'}, ...]  -> JSON (Fensterrahmen)
        self.panes: list = []     # [{'x','y','w','h'}, ...]  -> SVG  (Glasscheiben)
        self.history: list = []   # [(window_or_None, pane), ...]  fuer Undo

        self.win_name = f'Fenster markieren – {img_path.name}  (u=Rueckgaengig r=Reset q=Beenden)'
        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.win_name, self._on_mouse)

    # ── Klick-Logik ──────────────────────────────────────────────────────────

    def _find_window(self, rect: tuple):
        """Bereits erfassten Fensterrahmen finden, der den Mittelpunkt von `rect` enthaelt."""
        gx, gy, gw, gh = rect
        gcx, gcy = gx + gw / 2, gy + gh / 2
        for win in self.windows:
            if win['x'] <= gcx <= win['x'] + win['w'] and win['y'] <= gcy <= win['y'] + win['h']:
                return win
        return None

    def _on_mouse(self, event, x, y, flags, _param):
        if event != cv2.EVENT_LBUTTONDOWN or not (0 <= x < self.w and 0 <= y < self.h):
            return

        pane_region = flood_region(self.red_wall, (x, y))
        if pane_region is None:
            print('  Klick liegt auf einer roten Linie – ignoriert.')
            return
        if pane_region.sum() > MAX_FILL_AREA_FRACTION * self.w * self.h:
            print('  Kein geschlossener Glasflaechen-Bereich gefunden – ignoriert.')
            return
        px, py, pw, ph = largest_rectangle_in_region(pane_region)
        if pw < 2 or ph < 2:
            print('  Keine gueltige Glasflaeche gefunden – ignoriert.')
            return
        px, py, pw, ph = grow_rect_through_wall((px, py, pw, ph), self.red_wall)
        pane = {'x': px, 'y': py, 'w': pw, 'h': ph}

        win_region = flood_region(self.green_wall, (x, y))
        if win_region is None or win_region.sum() > MAX_FILL_AREA_FRACTION * self.w * self.h:
            print('  Kein Fensterrahmen (gruen) an dieser Stelle gefunden – ignoriert.')
            return
        ys, xs = np.where(win_region)
        win_rect = (int(xs.min()), int(ys.min()),
                    int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))

        window = self._find_window(win_rect)
        new_window = None
        if window is None:
            wx, wy, ww, wh = win_rect
            window = {'x': wx, 'y': wy, 'w': ww, 'h': wh}
            self.windows.append(window)
            new_window = window

        self.panes.append(pane)
        self.history.append((new_window, pane))
        print(f'  + Scheibe {pane}' + ('  (neues Fenster)' if new_window else '  (bestehendes Fenster)'))

        self._save()
        self._render()

    def _undo(self):
        if not self.history:
            return
        window, pane = self.history.pop()
        self.panes.remove(pane)
        if window is not None:
            self.windows.remove(window)
        self._save()
        self._render()

    def _reset(self):
        self.windows.clear()
        self.panes.clear()
        self.history.clear()
        self._save()
        self._render()

    # ── Speichern ────────────────────────────────────────────────────────────

    def _save(self):
        save_json(self.img_path, self.windows)
        self._save_svg()

    def _save_svg(self):
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                 f'viewBox="0 0 {self.w} {self.h}">']
        for c in self.panes:
            parts.append(
                f'  <rect x="{c["x"]}" y="{c["y"]}" width="{c["w"]}" height="{c["h"]}" '
                f'fill="none" stroke="red" stroke-width="2"/>')
        parts.append('</svg>')
        self.svg_path.write_text('\n'.join(parts), encoding='utf-8')

    # ── Anzeige ──────────────────────────────────────────────────────────────

    def _render(self):
        dbg = self.bgr.copy()
        for i, win in enumerate(self.windows):
            cv2.rectangle(dbg, (win['x'], win['y']),
                          (win['x'] + win['w'], win['y'] + win['h']), (0, 200, 80), 2)
            cv2.putText(dbg, str(i + 1), (win['x'] + 3, win['y'] + 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 80), 1, cv2.LINE_AA)
        for c in self.panes:
            cv2.rectangle(dbg, (c['x'], c['y']),
                          (c['x'] + c['w'], c['y'] + c['h']), (0, 0, 220), 2)
        cv2.putText(dbg, f'Fenster: {len(self.windows)}  Scheiben: {len(self.panes)}',
                   (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 60), 2, cv2.LINE_AA)
        cv2.imshow(self.win_name, dbg)

    def run(self):
        self._render()
        while True:
            key = cv2.waitKey(50) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('u'):
                self._undo()
            elif key == ord('r'):
                self._reset()
        cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image', metavar='BILD')
    ap.add_argument('--prompt', default=OPENAI_PROMPT)
    ap.add_argument('--openai-model', default=OPENAI_MODEL, dest='openai_model')
    ap.add_argument('--force', action='store_true', help='Cache ignorieren, API erneut aufrufen')
    args = ap.parse_args()

    path = Path(args.image)
    if not path.is_file():
        ap.error(f'Bild nicht gefunden: {path}')

    InteractiveMarker(path, args.prompt, args.openai_model, args.force).run()


if __name__ == '__main__':
    main()
