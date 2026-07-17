#!/usr/bin/env python3
"""
pdfHouse.py -- Lesen/Schreiben von "Zwei-Ebenen"-Haus-PDFs.

Eingabe (vom Nutzer z.B. in Illustrator erstellt): ein PDF mit einer Seite,
die ein eingebettetes Rasterbild (das Gebaeudefoto) sowie Vektor-Linienzuege
(die von Hand nachgezeichnete Gebaeude-Kontur) enthaelt. Das PDF muss dafuer
KEINE echten PDF-Ebenen (OCG) verwenden -- Bild und Kontur werden einfach als
unterschiedliche Inhaltstypen auf derselben Seite unterschieden und getrennt
extrahiert (Illustrator-interne Ebenen werden beim PDF-Export i.d.R. sowieso
nicht als OCG uebernommen, ausser man aktiviert das explizit).

Ausgabe: eine neue PDF-Datei MIT echten OCG-Ebenen ("Bild" / "Kontur+Scheiben"),
die in Adobe Acrobat einzeln ein-/ausblendbar sind.
"""

import io
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


def load_pdf_house(pdf_path: Path):
    """Liest ein Zwei-Ebenen-Haus-PDF ein. Gibt (image, outline_polylines)
    zurueck:
      - image: PIL.Image des eingebetteten Fotos (das groesste eingebettete
        Rasterbild auf Seite 0), in nativer Pixel-Aufloesung.
      - outline_polylines: Liste von Punktzuegen [[(x,y), (x,y), ...], ...] in
        BILD-PIXEL-Koordinaten (nicht PDF-Punkt-Koordinaten!) -- bereits auf
        die tatsaechliche Foto-Aufloesung umgerechnet, damit sie direkt wie
        Fenster-/Scheiben-Koordinaten weiterverwendet werden koennen.

    Enthaelt die PDF kein eingebettetes Bild, wird ValueError ausgeloest.
    Enthaelt sie keine Vektor-Linien, ist outline_polylines einfach leer."""
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        image, img_rect = _extract_main_image(page)
        outline_polylines = _extract_outline(page, img_rect, image.size)
        return image, outline_polylines
    finally:
        doc.close()


def _extract_main_image(page: "fitz.Page"):
    """Groesstes eingebettetes Rasterbild der Seite als (PIL.Image, Rect
    seiner Platzierung auf der Seite in Punkt-Koordinaten)."""
    infos = page.get_images(full=True)
    if not infos:
        raise ValueError('PDF enthaelt kein eingebettetes Bild')
    doc = page.parent
    best = max(infos, key=lambda info: info[2] * info[3])  # width*height
    xref = best[0]
    rects = page.get_image_rects(xref)
    if not rects:
        raise ValueError('Bild-Platzierung auf der Seite nicht gefunden')
    rect = rects[0]
    raw = doc.extract_image(xref)
    image = Image.open(io.BytesIO(raw['image']))
    image.load()
    if image.mode not in ('RGB', 'RGBA', 'L'):
        image = image.convert('RGB')
    return image, rect


def _extract_outline(page: "fitz.Page", img_rect: "fitz.Rect", img_size: tuple):
    """Alle Vektor-Linienzuege der Seite (die Kontur), umgerechnet von PDF-
    Punkt-Koordinaten in Bild-Pixel-Koordinaten anhand der Platzierung/Groesse
    des Fotos auf der Seite (einfache achsparallele Skalierung -- gedrehte
    oder gescherte Bildplatzierungen werden nicht unterstuetzt)."""
    img_w, img_h = img_size
    sx = img_w / img_rect.width if img_rect.width else 1.0
    sy = img_h / img_rect.height if img_rect.height else 1.0

    def to_image_px(pt):
        return ((pt.x - img_rect.x0) * sx, (pt.y - img_rect.y0) * sy)

    polylines = []
    for drawing in page.get_drawings():
        pts: list = []
        for item in drawing.get('items', []):
            kind = item[0]
            if kind == 'l':
                p1, p2 = item[1], item[2]
                if not pts:
                    pts.append(to_image_px(p1))
                pts.append(to_image_px(p2))
            elif kind == 'c':
                # Bezier-Kurve: nur Start-/Endpunkt uebernehmen (reine
                # Sichtreferenz, keine exakte Pfadgeometrie noetig).
                p1, p4 = item[1], item[4]
                if not pts:
                    pts.append(to_image_px(p1))
                pts.append(to_image_px(p4))
            elif kind == 're':
                rect = item[1]
                corners = [rect.top_left, rect.top_right, rect.bottom_right,
                          rect.bottom_left, rect.top_left]
                if pts:
                    polylines.append(pts)
                pts = [to_image_px(c) for c in corners]
            elif kind == 'qu':
                quad = item[1]
                corners = [quad.ul, quad.ur, quad.lr, quad.ll, quad.ul]
                if pts:
                    polylines.append(pts)
                pts = [to_image_px(c) for c in corners]
        if pts:
            polylines.append(pts)
    return polylines


def save_marked_pdf(out_path: Path, image: Image.Image, outline_polylines: list,
                    panes: list[dict], outline_color=(0.93, 0.11, 0.14),
                    pane_color=(0.29, 0.56, 1.0)):
    """Schreibt ein neues Zwei-Ebenen-PDF mit ECHTEN, in Acrobat einzeln
    ein-/ausblendbaren Ebenen (OCG):
      - "Bild": das Gebaeudefoto.
      - "Kontur+Scheiben": die (unveraendert uebernommene) Gebaeude-Kontur
        PLUS die markierten Glasscheiben-Rechtecke, gemeinsam auf einer Ebene.

    Die Seite wird 1:1 in Bild-Pixel-Punkten angelegt (1 PDF-Punkt = 1 Pixel),
    damit `outline_polylines`/`panes` (beides in Bild-Pixel-Koordinaten) ohne
    weitere Umrechnung direkt als PDF-Koordinaten uebernommen werden koennen."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=image.width, height=image.height)
        ocg_image = doc.add_ocg('Bild', on=True)
        ocg_outline = doc.add_ocg('Kontur+Scheiben', on=True)

        buf = io.BytesIO()
        image.convert('RGB').save(buf, format='PNG')
        page.insert_image(page.rect, stream=buf.getvalue(), oc=ocg_image)

        for pl in outline_polylines:
            if len(pl) >= 2:
                page.draw_polyline(pl, color=outline_color, width=2, oc=ocg_outline)

        for pane in panes:
            rect = fitz.Rect(pane['x'], pane['y'], pane['x'] + pane['w'], pane['y'] + pane['h'])
            page.draw_rect(rect, color=pane_color, width=2, oc=ocg_outline)

        doc.save(str(out_path))
    finally:
        doc.close()
