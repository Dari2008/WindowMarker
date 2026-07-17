#!/usr/bin/env python3
"""
calcImages.py – Automatische Fenstererkennung fuer Gebaeudebilder.

Methoden:
  openai – GPT-Image-1 zeichnet gruene Boxen; OpenCV liest sie aus  [Standard]
  yolo   – YOLOWorld zero-shot (kein Training noetig)
  opencv – Kantenerkennung / Helligkeitsschwelle

Verwendung:
  python calcImages.py bild.jpg
  python calcImages.py bild.jpg --tune
  python calcImages.py bild.jpg --method yolo
  python calcImages.py bild.jpg --method opencv --mode bright
  python calcImages.py --folder ordner/ --overwrite
"""

import cv2
import numpy as np
import json
import argparse
import base64
import io
import sys
from pathlib import Path
from typing import NamedTuple
from dotenv import load_dotenv
import os

# ── API-Key ────────────────────────────────────────────────────────────────────

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_KEY")

# Prompt, den OpenAI erhaelt (Englisch fuer beste Ergebnisse)
OPENAI_PROMPT = (
    '''
    Annotate all windows with a green rectangle and all glass panes of the windows with a red rectangle. Also anotate shop windows.
    '''
)

# OpenAI-Modell fuer die Bildannotierung
OPENAI_MODEL = 'gpt-image-2'

# ── Konstanten ─────────────────────────────────────────────────────────────────

IMAGE_EXTS   = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
CACHE_SUFFIX = '._annotated.png'   # gecachtes OpenAI-Ergebnis neben dem Originalbild

DEFAULT_CLASSES = ['window']
DEFAULT_MODEL   = 'yolov8s-worldv2.pt'


# ── Parameter-Klassen ──────────────────────────────────────────────────────────

class GreenParams(NamedTuple):
    """Parameter fuer die gruene-Box-Erkennung im OpenAI-Ergebnis."""
    green_thresh: int   = 40    # Mindest-Grünheit: G - max(R,B), Bereich 0-255
    min_w:        int   = 8
    min_h:        int   = 8
    min_area:     int   = 60
    iou_thr:      float = 0.30


class CVParams(NamedTuple):
    canny_lo:     int   = 30
    canny_hi:     int   = 100
    clahe_clip:   float = 2.5
    dilate_iter:  int   = 2
    thresh_block: int   = 25
    thresh_c:     int   = 8
    min_w:        int   = 10
    min_h:        int   = 10
    max_w:        int   = 500
    max_h:        int   = 500
    min_area:     int   = 150
    min_ratio:    float = 0.10
    max_ratio:    float = 8.0
    rect_score:   float = 0.40
    iou_thresh:   float = 0.35
    cv_mode:      str   = 'both'


# ── Gemeinsame Hilfsfunktionen ─────────────────────────────────────────────────

def iou(a: tuple, b: tuple) -> float:
    ax1, ay1, aw, ah = a[:4]
    bx1, by1, bw, bh = b[:4]
    ix1 = max(ax1, bx1);  iy1 = max(ay1, by1)
    ix2 = min(ax1 + aw, bx1 + bw)
    iy2 = min(ay1 + ah, by1 + bh)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    return inter / (aw * ah + bw * bh - inter)


def nms(rects: list, thresh: float) -> list:
    kept = []
    for r in sorted(rects, key=lambda r: r[2] * r[3], reverse=True):
        if all(iou(r, k) <= thresh for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: (r[1], r[0]))


def _containment(outer: tuple, inner: tuple) -> float:
    """Fraction of inner's area that lies inside outer."""
    ox, oy, ow, oh = outer[:4]
    ix, iy, iw, ih = inner[:4]
    xi1, yi1 = max(ox, ix), max(oy, iy)
    xi2, yi2 = min(ox + ow, ix + iw), min(oy + oh, iy + ih)
    if xi2 <= xi1 or yi2 <= yi1:
        return 0.0
    return (xi2 - xi1) * (yi2 - yi1) / max(1, iw * ih)


def prefer_inner(rects: list, containment_thr: float = 0.85) -> list:
    """
    Remove a rectangle if at least one smaller rectangle is mostly contained within it.
    Handles nested/group borders: keeps individual window panes, discards outer group frames.
    Applied before NMS so true duplicates are handled separately.
    """
    if len(rects) < 2:
        return rects
    remove = [False] * len(rects)
    for i, r_outer in enumerate(rects):
        if remove[i]:
            continue
        outer_area = r_outer[2] * r_outer[3]
        for j, r_inner in enumerate(rects):
            if i == j or remove[j]:
                continue
            if r_inner[2] * r_inner[3] >= outer_area:
                continue  # not smaller
            if _containment(r_outer, r_inner) > containment_thr:
                remove[i] = True
                break
    return [r for r, rm in zip(rects, remove) if not rm]


def save_json(img_path: Path, windows: list) -> Path:
    """
    Speichert Fenster-Daten als JSON.
    Akzeptiert sowohl Tupel (x,y,w,h[,conf]) als auch Dicts {'x','y','w','h','children':[]}.
    """
    out_windows = []
    for w in windows:
        if isinstance(w, dict):
            out_windows.append(w)
        else:
            out_windows.append({'x': int(w[0]), 'y': int(w[1]),
                                'w': int(w[2]), 'h': int(w[3])})
    data = {'name': img_path.stem, 'windows': out_windows}
    out  = img_path.with_suffix('.json')
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def draw_rects(bgr: np.ndarray, rects: list,
               color=(0, 200, 80), show_conf: bool = True) -> np.ndarray:
    dbg = bgr.copy()
    for i, r in enumerate(rects):
        x, y, w, h = r[:4]
        conf  = r[4] if len(r) > 4 else None
        label = str(i + 1)
        if show_conf and conf is not None:
            label += f'  {conf:.0%}'
        cv2.rectangle(dbg, (x, y), (x + w, y + h), color, 2)
        cv2.putText(dbg, label, (x + 3, y + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return dbg


def show_result(bgr: np.ndarray, rects: list, title: str = 'Erkannte Fenster'):
    cv2.imshow(title, draw_rects(bgr, rects))
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def draw_openai_result(bgr: np.ndarray, windows: list) -> np.ndarray:
    """
    Zeichnet grüne Fenster-Bounding-Rects und rote Glasflaechen-Polylinien.
    windows: Liste von Dicts {'x','y','w','h','children':[{'polygon':...}]}
    """
    dbg = bgr.copy()
    for i, w in enumerate(windows):
        x, y, ww, wh = w['x'], w['y'], w['w'], w['h']
        cv2.rectangle(dbg, (x, y), (x + ww, y + wh), (0, 200, 80), 2)
        cv2.putText(dbg, str(i + 1), (x + 3, y + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 80), 1, cv2.LINE_AA)
        for child in w.get('children', []):
            poly = child.get('polygon')
            if poly:
                pts = np.array(poly, dtype=np.int32)
                cv2.polylines(dbg, [pts], isClosed=True, color=(0, 0, 220), thickness=2)
            else:
                cx2 = child['x'] + child['w']
                cy2 = child['y'] + child['h']
                cv2.rectangle(dbg, (child['x'], child['y']), (cx2, cy2), (0, 0, 220), 1)
    return dbg


def show_openai_result(bgr: np.ndarray, windows: list, title: str = 'Erkannte Fenster'):
    cv2.imshow(title, draw_openai_result(bgr, windows))
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def _overlay_info(img: np.ndarray, text: str) -> np.ndarray:
    cv2.putText(img, text, (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 60), 2, cv2.LINE_AA)
    return img


# ── OpenAI-Methode ─────────────────────────────────────────────────────────────

def _check_api_key():
    if not OPENAI_API_KEY:
        print('Fehler: OPENAI_API_KEY ist leer.')
        print('  Bitte den Key in calcImages.py oben eintragen.')
        sys.exit(1)


def _bgr_to_png_bytes(bgr: np.ndarray) -> bytes:
    _, buf = cv2.imencode('.png', bgr)
    return buf.tobytes()


# Echte Grenzen der OpenAI-Images-API (gpt-image-1 & co.): jede Achse muss ein
# Vielfaches von 16 sein, und insgesamt duerfen es hoechstens 8.000.000 Pixel
# sein. Ein Bild, das diese Grenzen nicht einhaelt, wird von OpenAI selbst
# zurechtgeschnitten/aufgefuellt statt sauber skaliert -- das hat bisher dazu
# gefuehrt, dass die zurueckgegebenen Markierungen nicht mehr zum Original
# passten (siehe _resize_back in call_openai).
OPENAI_MAX_PIXELS = 8_000_000
OPENAI_DIM_MULTIPLE = 16


def _fit_openai_dims(w: int, h: int, max_pixels: int = OPENAI_MAX_PIXELS,
                     multiple: int = OPENAI_DIM_MULTIPLE) -> tuple[int, int]:
    """Groesstmoegliche Zielgroesse, die (a) das Seitenverhaeltnis von (w, h)
    GENAU beibehaelt (eine einzige gemeinsame Skalierung fuer beide Achsen,
    keine unabhaengige Streckung/Verzerrung), (b) je Achse ein Vielfaches von
    `multiple` ist und (c) insgesamt hoechstens `max_pixels` Pixel hat. Wird
    das Bild bereits eingehalten (kleines Foto), bleibt nur das Abrunden auf
    ein Vielfaches von 16 uebrig -- sonst so gross wie moeglich innerhalb des
    Pixel-Budgets, statt wie bisher pauschal auf eine kleine Kantenlaenge
    (1024px) zu schrumpfen."""
    scale = min(1.0, (max_pixels / (w * h)) ** 0.5)
    new_w = max(multiple, int(w * scale) // multiple * multiple)
    new_h = max(multiple, int(h * scale) // multiple * multiple)
    return new_w, new_h


def call_openai(bgr: np.ndarray, prompt: str, model: str = OPENAI_MODEL) -> np.ndarray:
    """
    Schickt das Bild an das gewaehlte OpenAI-Modell und gibt das annotierte Bild zurueck.
    Das Bild wird ggf. auf die von OpenAI erlaubte Groesse skaliert (siehe
    _fit_openai_dims); die Rueckgabe hat dieselbe Groesse wie bgr.
    """
    _check_api_key()
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print('Fehler: openai nicht installiert.  pip install openai')
        sys.exit(1)

    h, w = bgr.shape[:2]
    new_w, new_h = _fit_openai_dims(w, h)
    small = cv2.resize(bgr, (new_w, new_h),
                       interpolation=cv2.INTER_AREA) if (new_w, new_h) != (w, h) else bgr

    gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    small = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)   # Graustufen als RGB-PNG
    png_bytes = _bgr_to_png_bytes(small)

    print(f'  Sende Bild an OpenAI ({model}) ...')
    client = OpenAI(api_key=OPENAI_API_KEY)

    if model == 'dall-e-2':
        # dall-e-2 benoetigt quadratisches RGBA-Bild und eine Maske
        sh, sw = small.shape[:2]
        side   = min(1024, max(256, max(sh, sw)))
        side   = 1024 if side > 512 else (512 if side > 256 else 256)
        sq     = cv2.resize(small, (side, side), interpolation=cv2.INTER_AREA)
        rgba   = cv2.cvtColor(sq, cv2.COLOR_BGR2BGRA)
        _, img_buf = cv2.imencode('.png', rgba)
        # Maske: voellig transparent -> alles bearbeiten
        mask_arr = np.zeros((side, side, 4), dtype=np.uint8)
        _, mask_buf = cv2.imencode('.png', mask_arr)
        response = client.images.edit(
            model           = 'dall-e-2',
            image           = ('image.png',  io.BytesIO(bytes(img_buf)),  'image/png'),
            mask            = ('mask.png',   io.BytesIO(bytes(mask_buf)), 'image/png'),
            prompt          = prompt,
            n               = 1,
            size            = f'{side}x{side}',
            response_format = 'b64_json',
        )
    else:
        response = client.images.edit(
            model  = model,
            image  = ('image.png', io.BytesIO(png_bytes), 'image/png'),
            prompt = prompt,
        )

    img_bytes = base64.b64decode(response.data[0].b64_json)
    arr       = np.frombuffer(img_bytes, np.uint8)
    annotated = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if annotated is None:
        print('  Fehler: Antwort konnte nicht dekodiert werden.')
        sys.exit(1)

    # Auf Originalgroesse zurueckskalieren
    if annotated.shape[:2] != (h, w):
        annotated = cv2.resize(annotated, (w, h), interpolation=cv2.INTER_LINEAR)

    return annotated


def _cache_path(img_path: Path) -> Path:
    return img_path.with_name(img_path.stem + CACHE_SUFFIX)


# OpenAIs images.edit ist eine generative Bearbeitung, kein pixelgenauer Edit:
# das zurueckgegebene Bild ist inhaltlich fast identisch, aber um ein paar
# Pixel verschoben/leicht anders skaliert (bestaetigt durch Vergleich der
# regenerierten Gebaeude-Textur mit dem echten Original an derselben Stelle).
# Dadurch landen die gruenen/roten Markierungen leicht daneben, wenn man sie
# direkt auf dem Original ausschneidet. ECC-Bildregistrierung berechnet die
# affine Korrektur, die annotated wieder auf original ausrichtet, bevor die
# Farbmasken extrahiert werden. Auf halber Aufloesung berechnet (deutlich
# schneller, das Ergebnis ist praktisch identisch, siehe Skalierungs-Invarianz
# der linearen ECC-Komponente); nur die Translation muss auf volle Aufloesung
# hochskaliert werden.
_ECC_SCALE = 0.5


def _align_annotated(original: np.ndarray, annotated: np.ndarray,
                     scale: float = _ECC_SCALE) -> np.ndarray:
    """Richtet `annotated` per ECC-Registrierung wieder auf `original` aus."""
    h, w = original.shape[:2]
    if annotated.shape[:2] != (h, w):
        return annotated

    sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
    small_o = cv2.resize(original,  (sw, sh), interpolation=cv2.INTER_AREA)
    small_a = cv2.resize(annotated, (sw, sh), interpolation=cv2.INTER_AREA)
    gray_o  = cv2.cvtColor(small_o, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray_a  = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY).astype(np.float32)

    warp_matrix = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    try:
        _, warp_matrix = cv2.findTransformECC(gray_o, gray_a, warp_matrix,
                                              cv2.MOTION_AFFINE, criteria)
    except cv2.error as e:
        print(f'  WARNUNG: ECC-Ausrichtung fehlgeschlagen ({e}); '
              f'verwende unkorrigiertes Bild.')
        return annotated

    warp_full = warp_matrix.copy()
    warp_full[:, 2] /= scale   # Translation war auf halber Aufloesung berechnet
    return cv2.warpAffine(annotated, warp_full, (w, h),
                          flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def get_annotated(img_path: Path, bgr: np.ndarray,
                  prompt: str, force: bool = False,
                  model: str = OPENAI_MODEL) -> np.ndarray:
    """Gibt das KI-annotierte Bild zurueck; nutzt Cache wenn vorhanden.
    Richtet das Ergebnis in jedem Fall per ECC auf `bgr` aus (siehe
    _align_annotated), auch wenn es aus dem Cache kommt -- so profitieren
    auch schon vorhandene, vor dieser Korrektur erzeugte Cache-Dateien
    automatisch beim naechsten Laden davon."""
    cache = _cache_path(img_path)
    if not force and cache.exists():
        print(f'  Cache gefunden: {cache.resolve()}')
        cached = cv2.imread(str(cache))
        if cached is not None:
            aligned = _align_annotated(bgr, cached)
            if not np.array_equal(aligned, cached):
                if cv2.imwrite(str(cache), aligned):
                    print(f'  Cache per ECC neu ausgerichtet: {cache.resolve()}')
            return aligned

    annotated = call_openai(bgr, prompt, model=model)
    annotated = _align_annotated(bgr, annotated)
    ok = cv2.imwrite(str(cache), annotated)
    if ok:
        print(f'  Annotiertes Bild gespeichert: {cache.resolve()}')
    else:
        print(f'  WARNUNG: Konnte Cache nicht schreiben: {cache.resolve()}')
    return annotated


def greenness_map(annotated: np.ndarray) -> np.ndarray:
    """Grünheits-Graustufenbild: G - max(R, B), Bereich 0-255."""
    f = annotated.astype(np.int16)
    g = np.clip(f[:, :, 1] - np.maximum(f[:, :, 0], f[:, :, 2]), 0, 255)
    return g.astype(np.uint8)


def redness_map(annotated: np.ndarray) -> np.ndarray:
    """Rötlichkeits-Graustufenbild: R - max(G, B), Bereich 0-255. BGR-Eingabe."""
    f = annotated.astype(np.int16)
    r = np.clip(f[:, :, 2] - np.maximum(f[:, :, 0], f[:, :, 1]), 0, 255)
    return r.astype(np.uint8)


def save_intermediate(img_path: Path, annotated: np.ndarray,
                      green_thresh: int = GreenParams().green_thresh):
    """Speichert alle Zwischenbilder neben dem Originalbild."""
    stem   = img_path.stem
    parent = img_path.resolve().parent

    def _write(path: Path, img: np.ndarray):
        ok = cv2.imwrite(str(path), img)
        if not ok:
            print(f'  WARNUNG: Schreiben fehlgeschlagen: {path}')
        return ok

    # 1. OpenAI-annotiertes Bild (Farbe)
    p_ann   = parent / (stem + '._annotated.png')
    _write(p_ann, annotated)

    # 2. Grünheits-Graustufenbild + gefilterte Maske
    green   = greenness_map(annotated)
    p_green = parent / (stem + '._greenness.png')
    _write(p_green, green)
    gmask   = _extract_color_mask(annotated, False, green_thresh)
    _write(parent / (stem + '._greenmask.png'), gmask)

    # 3. Rötlichkeits-Graustufenbild + gefilterte Maske
    red    = redness_map(annotated)
    p_red  = parent / (stem + '._redness.png')
    _write(p_red, red)
    rmask  = _extract_color_mask(annotated, True, green_thresh)
    _write(parent / (stem + '._redmask.png'), rmask)

    print(f'  Zwischenbilder gespeichert in: {parent}')
    print(f'    {p_ann.name}  |  {p_green.name}  |  {p_red.name}')


def _extract_color_mask(annotated: np.ndarray, is_red: bool, thresh: int) -> np.ndarray:
    """
    Schritt 1: Filtert genau eine Farbe aus dem annotierten Bild.
    Grün: G − max(R,B)  |  Rot: R − max(G,B)   (BGR-Reihenfolge)
    Gibt eine Binärmaske zurück (255 = Zielfarbe).
    """
    f = annotated.astype(np.int16)
    if is_red:
        ch = np.clip(f[:, :, 2] - np.maximum(f[:, :, 0], f[:, :, 1]), 0, 255)
    else:
        ch = np.clip(f[:, :, 1] - np.maximum(f[:, :, 0], f[:, :, 2]), 0, 255)
    _, mask = cv2.threshold(ch.astype(np.uint8), thresh, 255, cv2.THRESH_BINARY)
    return mask


# ── Klick-basierte Flutfuellung (interactiveMarker.py / windowTool.py) ─────────

def prep_wall(mask: np.ndarray) -> np.ndarray:
    """Schliesst kleine Luecken in einer Linienmaske, damit eine Flutfuellung nicht
    durch Antialiasing-Luecken in der roten/gruenen Linie durchsickert."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    closed = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, k, iterations=2)
    return closed > 0


def flood_region(barrier: np.ndarray, seed: tuple):
    """
    Flutfuellt den mit `seed` (x, y) verbundenen Bereich, der nicht durch `barrier`
    (True = Wand) begrenzt ist. Gibt None zurueck, wenn der Klick selbst auf einer Wand liegt.
    """
    sx, sy = seed
    if barrier[sy, sx]:
        return None
    free = (~barrier).astype(np.uint8)   # 1 = begehbar, 0 = Wand
    ff_mask = np.zeros((free.shape[0] + 2, free.shape[1] + 2), np.uint8)
    cv2.floodFill(free, ff_mask, (sx, sy), 2, loDiff=0, upDiff=0, flags=4)
    return free == 2


def largest_rectangle(mask: np.ndarray) -> tuple:
    """Groesstes achsenparalleles Rechteck, das vollstaendig in `mask` (bool) liegt.
    Klassischer 'largest rectangle in binary matrix' Algorithmus (Histogramm + Stack)."""
    h, w = mask.shape
    heights = np.zeros(w, dtype=np.int32)
    best_area = 0
    best = (0, 0, 0, 0)
    for y in range(h):
        heights = np.where(mask[y], heights + 1, 0)
        stack = []
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            while stack and heights[stack[-1]] >= cur:
                top = stack.pop()
                bar_h = heights[top]
                left = stack[-1] + 1 if stack else 0
                width = x - left
                area = bar_h * width
                if area > best_area:
                    best_area = area
                    best = (left, y - bar_h + 1, width, bar_h)
            stack.append(x)
    return best


def largest_rectangle_in_region(region: np.ndarray) -> tuple:
    """Wie largest_rectangle, aber auf die Bounding-Box von `region` zugeschnitten
    (deutlich schneller als die ganze Bildflaeche zu durchsuchen)."""
    ys, xs = np.where(region)
    if len(xs) == 0:
        return (0, 0, 0, 0)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    lx, ly, lw, lh = largest_rectangle(region[y0:y1, x0:x1])
    return (x0 + lx, y0 + ly, lw, lh)


def grow_rect_through_wall(rect: tuple, wall_mask: np.ndarray, max_grow: int = 25) -> tuple:
    """
    Erweitert ein Rechteck an allen vier Seiten ueber eine Wandmaske (z.B. die
    rohe, ungedilatete Rotmaske) hinweg: jede Kante wandert so lange nach aussen,
    wie sie noch Wand-Pixel beruehrt, und stoppt erst, sobald sie komplett
    hindurch ist (die Zeile/Spalte also wieder frei von der Farbe ist).
    So reicht die fertige Glasscheibe bis zur Aussenkante der roten Linie statt
    knapp davor aufzuhoeren.
    """
    x, y, w, h = rect
    H, W = wall_mask.shape

    grown = 0
    while y > 0 and grown < max_grow and wall_mask[y - 1, x:x + w].any():
        y -= 1; h += 1; grown += 1
    grown = 0
    while y + h < H and grown < max_grow and wall_mask[y + h, x:x + w].any():
        h += 1; grown += 1
    grown = 0
    while x > 0 and grown < max_grow and wall_mask[y:y + h, x - 1].any():
        x -= 1; w += 1; grown += 1
    grown = 0
    while x + w < W and grown < max_grow and wall_mask[y:y + h, x + w].any():
        w += 1; grown += 1

    return (x, y, w, h)


def _mask_to_edge_contours(mask: np.ndarray) -> list:
    """
    Schritt 2: Wandelt eine Binärmaske über Kantenerkennung in Konturen um.
    Jede zusammenhängende Farbregion → genau EINE Kontur.

    Pipeline:
      a) Dilation:   Strichlinien zu Flächen aufblasen
      b) Close:      verbleibende Lücken schliessen
      c) Open:       Rauschen / winzige Flecken entfernen
      d) Morph. Gradient (Dilation − Erosion):
             erzeugt eine dünne Kantenlinie pro Fläche (kein Doppelring)
      e) findContours: eine Kontur pro Kantenlinie
    """
    fill_k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    filled  = cv2.dilate(mask, fill_k, iterations=2)

    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    filled  = cv2.morphologyEx(filled, cv2.MORPH_CLOSE, close_k, iterations=2)
    filled  = cv2.morphologyEx(filled, cv2.MORPH_OPEN,  close_k, iterations=1)

    edge_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    edges  = cv2.morphologyEx(filled, cv2.MORPH_GRADIENT, edge_k)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return list(contours)


def _color_to_rects(annotated: np.ndarray, p: GreenParams,
                    is_red: bool = False) -> list:
    """
    Schritt 1+2 für Bounding-Rects:
    Farbe isolieren → Kantenkonturen → (x,y,w,h)-Tupel-Liste.
    """
    mask     = _extract_color_mask(annotated, is_red, p.green_thresh)
    contours = _mask_to_edge_contours(mask)
    rects = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= p.min_w and h >= p.min_h and w * h >= p.min_area:
            rects.append((x, y, w, h))
    return rects


def _make_right_angle_poly(contour: np.ndarray,
                            x: int, y: int, w: int, h: int) -> list:
    """
    Erstellt ein Polygon mit exakten 90°-Winkeln aus einem dichten Kontur-Array.

    Rechteckige Scheibe  → 4 Ecken des Bounding-Rects.
    Bogenfenster (oben)  → linke Schulter · Bogenkurve (links→rechts) ·
                           rechte Schulter · unten-rechts · unten-links.

    Arch-Erkennung: gibt es im oberen 40 % der Höhe Punkte, die weder am
    linken noch am rechten Rand liegen? Dann ist die Oberseite gebogen.
    """
    pts = contour.reshape(-1, 2).astype(np.float32)
    tol = min(w, h) * 0.10          # Randtoleranz (10 % der kürzeren Seite)

    # ── Arch-Detektion ────────────────────────────────────────────────────────
    arch_zone_y = y + h * 0.40
    arch_cands  = pts[
        (pts[:, 1] < arch_zone_y) &
        (pts[:, 0] > x + tol) &
        (pts[:, 0] < x + w - tol)
    ]
    if len(arch_cands) < 5:
        # Rechteckige Scheibe: exakt 4 Ecken
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    # ── Bogenfenster ──────────────────────────────────────────────────────────
    # Schulter-Y: der höchste Punkt (kleinstes y) an der linken bzw. rechten
    # Seite. Der Bogen beginnt dort.
    left_pts  = pts[pts[:, 0] <= x + tol]
    right_pts = pts[pts[:, 0] >= x + w - tol]
    if len(left_pts) > 0 and len(right_pts) > 0:
        shoulder_y = int(min(left_pts[:, 1].min(), right_pts[:, 1].min()))
    elif len(left_pts) > 0:
        shoulder_y = int(left_pts[:, 1].min())
    elif len(right_pts) > 0:
        shoulder_y = int(right_pts[:, 1].min())
    else:
        shoulder_y = int(y + h * 0.5)

    # Alle Konturpunkte im Bogen-Bereich (oberhalb der Schulter)
    arch_pts = pts[pts[:, 1] <= shoulder_y + tol * 1.5]
    if len(arch_pts) < 3:
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    # Bogen vereinfachen (offene Kurve, nicht geschlossen)
    arch_c   = arch_pts.reshape(-1, 1, 2).astype(np.int32)
    arch_eps = max(1.0, 0.008 * cv2.arcLength(arch_c, False))
    arch_simplified = (cv2.approxPolyDP(arch_c, arch_eps, False)
                       .reshape(-1, 2).tolist())

    # Von links nach rechts sortieren: ergibt für Halb- und Spitzbogen
    # die korrekte Reihenfolge über den Scheitelpunkt
    arch_simplified.sort(key=lambda p: p[0])

    # Polygon zusammensetzen
    result: list = [[x, shoulder_y]]          # linke Schulter (exakter Rand)
    for p_ in arch_simplified:
        pt = [int(round(p_[0])), int(round(p_[1]))]
        if pt != result[-1]:
            result.append(pt)
    if [x + w, shoulder_y] != result[-1]:
        result.append([x + w, shoulder_y])    # rechte Schulter (exakter Rand)
    result.append([x + w, y + h])             # unten-rechts
    result.append([x,     y + h])             # unten-links
    return result


def _color_to_shapes(annotated: np.ndarray, p: GreenParams,
                     is_red: bool = True) -> list:
    """
    Schritt 1+2 für Formen mit rechten Winkeln:
    Farbe isolieren → Kantenkonturen → Dicts mit 90°-Polygon (Bogen erhalten).
    """
    mask     = _extract_color_mask(annotated, is_red, p.green_thresh)
    contours = _mask_to_edge_contours(mask)
    shapes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= p.min_w and h >= p.min_h and w * h >= p.min_area:
            poly = _make_right_angle_poly(c, x, y, w, h)
            shapes.append({'x': x, 'y': y, 'w': w, 'h': h, 'polygon': poly})
    return shapes


def find_green_rects(annotated: np.ndarray, p: GreenParams) -> list:
    """Erkennt gruene Fenster-Rahmen; gibt (x,y,w,h)-Tupel-Liste zurueck."""
    rects = _color_to_rects(annotated, p, is_red=False)
    rects = prefer_inner(rects, containment_thr=0.80)
    return nms(rects, p.iou_thr)


def detect_openai(annotated: np.ndarray, p: GreenParams) -> list:
    """
    Vollstaendige OpenAI-Erkennung: gruene Fensterrahmen + rote Glasflaechen.
    Gibt eine Liste von Fenster-Dicts zurueck:
      {'x', 'y', 'w', 'h', 'children': [{'x','y','w','h','polygon':[[x,y],...]}]}
    """
    # Grüne Bounding-Rects (Fensterrahmen)
    green_rects = find_green_rects(annotated, p)

    # Rote Glasflächen-Konturen (können Bögen sein)
    red_shapes  = _color_to_shapes(annotated, p, is_red=True)

    # Rote Formen den passenden Fenstern als children zuordnen
    windows = []
    for gx, gy, gw, gh in green_rects:
        children = []
        for rs in red_shapes:
            cx = rs['x'] + rs['w'] // 2
            cy = rs['y'] + rs['h'] // 2
            if gx <= cx <= gx + gw and gy <= cy <= gy + gh:
                children.append(rs)
        windows.append({'x': gx, 'y': gy, 'w': gw, 'h': gh, 'children': children})
    return windows


def tune_openai(img_path: Path, bgr: np.ndarray, annotated: np.ndarray,
                prompt: str = OPENAI_PROMPT, model: str = OPENAI_MODEL):
    """
    Interaktives Tuning der Farberkennung.
    Links: annotiertes OpenAI-Bild (zeigt Bögen und rote Glasflächen direkt).
    Rechts: erkannte Fenster (grüne Rects) + Glasflächen (rote Polylinien) auf dem Original.
    """
    WIN = 'OpenAI Tuning  (s=Speichern  r=Neu laden  q=Beenden)'
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

    bars = [
        ('Farb-Schwelle',  40,  254),
        ('Min Breite',      8,  300),
        ('Min Hoehe',       8,  300),
        ('Min Flaeche',    60, 5000),
        ('IoU NMS x100',   30,  100),
    ]
    for name, start, mx in bars:
        cv2.createTrackbar(name, WIN, start, mx, lambda _: None)

    print(f'Tuning: {img_path.name}  |  s=Speichern  r=API erneut aufrufen  q=Beenden')
    last_windows: list = []

    while True:
        v = {n: cv2.getTrackbarPos(n, WIN) for n, _, _ in bars}
        p = GreenParams(
            green_thresh = max(1, v['Farb-Schwelle']),
            min_w        = max(1, v['Min Breite']),
            min_h        = max(1, v['Min Hoehe']),
            min_area     = max(1, v['Min Flaeche']),
            iou_thr      = v['IoU NMS x100'] / 100,
        )

        windows      = detect_openai(annotated, p)
        last_windows = windows

        # Links: annotiertes Bild von OpenAI (Bögen und Farben direkt sichtbar)
        left  = annotated.copy()
        # Rechts: erkannte grüne Rahmen + rote Glasflächen-Polylinien auf Original
        right = draw_openai_result(bgr, windows)

        lh = left.shape[0]
        rh, rw = right.shape[:2]
        if lh != rh:
            right = cv2.resize(right, (int(rw * lh / rh), lh))

        n_children = sum(len(w.get('children', [])) for w in windows)
        combined   = np.hstack([left, right])
        _overlay_info(combined,
            f'Fenster: {len(windows)}  Glasfl.: {n_children}  |  '
            f'Links: OpenAI-Annotation  Rechts: Erkannte Formen  |  '
            f'Schwelle={p.green_thresh}  s=Speichern  r=Neu  q=Beenden')

        cv2.imshow(WIN, combined)
        key = cv2.waitKey(50) & 0xFF

        if key in (ord('q'), 27):
            break
        if key == ord('s'):
            save_intermediate(img_path, annotated, p.green_thresh)
            out = save_json(img_path, last_windows)
            n_c = sum(len(w.get('children', [])) for w in last_windows)
            print(f'  Gespeichert: {out}  ({len(last_windows)} Fenster, {n_c} Glasflaechen)')
        if key == ord('r'):
            cv2.destroyAllWindows()
            print('  Rufe OpenAI erneut auf ...')
            annotated = get_annotated(img_path, bgr, prompt, force=True, model=model)
            cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
            for name, start, mx in bars:
                cv2.createTrackbar(name, WIN, cv2.getTrackbarPos(name, WIN), mx, lambda _: None)

    cv2.destroyAllWindows()
    return last_windows


# ── YOLO-Methode ───────────────────────────────────────────────────────────────

def load_yolo(model_name: str, classes: list):
    try:
        from ultralytics import YOLOWorld
    except ImportError:
        print('Fehler: ultralytics nicht installiert.  pip install ultralytics')
        sys.exit(1)
    print(f'Lade Modell: {model_name}  (Klassen: {classes})')
    model = YOLOWorld(model_name)
    model.set_classes(classes)
    return model


def detect_yolo(bgr: np.ndarray, model, conf: float,
                iou_thresh: float, imgsz: int) -> list:
    results = model.predict(bgr, conf=conf, iou=iou_thresh, imgsz=imgsz, verbose=False)
    rects   = []
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            rects.append((x1, y1, max(1, x2 - x1), max(1, y2 - y1), float(box.conf[0])))
    return rects


def tune_yolo(path: Path, bgr: np.ndarray, model, args):
    WIN   = 'YOLO Tuning  (s=Speichern  q=Beenden)'
    SIZES = [320, 416, 512, 640, 800, 1024]
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.createTrackbar('Konfidenz x100', WIN, int(args.conf * 100), 100, lambda _: None)
    cv2.createTrackbar('IoU NMS x100',   WIN, int(args.iou  * 100), 100, lambda _: None)
    cv2.createTrackbar('Bildgroesse idx', WIN,
        SIZES.index(min(SIZES, key=lambda s: abs(s - args.imgsz))),
        len(SIZES) - 1, lambda _: None)

    print(f'YOLO Tuning: {path.name}  |  Klassen: {args.classes}')
    last_rects = []

    while True:
        conf   = max(0.01, cv2.getTrackbarPos('Konfidenz x100', WIN) / 100)
        iou_t  = max(0.01, cv2.getTrackbarPos('IoU NMS x100',   WIN) / 100)
        imgsz  = SIZES[cv2.getTrackbarPos('Bildgroesse idx', WIN)]
        rects  = detect_yolo(bgr, model, conf, iou_t, imgsz)
        last_rects = rects
        dbg    = draw_rects(bgr, rects)
        _overlay_info(dbg,
            f'Fenster: {len(rects)}  conf={conf:.2f}  iou={iou_t:.2f}  '
            f'imgsz={imgsz}  |  s=Speichern  q=Beenden')
        cv2.imshow(WIN, dbg)
        key = cv2.waitKey(80) & 0xFF
        if key in (ord('q'), 27):
            break
        if key == ord('s'):
            out = save_json(path, last_rects)
            print(f'  Gespeichert: {out}  ({len(last_rects)} Fenster)')

    cv2.destroyAllWindows()


# ── OpenCV-Methode ─────────────────────────────────────────────────────────────

def _odd(n: int) -> int:
    n = max(3, n)
    return n if n % 2 == 1 else n + 1


def _filter_contours(contours, p: CVParams) -> list:
    rects = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < p.min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not (p.min_w <= w <= p.max_w and p.min_h <= h <= p.max_h):
            continue
        ratio = w / h
        if not (p.min_ratio <= ratio <= p.max_ratio):
            continue
        if area / (w * h) < p.rect_score:
            continue
        rects.append((x, y, w, h))
    return rects


def detect_edge(bgr: np.ndarray, p: CVParams) -> list:
    gray  = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=p.clahe_clip, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)
    blur  = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, p.canny_lo, p.canny_hi)
    k     = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, k, iterations=p.dilate_iter)
    if p.dilate_iter > 0:
        edges = cv2.erode(edges, k, iterations=max(0, p.dilate_iter - 1))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return _filter_contours(contours, p)


def detect_bright(bgr: np.ndarray, p: CVParams) -> list:
    gray  = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    block = _odd(p.thresh_block)
    mask  = cv2.adaptiveThreshold(gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, -p.thresh_c)
    k    = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return _filter_contours(contours, p)


def detect_opencv(bgr: np.ndarray, p: CVParams) -> list:
    rects = []
    if p.cv_mode in ('edge', 'both'):
        rects += detect_edge(bgr, p)
    if p.cv_mode in ('bright', 'both'):
        rects += detect_bright(bgr, p)
    return nms(rects, p.iou_thresh)


def tune_opencv(path: Path, bgr: np.ndarray, cv_mode: str):
    WIN  = 'OpenCV Tuning  (s=Speichern  q=Beenden)'
    bars = [
        ('Canny Lo',        30,  300), ('Canny Hi',       100,  600),
        ('CLAHE x10',       25,   80), ('Dilate Iter',      2,    6),
        ('Thresh Block',    25,  100), ('Thresh C',         8,   40),
        ('Min W',           10,  300), ('Min H',           10,  300),
        ('Max W',          500, 2000), ('Max H',          500, 2000),
        ('Min Area',       150, 5000), ('Rect Score x100', 40,  100),
        ('IoU Thr x100',    35,  100),
    ]
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    for name, start, mx in bars:
        cv2.createTrackbar(name, WIN, start, mx, lambda _: None)

    print(f'OpenCV Tuning: {path.name}  |  Modus: {cv_mode}')
    last_rects = []

    while True:
        v = {n: cv2.getTrackbarPos(n, WIN) for n, _, _ in bars}
        p = CVParams(
            canny_lo=max(1,v['Canny Lo']), canny_hi=max(2,v['Canny Hi']),
            clahe_clip=max(0.1,v['CLAHE x10']/10), dilate_iter=v['Dilate Iter'],
            thresh_block=max(3,v['Thresh Block']), thresh_c=v['Thresh C'],
            min_w=max(1,v['Min W']), min_h=max(1,v['Min H']),
            max_w=max(v['Min W']+1,v['Max W']), max_h=max(v['Min H']+1,v['Max H']),
            min_area=max(1,v['Min Area']),
            rect_score=v['Rect Score x100']/100, iou_thresh=v['IoU Thr x100']/100,
            cv_mode=cv_mode,
        )
        rects = detect_opencv(bgr, p)
        last_rects = rects
        dbg   = draw_rects(bgr, rects)
        _overlay_info(dbg, f'Fenster: {len(rects)}  |  Modus: {cv_mode}  |  s=Speichern  q=Beenden')
        cv2.imshow(WIN, dbg)
        key = cv2.waitKey(50) & 0xFF
        if key in (ord('q'), 27):
            break
        if key == ord('s'):
            out = save_json(path, last_rects)
            print(f'  Gespeichert: {out}  ({len(last_rects)} Fenster)')

    cv2.destroyAllWindows()


# ── Verarbeitung ───────────────────────────────────────────────────────────────

def process_image(img_path: Path, args, model=None) -> int:
    bgr = cv2.imread(str(img_path))
    if bgr is None:
        print(f'  Warnung: Kann nicht lesen: {img_path}')
        return 0

    method = args.method

    if method == 'openai':
        annotated = get_annotated(img_path, bgr, args.prompt,
                                  force=getattr(args, 'force', False),
                                  model=getattr(args, 'openai_model', OPENAI_MODEL))
        p       = GreenParams()
        windows = detect_openai(annotated, p)
        save_intermediate(img_path, annotated, p.green_thresh)
        out = save_json(img_path, windows)
        n_c = sum(len(w.get('children', [])) for w in windows)
        print(f'  {img_path.name}: {len(windows)} Fenster, {n_c} Glasflaechen -> {out.name}')
        if args.debug:
            show_openai_result(bgr, windows, img_path.name)
        if args.save_debug:
            cv2.imwrite(args.save_debug, draw_openai_result(bgr, windows))
        return len(windows)

    elif method == 'yolo':
        rects = detect_yolo(bgr, model, args.conf, args.iou, args.imgsz)

    else:
        rects = detect_opencv(bgr, CVParams(cv_mode=args.mode))

    out = save_json(img_path, rects)
    print(f'  {img_path.name}: {len(rects)} Fenster -> {out.name}')

    if args.debug:
        show_result(bgr, rects, img_path.name)
    if args.save_debug:
        cv2.imwrite(args.save_debug, draw_rects(bgr, rects))

    return len(rects)


def process_folder(folder: Path, args, model=None):
    images  = sorted(f for f in folder.rglob('*') if f.suffix.lower() in IMAGE_EXTS)
    if not images:
        print('Keine Bilder gefunden.')
        return
    skipped = 0
    for img in images:
        if not args.overwrite and img.with_suffix('.json').exists():
            skipped += 1
            continue
        process_image(img, args, model)
    msg = f'\nFertig: {len(images) - skipped} Bilder verarbeitet'
    if skipped:
        msg += f', {skipped} uebersprungen (--overwrite zum Ueberschreiben)'
    print(msg)


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description='Automatische Fenstererkennung (OpenAI / YOLO / OpenCV).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    grp = ap.add_mutually_exclusive_group()
    grp.add_argument('image', nargs='?', metavar='BILD')
    grp.add_argument('--folder', '-f', metavar='ORDNER')

    ap.add_argument('--method', choices=['openai', 'yolo', 'opencv'],
                    default='openai', help='Erkennungsmethode (Standard: openai)')

    # OpenAI
    oai = ap.add_argument_group('OpenAI')
    oai.add_argument('--prompt', default=OPENAI_PROMPT,
                     help='Prompt fuer OpenAI (Standard: eingebauter Prompt)')
    oai.add_argument('--openai-model', default=OPENAI_MODEL, dest='openai_model',
                     metavar='MODELL',
                     help='OpenAI-Modell (Standard: gpt-image-1, alternativ: dall-e-2)')
    oai.add_argument('--force', action='store_true',
                     help='Cache ignorieren, API erneut aufrufen')

    # YOLO
    yolo = ap.add_argument_group('YOLO')
    yolo.add_argument('--model',   default=DEFAULT_MODEL)
    yolo.add_argument('--classes', nargs='+', default=DEFAULT_CLASSES, metavar='KLASSE')
    yolo.add_argument('--conf',    type=float, default=0.20)
    yolo.add_argument('--iou',     type=float, default=0.45)
    yolo.add_argument('--imgsz',   type=int,   default=640)

    # OpenCV
    ocv = ap.add_argument_group('OpenCV')
    ocv.add_argument('--mode', choices=['edge', 'bright', 'both'], default='both')

    # Allgemein
    ap.add_argument('--tune',       '-t', action='store_true')
    ap.add_argument('--debug',      '-d', action='store_true')
    ap.add_argument('--overwrite',        action='store_true')
    ap.add_argument('--save-debug', metavar='DATEI')

    return ap


def main():
    ap   = build_parser()
    args = ap.parse_args()

    model = None
    if args.method == 'yolo':
        model = load_yolo(args.model, args.classes)

    # Ordner-Modus
    if args.folder:
        folder = Path(args.folder)
        if not folder.is_dir():
            ap.error(f'Ordner nicht gefunden: {folder}')
        print(f'Verarbeite Ordner: {folder}  [Methode: {args.method}]')
        process_folder(folder, args, model)
        return

    if not args.image:
        ap.print_help()
        return

    path = Path(args.image)
    if not path.is_file():
        ap.error(f'Bild nicht gefunden: {path}')

    bgr = cv2.imread(str(path))
    if bgr is None:
        ap.error(f'Kann nicht lesen: {path}')

    # Tuning
    if args.tune:
        if args.method == 'openai':
            annotated = get_annotated(path, bgr, args.prompt,
                                      force=args.force, model=args.openai_model)
            tune_openai(path, bgr, annotated, prompt=args.prompt, model=args.openai_model)
        elif args.method == 'yolo':
            tune_yolo(path, bgr, model, args)
        else:
            tune_opencv(path, bgr, args.mode)
        return

    process_image(path, args, model)


if __name__ == '__main__':
    main()
