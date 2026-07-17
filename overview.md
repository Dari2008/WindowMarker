# Beleuchtete Modulkulissen – Projektübersicht

Interaktive TypeScript-Webanwendung zur Konfiguration und Steuerung von beleuchteten Hintergrund-Modulkulissen für Modelleisenbahnen. Entwickelt mit **Vite, TypeScript und Tailwind CSS**, vollständig auf Deutsch.

## Starten

```bash
npm install
npm run dev      # Entwicklungsserver → http://localhost:5173
npm run build    # Produktions-Build → dist/
npm run preview  # Build-Vorschau
```

---

## Projektstruktur

```
BeleuchteteModulKulissen/
├── index.html              # Haupt-Einstiegspunkt
├── package.json
├── tsconfig.json
├── vite.config.ts          # Multi-Page Build (main + control)
├── tailwind.config.js
├── postcss.config.js
│
├── src/
│   ├── main.ts             # Gesamte App-Logik
│   ├── style.css           # Tailwind + Fenster-Animationen
│   └── vite-env.d.ts
│
├── control/
│   ├── index.html          # Stellwerk-Konsole (im Iframe)
│   └── control.ts          # postMessage-Kommunikation
│
├── public/
│   ├── batch_variants.json  # Die EINE LED-Variante (`{"variant": {...}}` --
│   │                        # kein Array/keine Bibliothek mehrerer PCB-Typen
│   │                        # mehr; liegt bewusst NICHT in houses/, s.u.)
│   ├── houses/               # (frueher "images/") -- JEDES Haus in seinem
│   │   ├── images.json      # EIGENEN Unterordner. images.json listet die
│   │   │                    # Unterordnernamen -- wird automatisch von
│   │   │                    # windowTool.py gepflegt (_sync_houses_json),
│   │   │                    # NICHT von Hand!
│   │   └── haus1/
│   │       ├── haus1.pdf        # Gebäude-Zwei-Ebenen-PDF (Foto + Kontur)
│   │       ├── haus1.json       # Fenster-/LED-Metadaten
│   │       ├── haus1.code.json  # kompakte Zweitkodierung fuer Firmware
│   │       ├── haus1.panes.pdf  # Export: Foto + Kontur/Scheiben als PDF-Ebenen
│   │       └── ...
│   └── exported/              # Ziel des kombinierten Projekt-Exports (Tab 2,
│       │                      # Button "Projekt exportieren" ->
│       │                      # ledBatchEditor.App._export_project) -- wird
│       │                      # VOR JEDEM Export komplett GELEERT, damit hier
│       │                      # nie Dateien eines alten Exportlaufs liegen
│       │                      # bleiben. Flach (keine Haus-Unterordner):
│       ├── haus1.dxf                          # LEDs/Footprints (dxfExport.export_dxf)
│       ├── haus1_outline_with_panes.dxf       # Kontur + Fensteroeffnungen
│       ├── haus1_outline.dxf                  # nur die Kontur
│       ├── haus1.csv                          # Stueckliste (csvExport.py), inkl.
│       │                                      # 'filename'-Spalte je Zeile
│       ├── footprint-75x60mm.dxf              # JE tatsaechlich vorkommender
│       └── footprint-10x100mm.dxf             # Footprint-Groesse EINE eigene Datei
```

### Eigene Bilder hinzufügen

Fenster/Scheiben werden **nicht** von Hand ins JSON getippt, sondern mit den
Python-Autoren-Werkzeugen markiert (siehe [„Autoren-Werkzeuge“](#autoren-werkzeuge-python-offline--fenster-markieren--leds-platzieren)
weiter unten):

1. Ein Zwei-Ebenen-PDF erstellen (z. B. in Illustrator: Gebäudefoto platzieren,
   Gebäude-Kontur als Vektor-Linienzug darueber zeichnen, als PDF exportieren)
   und als `public/houses/<name>/<name>.pdf` ablegen (EIGENER Unterordner pro
   Haus). (Legacy: `<name>.jpg`/`.png` funktioniert weiterhin, dann gibt es
   aber keine Kontur-Referenz.)
2. `python windowMarker/windowTool.py` starten, Bild links auswählen, Fenster/
   Scheiben markieren (Tab „Fenster markieren“) – speichert automatisch
   `public/houses/<name>/<name>.json` (+ `.svg`, bei PDF-Quellen zusaetzlich
   `<name>.panes.pdf`).
3. **Nichts weiter!** `public/houses/images.json` wird von `windowTool.py`
   automatisch bei jedem Speichern/Ordnerwechsel neu geschrieben (siehe
   `_sync_houses_json` -- ein Unterordner zaehlt als Haus, wenn er eine
   Bilddatei `<name>.EXT` mit demselben Namen wie der Ordner enthaelt) –
   nicht mehr von Hand pflegen.

Die Website selbst liest aktuell nur das Feld `windows` (`{x, y, w, h}` in
Bild-Pixeln) aus dem JSON – alle anderen Felder (`glassPanes`, `ledBatches`,
`chainOrder`, …) sind Rohdaten der Autoren-Werkzeuge für die spätere
LED-Ansteuerung, siehe unten.

---

## Autoren-Werkzeuge (Python, offline – Fenster markieren & LEDs platzieren)

Zwei lokale Tkinter-Tools erzeugen/pflegen die JSON-Dateien in
`public/houses/<name>/` (je EIN Unterordner pro Haus), bevor ein Gebäude in
der Website benutzt werden kann. Sie laufen **kombiniert in einer
Oberfläche** (empfohlen) oder einzeln.

```bash
cd windowMarker
pip install -r requirements.txt
python windowTool.py     # startet BEIDE Tools kombiniert in 3 Tabs
```

`windowTool.py` startet `_launch_combined()`: ein gemeinsames Tk-Root-Fenster
mit einem `ttk.Notebook` und drei Tabs, die sich Bild/Fenster/Platzierungen
teilen:

| Tab                  | Datei/Klasse                          | Aufgabe |
|-----------------------|----------------------------------------|---------|
| **Fenster markieren** | `windowMarker/windowTool.py` (`App`)   | Fensterrahmen + Glasscheiben per Klick markieren |
| **LED-Batches**       | `ledBatchEditor/led_batch_editor.py` (`App`) | Physische LED-PCBs auf den Fenstern platzieren, an/aus-Zuordnung |
| **LED-Kette**         | dieselbe `App`-Instanz, `build_chain_tab()` | Reihenfolge der Batches zu einer Datenkette verbinden, global durchnummerieren |

### Dateiübersicht

```
windowMarker/
├── windowTool.py          # Haupt-GUI (aktuell) – kombiniert alle 3 Tabs,
│                           # Einstiegspunkt: `python windowTool.py`
├── pdfHouse.py              # Liest/schreibt Zwei-Ebenen-Haus-PDFs (PyMuPDF):
│                           # load_pdf_house() extrahiert Foto + Kontur aus
│                           # dem Eingabe-PDF, save_marked_pdf() schreibt ein
│                           # neues PDF mit echten OCG-Ebenen ("Bild" /
│                           # "Kontur+Scheiben")
├── calcImages.py           # Automatische Vor-Erkennung (OpenAI GPT-Image-1 /
│                           # YOLO-World / OpenCV) + Flood-Fill-Helfer
│                           # (flood_region, largest_rectangle_in_region,
│                           # grow_rect_through_wall, prep_wall), von
│                           # windowTool.py importiert -- laeuft auf dem aus
│                           # dem PDF extrahierten Foto (cv2 kann kein PDF
│                           # direkt einlesen)
├── dxfExport.py            # DXF-Export der platzierten LEDs. get_placed_leds()
│                           # liest direkt aus <name>.json['ledBatches'] (nicht
│                           # aus windows[].ledIndex) -- ein Eintrag
│                           # {'x','y','w','h','ledIndex','variantUuid','width_mm','height_mm'}
│                           # pro AKTIVER LED (teilen sich mehrere LEDs ein
│                           # Fenster, je ein eigener Eintrag mit demselben
│                           # Rechteck; variantUuid = ledBatches[].id, also
│                           # die physische PLATZIERUNG -- alle LEDs EINER
│                           # aufgeloeteten Platine teilen sich eine UUID,
│                           # eine andere Platzierung [auch derselben
│                           # Varianten-ART] bekommt eine andere; 'width_mm'/
│                           # 'height_mm' = ledBatches[].width_mm/height_mm, die
│                           # PRO PLATZIERUNG eintragbare Footprint-Groesse aus
│                           # ledBatchEditor.py's Platzierungskarte -- `None`,
│                           # wenn diese Platzierung keine eigene hat, dann
│                           # gilt der Default der Variante). Die
│                           # Fensterrechtecke stehen im JSON in BILD-PIXELN --
│                           # get_placed_leds() rechnet sie ueber house_data
│                           # ['dpi'] (dpi/25.4, wie ledBatchEditor.px_per_mm)
│                           # in ECHTE mm um, DAMIT SIE DIESELBE EINHEIT WIE
│                           # DIE FOOTPRINT-KONTUR HABEN -- ohne das waeren
│                           # Fensterrechtecke ein Vielfaches ihrer echten
│                           # Groesse (roher Pixelwert als "mm"), wodurch die
│                           # korrekt bemessene Footprint-Kontur daneben
│                           # winzig aussah; house_outline() bekommt denselben
│                           # px_per_mm-Faktor fuer die Gebaeude-Kontur.
│                           # Outline (house_outline()) haelt den EXAKTEN,
│                           # aus dem PDF nachgezeichneten Pfad
│                           # (`polylines`) UND die daraus SELBST berechnete
│                           # Bounding-Box (`left/top/right/bottom`,
│                           # `width`/`height`) -- der Export zeichnet den
│                           # echten Pfad (add_outline_path), die Box bleibt
│                           # fuer einfache Positions-/Groessenberechnungen
│                           # verfuegbar. export_dxf() ist die EINZIGE
│                           # Funktion, die tatsaechlich eine DXF-Datei
│                           # schreibt: nimmt die platzierten LEDs EINES
│                           # Hauses + optionale Outline entgegen, sortiert
│                           # nach Variant-UUID (Rechtecke/Labels derselben
│                           # Platine hintereinander im DXF) und zeichnet
│                           # jede Variant-UUID auf ihrem eigenen ezdxf-Layer
│                           # + eigener (aus der UUID deterministisch
│                           # abgeleiteter) Farbe, damit sich einzelne
│                           # Platinen im CAD-Programm ein-/ausblenden
│                           # lassen; DxfDrawing ist der Komfort-Wrapper
│                           # darunter (Rechtecke/Linien/Linien zwischen
│                           # Rechtecken/Text-Labels/Polylinien fuer den
│                           # exakten Umriss; DxfDrawing.load() oeffnet eine
│                           # bestehende DXF zum Weiterbearbeiten).
│                           # WICHTIG: alle Koordinaten in diesem Modul sind
│                           # BILD-Konvention (Y waechst nach UNTEN, siehe
│                           # get_placed_leds/house_outline) -- add_rect/
│                           # add_line/add_polyline/add_text spiegeln die
│                           # Y-Achse beim Zeichnen INTERN in CAD-Konvention
│                           # (Y waechst nach OBEN, DxfDrawing._fy = einfache
│                           # Negation) um, sonst stuende die exportierte
│                           # Zeichnung in jedem CAD-Programm auf dem Kopf.
│                           # Ausserdem setzt DxfDrawing.__init__ bewusst
│                           # `$INSUNITS = 4` (Millimeter) im Datei-Header --
│                           # ezdxf.new() default'et sonst auf 6 (Meter),
│                           # wodurch jedes einheitenbewusste CAD-/Laser-
│                           # schneide-Programm unsere mm-Werte beim Import
│                           # faelschlich als Meter liest und um den Faktor
│                           # 1000 hochskaliert.
│                           # Pro Variant-UUID (= pro Platzierung) wird
│                           # ausserdem ihre Referenz-Footprint-Kontur
│                           # eingefuegt (_insert_footprints()) -- KEINE
│                           # benannten Footprint-"Typen"/Auswahl mehr, die
│                           # Kontur ist ein GENERIERTES Rechteck (siehe
│                           # footprintScale.py, es gibt keine echten
│                           # Footprint-DXF-Dateien/footprints/-Ordner mehr).
│                           # Die effektive Groesse loest resolve_footprint_size
│                           # (variant_size, leds) auf: erst der PLATZIERUNGS-
│                           # Override (`leds[0]['width_mm']/['height_mm']`,
│                           # siehe get_placed_leds), sonst das an export_dxf()
│                           # uebergebene `variant_size` (Default der Variante,
│                           # `variant['footprint_width_mm']`/
│                           # `['footprint_height_mm']` in
│                           # public/batch_variants.json), sonst FOOTPRINT_WIDTH/
│                           # HEIGHT (75x60mm) -- jede Platzierung/Variante
│                           # traegt ihre Groesse also direkt als Zahl, es kann
│                           # sich (wie gewuenscht) von Fenster zu Fenster
│                           # unterscheiden. _footprint_scaled_points(width_mm,
│                           # height_mm) generiert dazu ueber
│                           # footprintScale.get_footprint_points() ein
│                           # Rechteck in genau dieser Groesse, auf (0, 0)
│                           # normiert. collect_footprint_sizes(entries,
│                           # variant_size) sammelt alle DISTINKTEN
│                           # tatsaechlich vorkommenden Groessen eines Hauses
│                           # (genutzt vom kombinierten Projekt-Export, siehe
│                           # ledBatchEditor.App._export_project, um je Groesse
│                           # eine footprint-WxHmm.dxf zu schreiben);
│                           # format_footprint_size(w, h) formatiert eine
│                           # Groesse als 'WxHmm' (z.B. '10x100mm') -- EIN
│                           # Format fuer diesen Dateinamen UND die
│                           # 'filename'-Spalte in der CSV-Stueckliste (siehe
│                           # csvExport.py), damit beide garantiert
│                           # uebereinstimmen.
│                           # _insert_footprints() wird von export_dxf() UND
│                           # von _draw_outline_with_panes() (fuer die
│                           # Footprint-AUSSCHNITTE auf der Fensterscheiben-
│                           # Kontur) gemeinsam genutzt, damit beide GENAU
│                           # dieselben Positionen zeichnen; ein optionaler
│                           # `layer=`-Parameter haengt alle gezeichneten
│                           # Punktlisten auf EINEN Layer (Default '0'),
│                           # damit _replace_layer_entities() sie beim
│                           # Aktualisieren (edit_outline_with_panes_dxf)
│                           # zuverlaessig wiederfindet, statt sie zu
│                           # duplizieren.
│                           # Mittig ueber der tatsaechlichen Ausdehnung
│                           # ihrer Fenster eingefuegt (`leds` sind
│                           # get_placed_leds()-Eintraege = FENSTER-Rechtecke,
│                           # keine LED-Punktpositionen -- die Spanne reicht
│                           # daher von der linken Kante des am weitesten
│                           # links liegenden Fensters bis zur RECHTEN Kante
│                           # des am weitesten rechts liegenden, `led['x'] +
│                           # led['w']`; eine fruehere Version nahm
│                           # faelschlich nochmal `led['x']` als rechten Rand
│                           # und liess dessen Fensterbreite unter den Tisch
│                           # fallen -- die Platine landete dadurch zu schmal
│                           # berechnet und sichtbar falsch platziert);
│                           # zusaetzlich sitzen die LEDs footprintScale.
│                           # LED_OFFSET_TOP_MM (fester Wert, 7.3mm) unterhalb
│                           # der Footprint-Oberkante (nicht buendig) -- siehe
│                           # _footprint_anchor.
│                           # Zwei EIGENSTAENDIGE Gehaeuseteil-DXFs (je ihr
│                           # eigenes File, NICHT Teil von export_dxf() oben):
│                           #   export_outline_with_panes_dxf(outline, windows,
│                           #     out_path, entries, variant_size) --
│                           #     'Gebaeudekontur mit Fensterscheiben' (Layer
│                           #     OUTLINE_PANES_LAYER = 'HOUSE_OUTLINE_PANES'):
│                           #     der ECHTE Kontur-Pfad MIT ALLEN
│                           #     Fensteroeffnungen aus `windows` (nicht nur
│                           #     den von LEDs beleuchteten wie im Hauptteil
│                           #     oben), PLUS (mit `entries`) je Platzierung
│                           #     ihre Footprint-Kontur als AUSSCHNITT auf
│                           #     eigenem Layer OUTLINE_PANES_FOOTPRINT_LAYER
│                           #     ('HOUSE_OUTLINE_PANES_FOOTPRINTS') -- exakt
│                           #     dieselbe Position wie im LED-/Platinen-
│                           #     Export, siehe _insert_footprints() (von
│                           #     export_dxf() UND hier gemeinsam genutzt,
│                           #     damit beide garantiert uebereinstimmen).
│                           #   export_outline_only_dxf(outline, out_path) --
│                           #     NUR der Kontur-Pfad, ohne Fensteroeffnungen
│                           #     (Layer OUTLINE_ONLY_LAYER = 'HOUSE_OUTLINE').
│                           # Weitere Gehaeuseteile (Seitenteile, Verbinder,
│                           # Rahmenleisten -- siehe csvExport.py fuer deren
│                           # Stueckzahlen) werden bewusst NICHT hier erzeugt,
│                           # sondern vom Nutzer selbst von Hand berechnet und
│                           # ergaenzt.
│                           # edit_outline_with_panes_dxf(outline, windows, path)/
│                           # edit_outline_only_dxf(outline, path) aktualisieren
│                           # stattdessen eine BEREITS exportierte Datei (per
│                           # DxfDrawing.load() geoeffnet): sie loeschen NUR die
│                           # Entities auf ihrem eigenen Layer
│                           # (_replace_layer_entities) und zeichnen sie frisch,
│                           # lassen aber alles, was der Nutzer manuell auf
│                           # ANDEREN Layern in derselben Datei ergaenzt hat
│                           # (z.B. von Hand konstruierte Seitenteile/
│                           # Verbinder), unangetastet -- so kann man in einem
│                           # CAD-Programm an derselben Datei weiterarbeiten,
│                           # ohne dass ein erneuter Export die eigenen
│                           # Ergaenzungen ueberschreibt.
│                           # Den projektweiten Export-Einstiegspunkt (alle
│                           # Haeuser auf einmal) gibt es NICHT mehr in diesem
│                           # Modul -- er lebt als
│                           # ledBatchEditor.App._export_project (kombiniert
│                           # DXF + CSV + footprint-WxHmm.dxf in EINEM Rutsch,
│                           # schreibt in den geleerten public/exported/-Ordner).
├── footprintScale.py        # Erzeugt Footprint-Konturen PROGRAMMATISCH als
│                           # Rechtecke -- es gibt KEINE echten Footprint-DXF-
│                           # Dateien/footprints/-Ordner mehr, jede
│                           # Platzierung/Variante traegt ihre Groesse direkt
│                           # als Zahl (width_mm/height_mm). Genutzt von
│                           # dxfExport.py (Export)
│                           # UND ledBatchEditor/led_batch_editor.py
│                           # (Vorschau, per Cross-Import), damit beide exakt
│                           # dieselbe generierte Geometrie zeigen/exportieren.
│                           # get_footprint_points(width_mm, height_mm)
│                           # erzeugt ein EIGENSTAENDIGES ezdxf-Dokument
│                           # (`ezdxf.document.Drawing`, NICHT gespeichert)
│                           # mit dem rechteckigen Footprint-Umriss (width_mm
│                           # x height_mm) als einzige LWPOLYLINE, auf (0,0)
│                           # normiert -- OHNE jeden Anker-/Verschiebungs-
│                           # Offset (den wendet der Aufrufer SPAETER separat
│                           # an: dxfExport._footprint_scaled_points/
│                           # led_batch_editor._load_footprint_polylines lesen
│                           # dazu die LWPOLYLINE-Punkte aus dessen
│                           # modelspace() aus, bevor _footprint_anchor
│                           # uebersetzt und add_polyline() zeichnet).
│                           # export_all_footprints(sizes, out_dir) --
│                           # zweiter Einstiegspunkt: nimmt {name: (width_mm,
│                           # height_mm)} fuer BELIEBIG VIELE Footprints
│                           # entgegen, ruft fuer jeden get_footprint_points()
│                           # auf und speichert das Ergebnis als eigene
│                           # <name-ohne-.dxf>.dxf nach `out_dir` (nur das
│                           # generierte Rechteck, kein Anker/keine LEDs --
│                           # eigenstaendige Referenz-/Vorlagen-Datei pro
│                           # Groesse). Gibt die Liste der geschriebenen
│                           # Dateipfade zurueck. Aufgerufen vom kombinierten
│                           # Projekt-Export (ledBatchEditor.App._export_project)
│                           # mit `name = f'footprint-{dxfExport.
│                           # format_footprint_size(w, h)}'` fuer jede
│                           # tatsaechlich vorkommende Groesse (siehe
│                           # dxfExport.collect_footprint_sizes) -- es gibt
│                           # keine benannten Footprint-"Typen"/footprints/-
│                           # Configs mehr, welche Groesse gilt, entscheidet
│                           # ausschliesslich dxfExport.resolve_footprint_size.
├── csvExport.py            # Stueckliste (Part-Count) als CSV.
│                           # get_part_counts(house_data, variant, outline,
│                           # house_name) ist DIE zentrale Funktion: gruppiert
│                           # dxfExport.get_placed_leds() nach Platzierung
│                           # (variantUuid = ledBatches[].id -- eine Platine
│                           # zaehlt einmal, unabhaengig von der Anzahl
│                           # aktiver LEDs darauf) und gibt eine Liste von
│                           # {'count','description','filename'}-Dicts zurueck
│                           # ('filename' referenziert die zur Zeile
│                           # gehoerende DXF-Datei, z.B. 'haus1.dxf' oder
│                           # 'footprint-10x100mm.dxf' -- leer ohne `house_name`):
│                           #   1. Gesamtzahl platzierter Platinen
│                           #      (Beschriftung = Variantenname, filename =
│                           #      '<house_name>.dxf').
│                           #   2. davon NAHE DER BODENKANTE des Hauses --
│                           #      Ueberschneidung mit dem unteren
│                           #      BOTTOM_THRESHOLD_MM=40mm(4cm)-Streifen der
│                           #      Gebaeude-Kontur (Outline.bottom, siehe
│                           #      dxfExport.house_outline).
│                           #   3.-n. Seitenteile/Innere Seitenteile JE
│                           #      TATSAECHLICH VORKOMMENDER Footprint-Groesse
│                           #      (dxfExport.resolve_footprint_size je
│                           #      Platzierung aufgeloest, dann nach (width_mm,
│                           #      height_mm) gruppiert -- KEINE benannten
│                           #      Footprint-"Typen"/Big-Small-Keyword-Suche
│                           #      mehr): je SIDE_PIECES_PER_PLACEMENT=2 bzw.
│                           #      INNER_SIDE_PIECES_PER_PLACEMENT=2 PRO
│                           #      Platzierung dieser Groesse, benannt
│                           #      "Seitenteile (WxHmm)"/"Innere Seitenteile
│                           #      (WxHmm)" (dxfExport.format_footprint_size)
│                           #      mit filename = 'footprint-WxHmm.dxf' --
│                           #      unterschiedliche Groessen sind physisch
│                           #      unterschiedlich gross, daher getrennte
│                           #      Zeilen trotz gleichem Multiplikator.
│                           #   n+1. Verbinder -- bei JEDER Groesse PHYSISCH
│                           #      IDENTISCH, daher NUR EINE Zeile ueber ALLE
│                           #      Platzierungen (CONNECTORS_PER_PLACEMENT=1).
│                           #   n+2.-n+4. Feste Haus-Stueckzahlen (nur mit
│                           #      Outline): je OUTLINE_WITH_PANES_COUNT/
│                           #      OUTLINE_HORIZONTAL_COUNT/
│                           #      OUTLINE_VERTICAL_COUNT=2 -- unabhaengig
│                           #      von der Zahl der LED-Platzierungen. NUR die
│                           #      "Gebaeudekontur mit Fensterscheiben" hat
│                           #      auch ein zugehoeriges DXF-Teil
│                           #      (dxfExport.export_outline_with_panes_dxf/
│                           #      export_outline_only_dxf) -- die Rahmenleisten
│                           #      ("Kontur horizontal"/"Kontur vertikal")
│                           #      werden bewusst NICHT automatisch als DXF
│                           #      erzeugt, der Nutzer berechnet/ergaenzt sie
│                           #      selbst.
│                           # export_csv() schreibt eine solche Liste als
│                           # CSV (Spalten: count, description, filename).
│                           # Den projektweiten Export-Einstiegspunkt (alle
│                           # Haeuser auf einmal) gibt es NICHT mehr in diesem
│                           # Modul -- er lebt als
│                           # ledBatchEditor.App._export_project (Toolbar-
│                           # Button "Projekt exportieren", kombiniert DXF +
│                           # CSV + footprint-WxHmm.dxf in EINEM Rutsch).
├── interactiveMarker.py    # Aeltere CLI/OpenCV-Variante ohne GUI-Ordnerliste
│                           # – durch windowTool.py abgeloest, nur als Referenz
├── windowMarker.py         # Aeltere, einfache Marker-GUI ohne LED-Tabs
│                           # – durch windowTool.py abgeloest
└── extractWindows.py       # Einmaliges Dev-Hilfsskript (fest auf haus1
                            # verdrahtet), kein Teil des regulaeren Workflows

ledBatchEditor/
├── led_batch_editor.py     # LED-Varianten, Platzierung, Auto-Zuordnung,
│                           # Kette – einzeln lauffaehig ODER eingebettet in
│                           # windowTool.py's Tabs 2+3; importiert pdfHouse.py
│                           # ueber sys.path (optional -- ohne pymupdf bleibt
│                           # nur der JPG/PNG-Ladeweg nutzbar)
└── README.md                # ⚠ veraltet – beschreibt noch den alten
                              # Rechteck-Ziehen-Workflow; der tatsaechliche
                              # aktuelle Ablauf steht unten in diesem Dokument

public/
├── batch_variants.json      # Die EINE LED-Variante (`{"variant": {...}}`,
│                             # ueber alle Bilder hinweg dieselbe -- keine
│                             # Bibliothek mehrerer benannter PCB-Typen mehr,
│                             # kein Array) -- bewusst NICHT in images/
│                             # (siehe images.json-Autosync: der Ordner soll
│                             # nur Haus-Dateien enthalten)
└── images/
    ├── <name>.pdf            # Zwei-Ebenen-Gebaeude-PDF (Foto + Kontur,
    │                         # z.B. aus Illustrator) -- aktueller Workflow;
    │                         # <name>.jpg/.png funktioniert als Fallback
    │                         # weiterhin (dann ohne Kontur-Referenz)
    ├── <name>.json           # Pro Bild: Fenster, Scheiben, LED-Platzierungen,
    │                         # Kette (volles Schema siehe unten)
    ├── <name>.code.json      # Kompakte Zweitkodierung (siehe unten)
    ├── <name>.panes.pdf      # Export von windowTool.py (nur PDF-Quellen):
    │                         # neues PDF mit den OCG-Ebenen "Bild" (Foto) und
    │                         # "Kontur+Scheiben" (Kontur + markierte Scheiben)
    ├── <name>.svg            # Scheiben-Overlay-Export von windowTool.py
    │                         # (weiterhin fuer ALLE Quellen, auch PDF)
    ├── <name>._annotated.png # Von calcImages.py erzeugtes Overlay (gruen =
    │                         # Fensterrahmen, rot = Scheiben-Kanten)
    ├── <name>._greenmask.png # Extrahierte Fensterrahmen-Maske
    ├── <name>._redmask.png   # Extrahierte Scheiben-Kanten-Maske
    └── images.json            # Liste der von der Website geladenen Segmente --
                              # wird automatisch von windowTool.py gepflegt
                              # (_sync_images_json), NICHT von Hand
```

DXF-/CSV-Export landet NICHT mehr in diesem Ordner -- siehe
`public/exported/` (Tab 2, Button "Projekt exportieren") weiter oben.

### Workflow

1. **Fenster markieren** (Tab 1): Bild auswählen. Bei einer `.pdf`-Quelle
   extrahiert `pdfHouse.load_pdf_house()` das eingebettete Foto UND die von
   Hand nachgezeichnete Gebäude-Kontur (Vektor-Linienzuege auf derselben
   PDF-Seite) und rechnet die Kontur-Koordinaten anhand der Platzierung des
   Fotos auf der Seite in Bild-Pixel um; die Kontur wird als feste, orange
   gestrichelte Referenz-Ebene **immer sichtbar und NICHT editierbar**
   angezeigt (kein Klick-Handling darauf – die eigentliche Markierung
   arbeitet weiterhin per Flutfuellung auf den Bildpixeln). Die Erkennung
   laeuft NICHT mehr automatisch beim Laden – erst ein Klick auf
   **„Fenster erkennen“** (nutzt den `._annotated.png`-Cache, falls vorhanden)
   oder **„Fenster neu erkennen“** (erzwingt einen frischen OpenAI-Aufruf)
   schickt das (aus dem PDF extrahierte, oder bei JPG/PNG das Original-)Foto
   an OpenAI/YOLO/OpenCV und erzeugt ein Overlay mit gruenen Fensterrahmen-
   und roten Scheiben-Kanten-Linien; ein Klick zum Markieren VOR der ersten
   Erkennung zeigt stattdessen nur einen Hinweis („Bitte zuerst Fenster
   erkennen lassen“), statt abzustuerzen. Klick in eine Scheibe
   flutet den von roten Linien umschlossenen Bereich (Glasscheibe) und
   zusaetzlich den von gruenen Linien umschlossenen Bereich (Fensterrahmen).
   Ein Fenster **ohne** lokale blaue/rote Unterteilung (z. B. ein einzelnes
   ungeteiltes Fenster) fällt beim gezielten Einzelklick automatisch auf den
   gesamten gelben Rahmen zurück und wird als Fenster **und** als Glasscheibe
   gespeichert. Rechtsklick lässt die Scheibe ueber die rote Kante hinaus
   „wachsen“ (`grow_rect_through_wall`). Speichert automatisch (debounced)
   `windows` + `glassPanes` in `<name>.json` und die Scheiben zusätzlich als
   `<name>.svg`; bei PDF-Quellen zusaetzlich als `<name>.panes.pdf`
   (`pdfHouse.save_marked_pdf()`) – ein neues PDF mit zwei ECHTEN, in Acrobat
   einzeln ein-/ausblendbaren Ebenen (OCG): „Bild“ (das Foto) und
   „Kontur+Scheiben“ (die uebernommene Kontur plus die markierten
   Glasscheiben-Rechtecke gemeinsam).
2. **Die LED-Variante bearbeiten** (Tab 2, Toolbar „Bearbeiten...“): es gibt
   bewusst nur EINE LED-Variante (keine Bibliothek mehrerer benannter
   PCB-Typen, kein Auswahl-Dropdown) -- der Button oeffnet direkt den
   Varianten-Designer fuer diese eine Variante (legt sie beim ersten Mal an).
   Im Designer jede LED der physischen PCB anklicken (1 Kästchen = 10 mm,
   echte mm-Masse, keine Verzerrung). Klickreihenfolge = Kettenreihenfolge
   auf der Platine. Als Orientierung wird zusaetzlich eine GENERIERTE
   Footprint-Kontur eingeblendet (ein Rechteck, siehe
   `windowMarker/footprintScale.py` -- es gibt KEINE echten Footprint-DXF-
   Dateien und KEINE benannten Footprint-"Typen"/Auswahl-Combobox mehr) --
   **die Groesse** wird direkt als Zahl in zwei Eingabefeldern „B×H (mm)“
   oben eingetragen (`self.v_footprint_w`/`self.v_footprint_h`, committed
   per Enter/Fokusverlust ueber `_on_footprint_size_commit`), gespeichert als
   `variant['footprint_width_mm']`/`['footprint_height_mm']`; fehlen sie
   (alte Varianten), gilt der Fallback `FOOTPRINT_WIDTH`/`HEIGHT` = 75×60mm.
   Der Abstand von der LED-Reihe zur Footprint-Oberkante ist EIN fester,
   globaler Wert `footprintScale.LED_OFFSET_TOP_MM` = 7.3mm (kein
   konfigurierbares Feld mehr) -- siehe `windowMarker/footprintScale.py`
   (`get_footprint_points`), von hier UND `dxfExport.py` gemeinsam genutzt,
   damit Vorschau und spaeterer Export exakt uebereinstimmen. Die generierte
   Kontur wird pro (width_mm, height_mm)-Groesse gecacht (siehe
   `_load_footprint_polylines`) und mittig ueber der tatsaechlichen
   LED-Ausdehnung zentriert (inkl. `LED_WIDTH_MM` = 5 mm Gehaeusebreite je
   LED, `LED_OFFSET_TOP_MM` als vertikaler Versatz -- siehe
   `_footprint_anchor`, identische Rechnung wie beim spaeteren DXF-Export in
   `windowMarker/dxfExport.py`); rein visuelle Referenz, kein eigenes
   Klick-/Zieh-Ziel.
   Zwei schwarze, massstabsgetreue 5×8 mm Kaesten (`CONNECTOR_W_MM` /
   `CONNECTOR_H_MM`) markieren die Kabelverbinder der Platine zur
   Orientierung: **DIN** (Daten-Eingang) automatisch bei (0,0), **DOUT**
   (Daten-Ausgang) automatisch kurz hinter der LETZTEN LED IN KLICK-/
   KETTENREIHENFOLGE (hoechster Index, Abstand = `CONNECTOR_W_MM`, also
   ungefaehr die eigene Kastenbreite) – massgeblich ist dabei die
   Reihenfolge, in der die LEDs angeklickt wurden, NICHT ihre raeumliche
   Position (bei einem nicht streng von links nach rechts angeklickten
   Layout waere „die LED mit dem groessten x_mm“ sonst nicht dieselbe wie
   „die letzte LED der Kette“). Beide Kaesten lassen sich auch **von Hand
   ziehen** (genau wie LEDs: Klick+Ziehen auf den Kasten selbst), falls die
   physische Platine ihre Verbinder nicht an der automatisch berechneten
   Stelle hat -- eine gezogene Position wird als `din_mm`/`dout_mm` (mm,
   im rohen Varianten-Koordinatensystem) auf der Variante gespeichert und
   ueberschreibt fortan die Automatik (`connector_positions()` in
   `led_batch_editor.py`); Rechtsklick auf einen verschobenen Anschluss
   setzt ihn wieder auf automatisch zurueck. Zusaetzlich zum Ziehen auf dem
   Raster erscheinen DIN/DOUT auch als eigene Kartenreihen ganz oben in der
   LED-Liste rechts (`_render_connector_card`), mit demselben editierbaren
   X/Y-Feld-Layout wie eine LED-Karte, aber bewusst amberfarbenem statt
   blaugrauem Hintergrund, damit sie auf den ersten Blick nicht mit der
   eigentlichen LED-Kette verwechselt werden; ein Klick auf eine Karte waehlt
   sie aus (Hervorhebung auf dem Canvas), ein „(auto)“-Hinweis zeigt den
   automatischen Status, ein ↺-Button erscheint stattdessen, sobald die
   Position von Hand gesetzt wurde. Ohne manuelle Verschiebung (weder per
   Ziehen noch per Eingabefeld) bleibt das Verhalten exakt wie zuvor (kein
   `din_mm`/`dout_mm` im JSON). Gespeichert in `batch_variants.json`.
3. **Batches platzieren** (Tab 2): Werkzeug **„✛ Variante platzieren“** im
   schwebenden Werkzeug-Panel oben rechts ueber dem Canvas aktivieren
   (Checkbutton -- alle vier Werkzeuge „💡 LED umschalten“/„✛ Variante
   platzieren“/„📏 Messen“/„📐 Skalieren“ leben dort statt in der oberen
   Toolbar, siehe `tools_panel`/`_build`: die Toolbar wurde mit Variante/
   Footprint/DPI/Export-Buttons zu voll, das Panel schwebt per `place()`
   automatisch in der Ecke), dann aufs Bild klicken (es gibt nur die
   eine Variante, keine Auswahl mehr noetig) – die LED-Reihe rastet
   automatisch an die Oberkante **aller** dort beruehrten Fenster ein
   (`_snap_anchor`, `SNAP_PX`/`WINDOW_TOL` = 14 px). Zusaetzlich zu den LEDs
   und den Verbinder-Kaesten wird auch hier die echte Footprint-Kontur an
   jeder Platzierung mitgezeichnet (`_draw_footprint`, dieselbe Zentrierung
   wie im Designer, inkl. Spiegelung bei geflippten Platzierungen). Jede
   platzierte Batch kann dabei ihre EIGENE Footprint-Groesse bekommen --
   ueberschreibt den Default der Variante nur fuer DIESE eine Platzierung
   (z.B. weil eine bestimmte Platzierung eine andere physische Platine
   braucht, siehe `resolve_footprint_size`), auf ZWEI Wegen (beide als
   direkte B×H-Zahlenfelder, KEINE benannte Auswahl-Combobox mehr):
   - **Vorab, fuer die NAECHSTE Platzierung**: zwei B×H-Eingabefelder ganz
     links in der Toolbar (`self.v_next_footprint_w`/`_h`,
     `_next_footprint_size()`) -- leer = folgt der Variante, oder eine
     eigene Groesse eintragen; jede neue Platzierung, die man danach mit
     dem „✛ Variante platzieren“-Werkzeug anlegt, bekommt diese Groesse
     sofort mit (auch die Schattenvorschau vorm Klick zeigt schon die
     gewaehlte Footprint-Vorschau). So lassen sich hintereinander mehrere
     Platzierungen DERSELBEN Variante mit UNTERSCHIEDLICHEN Groessen
     anlegen, ohne jede einzeln danach umstellen zu muessen.
   - **Nachtraeglich, fuer EINE bestehende Platzierung**: jede Karte in der
     Liste „Platzierte Batches“ rechts hat eigene B×H-Eingabefelder
     (`_add_card`), leer = folgt der Variante.

   Eine eingetragene Groesse wird als `width_mm`/`height_mm` auf der
   Platzierung selbst gespeichert (`ledBatches[].width_mm`/`height_mm` im
   JSON, NICHT auf der Variante) und fliesst sowohl in die Tab-2-Vorschau
   (`footprint_image_points(..., placement=p)`) als auch in den spaeteren
   DXF-Export ein (`dxfExport.get_placed_leds()` traegt die Felder pro LED
   durch, `export_dxf()`/`resolve_footprint_size()` verwenden sie PRO
   PLATZIERUNGS-GRUPPE anstelle des Variant-Defaults).

   Jede Karte in der Liste „Platzierte Batches“ hat ausserdem einen Button
   **„🎯 Auf beleuchtete Fenster zentrieren“** (`_center_placement_on_lit_windows`):
   zentriert die Platzierung horizontal zwischen ALLEN Fenstern, die sie
   GERADE JETZT beleuchtet (deren Index von einer ihrer aktiven LEDs
   referenziert wird, `led['windowIndex']`) -- unabhaengig von der
   automatischen Gruppierung aus `_auto_place`, jederzeit von Hand fuer eine
   einzelne bereits platzierte Variante anwendbar (z.B. nachdem man sie
   manuell verschoben oder Fenster nachtraeglich geaendert hat). Beleuchtet
   die Platzierung aktuell KEIN Fenster (keine aktive LED mit `windowIndex`),
   passiert nichts -- eine Statusmeldung weist darauf hin, statt still gar
   nichts zu tun.

   Der halbtransparente „Schatten“ unter dem Mauszeiger (nur bei aktivem
   Werkzeug sichtbar) zeigt schon vor dem Klick an, welche LEDs an dieser
   Stelle an (gelb) bzw. aus (grau) waeren, sowie die (gerastert
   gezeichneten) DIN-/DOUT-Kaesten an der Platzierungsposition. Ohne
   aktives Werkzeug waehlt/verschiebt ein Klick nur bestehende
   Platzierungen – es wird nichts Neues platziert. Jede platzierte Batch
   zeigt ihre beiden 5×8 mm Verbinder-Kaesten (DIN/DOUT) auch direkt auf
   dem Foto (nicht nur im Varianten-Designer).
   **Leertaste antippen** (kurz, nicht halten) spiegelt die Ausrichtung: ist
   gerade eine bestehende Platzierung ausgewaehlt, wird DIESE gespiegelt;
   sonst die Ausrichtung der naechsten, noch zu platzierenden Variante
   (`place_flipped`, auch als Checkbox „Neue Platzierung spiegeln“ sichtbar).
   Leertaste HALTEN+ziehen pannt stattdessen das Bild. Alle Toolbar-Buttons
   haben bewusst `takefocus=0`, damit ein Klick auf sie den Tastaturfokus
   NICHT von der Zeichenflaeche wegnimmt (sonst wuerde die eingebaute
   `<space>`-Klassenbindung des zuletzt angeklickten Buttons dessen eigenen
   Zustand nochmal umschalten, statt nur die Ausrichtung zu spiegeln).
4. **An/Aus-Zuordnung**: automatisch (`_auto_assign`) – pro Fenster bleibt nur
   die LED am naechsten zur Fenstermitte aktiv, alle anderen dort andockenden
   LEDs werden deaktiviert; **Ausnahme**: beruehren mehrere LEDs ein Fenster
   mit einer Spannweite **≥ 30 mm**, bleiben ALLE aktiv (ein grosses Fenster
   braucht mehr als eine mittige Lampe). LEDs, die kein Fenster beruehren,
   bleiben immer deaktiviert.
   Manuell übersteuern: Werkzeug **„💡 LED umschalten“** aktivieren (gegenseitig
   exklusiv zu „Variante platzieren“) – Klick auf eine LED kippt ihren
   aktuellen Zustand **dauerhaft** fest um (`manual: true`), unabhängig von der
   automatischen Konkurrenz um ein Fenster. Alternativ jederzeit (auch ohne
   aktives Werkzeug): Rechtsklick auf eine LED = derselbe Toggle;
   Shift+Rechtsklick setzt sie zurück auf automatisch. Manuelle Overrides
   überleben Speichern/Neuladen.
   Werkzeug **„📏 Messen“** (Tab 2, gegenseitig exklusiv zu den anderen
   Werkzeugen): Klicken+Ziehen zieht ein Massband zwischen zwei
   Punkten auf dem Foto und zeigt den echten Abstand in mm (ueber
   `px_per_mm`) an dessen Mitte -- zum Nachmessen z.B. von Fensterbreiten
   oder LED-Abstaenden, ohne dabei eine Platzierung anzulegen. Es existiert
   immer nur EIN Massband gleichzeitig (ein neuer Zug ersetzt das alte); es
   verschwindet beim Umschalten auf ein anderes Werkzeug oder mit Escape
   (`_draw_measure`/`_cv_dn`/`_cv_mv`/`_cv_up` in `led_batch_editor.py`).
   Werkzeug **„📐 Skalieren“** (Tab 2, ebenfalls exklusiv): Klicken+Ziehen
   zwischen zwei Punkten mit bekanntem realen Abstand (z.B. eine Fenster-
   breite von 10 cm), beim Loslassen fragt ein Dialog „Wie viele mm soll
   diese Strecke sein?“ -- daraus wird die DPI direkt neu berechnet
   (`dpi = gemessene_px / eingegebene_mm * 25.4`) und uebernommen (setzt
   `self.dpi`/das DPI-Eingabefeld, loest `_auto_assign()`+Speichern aus).
   Ein Klick ohne Ziehen (Strecke ~0 px) oder Abbrechen des Dialogs aendert
   nichts (`_finish_scale_drag`/`_ask_real_distance_mm`). Praktisch, wenn
   die tatsaechliche Aufloesung/der Massstab eines Fotos unbekannt ist, aber
   eine bekannte Referenzstrecke darin sichtbar ist.
5. **🪄 Auto platzieren** (Tab 2, Toolbar-Button rechts): platziert
   automatisch je EINE Batch pro Cluster von HOECHSTENS 3 raeumlich
   benachbarten Fenstern (`_cluster_windows_into_groups`: clustert erst per
   `_group_windows_into_rows` nach Oberkante-y, Toleranz
   `AUTO_PLACE_ROW_TOL_PX`, dann innerhalb jeder Reihe -- nach x sortiert --
   in aufeinanderfolgende Dreiergruppen; die letzte Gruppe einer Reihe darf
   dabei WENIGER als 3 Fenster haben, wenn die Reihenlaenge nicht durch 3
   teilbar ist -- es wird nie ein Fenster verworfen/unplatziert gelassen).
   ALLE erzeugten Platzierungen verwenden dieselbe Footprint-Groesse (den
   Default der Variante, siehe `resolve_footprint_size`) -- es gibt KEINE
   Sonderbehandlung/Aufteilung nach Distanz zur Gebaeude-Unterkante mehr
   (fruehere "Footprint-Big"-fuer-bodennahe-Fenster/"-Small"-sonst-Logik
   samt `_split_bottom_windows`/`_find_footprint_by_keyword` wurde entfernt,
   seit es keine benannten Footprint-Typen mehr gibt); eine abweichende
   Groesse fuer einzelne Platzierungen traegt man danach von Hand ein (siehe
   Schritt 3, B×H-Eingabefelder). Horizontal wird jede Gruppe
   NICHT stur zentriert, sondern so ausgerichtet, dass MOEGLICHST VIELE
   VERSCHIEDENE Fenster der Gruppe von je einer LED beruehrt werden
   (`_best_group_anchor_x`): der feste LED-Abstand der Variante kann
   naemlich nicht gestreckt/gestaucht werden, passt also nicht
   zwangslaeufig zum tatsaechlichen Fensterabstand -- liegt z.B. eine Tuer
   zwischen zwei Fenstern der Gruppe, wuerde stures Zentrieren (an der
   Gruppen-Bounding-Box) leicht dazu fuehren, dass mehr LEDs ins Leere
   treffen als noetig. Bewertet wird bewusst die Anzahl DISTINKTER
   beruehrter Fenster, NICHT die rohe Anzahl beruehrender LEDs: bei stark
   unterschiedlich breiten Fenstern in einer Gruppe (z.B. ein breites
   Schaufenster neben einem schmaleren) wuerden sonst alle 3 LEDs bequem in
   EINEM breiten Fenster (Trefferzahl 3) hoeher bewertet als je eine LED in
   zwei verschiedenen Fenstern (Trefferzahl 2) -- das haette die ganze
   Platine auf das breite Fenster zusammengezogen (samt sichtbarem
   Ueberstand ueber dessen Kante) und ein daneben liegendes, genauso zur
   Gruppe gehoerendes Fenster komplett unbeleuchtet gelassen. Geprueft
   werden alle Anker, bei denen irgendeine LED exakt auf die Mitte
   irgendeines Fensters der Gruppe faellt (das Maximum liegt immer an so
   einer Ausrichtung), plus der naiv zentrierte als Fallback; bei gleicher
   Anzahl distinkter Fenster gewinnt der Kandidat naeher am naiv zentrierten
   Anker (z.B. wenn die Fenster der Gruppe weiter auseinanderliegen als die
   LED-Spannweite und ohnehin kein Anker mehr als eines beruehren kann --
   dann landet die Platine lieber sichtbar mittig zwischen den Fenstern als
   hart an eines herangezogen). Es ist also normal und beabsichtigt, wenn
   z.B. bei einer Dreiergruppe mit Tuer in der Mitte nur die 1. und 3. LED
   ein Fenster treffen und die 2. dunkel bleibt. Vertikal wird weiterhin
   an die Gruppen-Oberkante angelegt (`_auto_place`). Ueberschreibt alle
   bestehenden Platzierungen -- fragt vorher nach Bestaetigung.
   Direkt im Anschluss wird auch die Verbindungsreihenfolge automatisch neu
   berechnet (`_auto_connect_chain`): eine gierige Naechster-Nachbar-
   Heuristik startet bei der Platzierung, an die der Eingangs-Knoten
   angeschlossen wird (unterste Reihe, horizontal am naechsten zur
   Gebaeudemitte -- siehe `_find_bottom_center_placement`) und haengt danach
   immer die (nach DIN-Position) naechstgelegene noch unverbundene
   Platzierung an das DOUT der zuletzt angehaengten an -- minimiert dadurch
   jeden einzelnen Kabelabschnitt (der beste Weg, moeglichst keine
   Verbindung ueber `MAX_CONNECTION_MM` zu ziehen, garantiert es aber nicht,
   falls Platzierungen schlicht zu weit auseinander liegen -- das faellt
   dann als rote Verbindung im Ketten-Tab auf). Der verankerte Start
   garantiert, dass `chain_order[0]` immer die an den Eingangs-Knoten
   angeschlossene Platzierung ist (siehe Punkt 7).
6. **Kette verbinden** (Tab 3, „LED-Kette“): Wie in Tab 2 lässt sich das Bild
   mit dem Mausrad zoomen und mit der mittleren Maustaste verschieben (auch
   Zoom-`+`/`−`-Buttons und „Anpassen“ in der Toolbar). Klick auf einen Batch
   haengt ihn ans Ende der expliziten Verbindungsreihenfolge (`chain_order`),
   Rechtsklick entfernt ihn wieder (dann faellt er in die automatische
   Links-nach-rechts-Sortierung nach x-Position zurueck). ▲/▼ vertauscht
   benachbarte Eintraege.
   Jede Kabel-Verbindungslinie zwischen DOUT einer Platine und DIN der
   naechsten ist IMMER mit ihrer tatsaechlichen Laenge beschriftet (mm,
   `_draw_chain_wire`); ueberschreitet sie dabei `MAX_CONNECTION_MM`
   (100 mm / 10 cm -- die physisch verfuegbare/zulaessige Kabellaenge), wird
   sie ROT statt amber gezeichnet und die Beschriftung zeigt zusaetzlich
   „⚠“. Die Toolbar zeigt ausserdem eine zusammenfassende Warnung
   „⚠ N Verbindung(en) > 100mm“, sobald mindestens eine Verbindung zu lang
   ist (`_render_chain_cv`/`_v_chain_warn`). Rein visuelle Warnung --
   verhindert nicht das Verbinden/Verschieben, macht aber sofort sichtbar,
   welche Platzierungen zu weit auseinander liegen.
   Ganz an den ANFANG der Kette (das ERSTE Glied in `_ordered_placements()`-
   Reihenfolge, also `chain_order[0]`) wird ausserdem ein **Eingangs-Knoten**
   angeschlossen: ein schwarzer Kasten (echte
   `INPUT_NODE_W_MM`×`INPUT_NODE_H_MM` = 8×5 mm, Beschriftung „IN“) an der
   Mitte der Unterkante der Gebaeude-Kontur (`_get_input_node_pos()` --
   liest dieselbe PDF-Kontur wie windowTool.py, NICHT im JSON gespeichert,
   sondern pro `img_path` gecacht neu gelesen). Die Kette wird von hier aus
   gespeist -- deshalb verankert `_auto_connect_chain` den Kettenstart
   bewusst auf die Platzierung der untersten Reihe, die horizontal am
   naechsten zur Gebaeudemitte liegt (`_find_bottom_center_placement`),
   statt (wie frueher) bei einer beliebigen obersten/linkesten Platzierung
   zu beginnen. Auch diese erste Verbindung (Knoten -> DIN von
   `chain_order[0]`) wird mit Laenge beschriftet und ggf. rot markiert wie
   jede andere.

   Werkzeug **„🔗 LEDs gruppieren“**: Klick auf eine (Fenster-zugeordnete) LED
   merkt sie als Anker vor (blauer Ring), Klick auf eine ANDERE
   Fenster-zugeordnete LED laesst diese die Fensterzuordnung der ersten
   uebernehmen – beide teilen sich danach ein Fenster/einen `pixelIndex`, auch
   wenn sie urspruenglich zwei verschiedene Fenster versorgt haben. Ein
   nochmaliger Klick auf den bereits gewaehlten Anker verwirft die Auswahl
   wieder. Rechtsklick auf eine LED (bei aktivem Werkzeug) loest sie wieder
   aus jeder manuellen Gruppierung/Uebersteuerung – `_auto_assign` bestimmt
   ihre Fensterzuordnung danach wieder rein geometrisch selbst. Wichtig:
   `_auto_assign` fasst bei `manual: true` weder `enabled` NOCH `windowIndex`
   an (fruehere Version ueberschrieb `windowIndex` bei jedem Aufruf trotzdem
   geometrisch und machte die manuelle Gruppierung dadurch sofort wieder
   rueckgaengig).
   Die gestrichelte, gelbe Verbindungslinie zwischen zwei aufeinanderfolgenden
   Batches laeuft dabei vom **DOUT** (Daten-Ausgang) der einen Platine zum
   **DIN** (Daten-Eingang) der naechsten – nicht von LED zu LED und nicht
   Ursprung-zu-Ursprung: das physische Kabel wird ja am jeweiligen Verbinder
   angeschlossen. Wuerde man stattdessen DIN mit DIN verbinden, zickzackte die
   Linie bei gespiegelten Platzierungen quer durch die Platzierung (DIN
   springt beim Spiegeln auf die jeweils andere Seite). Daraus berechnet
   `_recompute_chain` global 0..N-1 durchnummerierte `chainIndex`-Werte je LED
   (physische Position auf der Datenleitung), traegt bei aktiven LEDs
   `ledIndex`/`pixelIndex` ins zugehoerige Fenster ein und sammelt alle nicht
   zugeordneten/deaktivierten Indizes in `disabledLeds`. Die Zahl ueber jeder
   Lampe in diesem Tab zeigt NICHT den einzelnen `chainIndex`, sondern den
   logischen `pixelIndex` (zaehlt pro versorgtem Fenster ab dem Daten-Eingang
   hoch -- mehrere LEDs desselben Fensters zeigen dieselbe Zahl; LEDs ohne
   Fenster bleiben unbeschriftet).
   Aus derselben Berechnung ergibt sich `dataChain`: eine geordnete Liste (ein
   Eintrag pro logischem Pixel, in Reihenfolge ab Daten-Eingang), in der jeder
   Eintrag IMMER als `"<from>-<to>"`-String den physischen `chainIndex`-Bereich
   der daran beteiligten LED(s) angibt -- auch bei nur einer einzelnen LED
   (z. B. `"23-23"`), damit das Format durchgehend einheitlich bleibt.
7. Fenster, die in Tab 1 nachträglich geändert werden, während Tab 2/3 schon
   offen sind, werden bei jedem Tab-Wechsel automatisch neu von der Platte
   geladen (`_reload_windows`) – kein manuelles Neuladen des Bildes nötig.

### JSON-Schema (`public/houses/<name>/<name>.json`)

Reales Beispiel (gekürzt, aus `haus1.json`):

```json
{
  "name": "haus1",
  "dpi": 150.0,
  "windows": [
    { "x": 958, "y": 159, "w": 59, "h": 71, "ledIndex": 23, "pixelIndex": 12 }
  ],
  "glassPanes": [
    { "x": 965, "y": 165, "w": 16, "h": 22 }
  ],
  "ledBatches": [
    {
      "id": "d605a6ae",
      "variantId": "70mm",
      "x": 165.2, "y": 569.0,
      "flipped": false,
      "leds": [
        { "index": 0, "chainIndex": 6, "pixelIndex": 3,    "enabled": true,  "windowIndex": 9,    "manual": false },
        { "index": 1, "chainIndex": 7, "pixelIndex": null, "enabled": false, "windowIndex": null, "manual": false }
      ]
    }
  ],
  "chainOrder": ["a8d7bd3c", "d605a6ae", "36e16d24", "c1b4cfb0"],
  "disabledLeds": [1, 3, 4, 7, 9, 10],
  "totalLedCount": 78,
  "totalPixelCount": 71,
  "dataChain": ["0-0", "1-1", "2-2", "5-5", "6-8", "..."]
}
```

| Feld | Von wem geschrieben | Bedeutung |
|------|----------------------|-----------|
| `windows[].{x,y,w,h}` | Tab 1 | Fensterrahmen in Bild-Pixeln |
| `windows[].ledIndex`  | Tab 2/3 (`_recompute_chain`) | Globaler Ketten-Index (physische Drahtposition) der LED, die dieses Fenster versorgt (nur wenn aktiv) |
| `windows[].pixelIndex` | Tab 2/3 (`_recompute_chain`) | Logischer Pixel-Index, der dieses Fenster versorgt (siehe `ledBatches[].leds[].pixelIndex` unten) |
| `glassPanes[].{x,y,w,h}` | Tab 1 | Einzelne Glasscheiben (koennen mehrere pro Fenster sein) |
| `dpi` | Tab 2 | mm→Bild-Pixel-Umrechnung (`px_per_mm = dpi / 25.4`) |
| `ledBatches[]` | Tab 2/3 | Platzierte physische PCB-Batches, siehe unten |
| `ledBatches[].leds[].chainIndex` | Tab 3 | PHYSISCHE Position auf der Datenleitung -- jede LED bekommt einen eigenen, nie uebersprungenen Wert (jede physische LED belegt weiterhin einen eigenen Slot im Datenprotokoll) |
| `ledBatches[].leds[].pixelIndex` | Tab 3 | LOGISCHER Index: beruehren mehrere LEDs dasselbe Fenster (`LONG_RUN_MM`-Regel oder mehrere manuell auf dasselbe Fenster gesetzte LEDs), gelten sie als EIN logisches Pixel und TEILEN SICH denselben `pixelIndex` -- der Zaehler wird fuer sie nicht weitergezaehlt (uebersprungen). `null` bei deaktivierten/nicht zugeordneten LEDs. |
| `ledBatches[].leds[].manual` | Tab 2 | `true` = An/Aus wurde vom Nutzer fest uebersteuert, `_auto_assign` fasst diese LED nicht mehr an |
| `ledBatches[].width_mm`/`height_mm` | Tab 2 | Optional: Footprint-Groesse NUR fuer DIESE Platzierung (ueberschreibt `variant['footprint_width_mm']`/`['footprint_height_mm']`); fehlt eines der beiden Felder, gilt der Default der Variante (siehe `resolve_footprint_size`) |
| `chainOrder` | Tab 3 | Explizite Batch-Verbindungsreihenfolge (Batch-IDs); nicht verbundene Batches werden dahinter automatisch nach x-Position sortiert |
| `disabledLeds` | Tab 3 | Globale Ketten-Indizes ohne aktives Fenster |
| `totalLedCount` | Tab 3 | Gesamtzahl aller physischen LEDs aller Batches dieses Bildes |
| `totalPixelCount` | Tab 3 | Gesamtzahl DISTINKTER logischer Pixel (`totalPixelCount <= totalLedCount`, da kombinierte LEDs sich einen Pixel teilen) |
| `dataChain` | Tab 3 (`_recompute_chain`) | Geordnete Liste, ein Eintrag pro logischem Pixel in Reihenfolge ab Daten-Eingang; jeder Eintrag IMMER als `"<from>-<to>"`-String (auch bei nur einer LED, z. B. `"23-23"`) mit dem physischen `chainIndex`-Bereich der beteiligten LED(s). `len(dataChain) == totalPixelCount`. |

`batch_variants.json` (die EINE LED-Variante, bildübergreifend -- kein Array
mehrerer benannter PCB-Typen mehr):

```json
{ "variant": { "id": "70mm", "name": "70mm", "leds": [ { "x_mm": 8.9, "y_mm": 0.0 }, ... ],
              "din_mm": { "x_mm": 0.0, "y_mm": 0.0 }, "dout_mm": { "x_mm": 58.9, "y_mm": 0.0 },
              "footprint_width_mm": 75.0, "footprint_height_mm": 60.0 } }
```

`x_mm`/`y_mm` sind reale, physische Koordinaten auf der Platine (Ursprung frei
waehlbar, nur relative Abstaende zaehlen); die Reihenfolge im Array ist die
Kettenreihenfolge auf der PCB (Klickreihenfolge im Varianten-Designer).
`din_mm`/`dout_mm` sind optional (nur vorhanden, wenn im Designer von Hand
verschoben, siehe oben) -- ohne sie berechnet `connector_positions()` beide
automatisch. `footprint_width_mm`/`footprint_height_mm` sind ebenfalls
optional (Default-Footprint-Groesse der Variante, siehe
`resolve_footprint_size`) -- fehlen sie, gilt der Fallback
`FOOTPRINT_WIDTH`/`HEIGHT` = 75×60mm.

### `<name>.code.json` (kompakte Zweitkodierung)

Wird von `led_batch_editor.py._save()` zusaetzlich zu `<name>.json` geschrieben
(`_build_code_json()`) – dieselbe Zuordnung wie im Haupt-JSON, aber mit dem
PHYSISCHEN `chainIndex` (nicht dem kompaktierten `pixelIndex`) und durchgehend
bereichs-komprimiert, gedacht als direkt firmware-taugliches Format:

```json
{
  "windows": { "0": "0-4", "1": 5 },
  "disabled-leds": [1, 3, "9-14", 20]
}
```

| Feld | Bedeutung |
|------|-----------|
| `windows` | `{str(Fensterindex): chainIndex}` -- nur Fenster mit mindestens einer aktiven LED. Wert ist ein einzelner `chainIndex` (int), wenn genau eine LED das Fenster versorgt, sonst `"<from>-<to>"` (min..max der beteiligten physischen Indizes). |
| `disabled-leds` | Alle `chainIndex`-Werte OHNE aktive Fensterzuordnung, bereichs-komprimiert (`_compact_ranges()`): einzelne Werte bleiben int, zusammenhaengende Laeufe werden zu einem `"<from>-<to>"`-String zusammengefasst. Deaktivierte LEDs zaehlen bewusst mit (belegen ja weiterhin einen Platz auf dem Strang). |

### Wichtige interne Mechanismen

- **OpenAI-Bildgroesse** (`calcImages._fit_openai_dims`): die Images-API
  (gpt-image-1 & co.) verlangt Achsen als Vielfache von 16 und insgesamt
  hoechstens 8.000.000 Pixel. Ein nicht-konformes Bild wird von OpenAI selbst
  zurechtgeschnitten/aufgefuellt statt sauber skaliert -- genau das fuehrte
  frueher dazu, dass die zurueckgegebenen gruenen/roten Markierungen NICHT
  mehr mit den echten Fensterpositionen im Originalbild uebereinstimmten.
  `_fit_openai_dims` skaliert daher mit EINEM gemeinsamen Skalierungsfaktor
  (kein unabhaengiges Strecken der Achsen) auf die groesstmoegliche, gueltige
  Groesse herunter -- bei einem typischen Hausfoto (~2 MP) bleibt das nahe an
  der vollen Aufloesung, statt wie zuvor pauschal auf max. 1024px Kantenlaenge
  zu schrumpfen (deutlich feinere Erkennung). Verifiziert per echtem
  OpenAI-Aufruf + visueller Ueberlagerung auf `house1.pdf`.
- **ECC-Ausrichtungskorrektur** (`calcImages._align_annotated`): selbst mit
  korrekter Groesse (siehe oben) bleibt `images.edit` eine GENERATIVE
  Bearbeitung, kein pixelgenauer Edit -- OpenAI gibt das Gebaeude leicht
  verschoben/anders skaliert zurueck (ein paar Pixel, aber genug, damit
  Fenster-/Scheiben-Boxen sichtbar daneben liegen). Bestaetigt durch direkten
  Vergleich der regenerierten Gebaeudetextur mit dem echten Original an
  derselben Bildstelle (nicht nur der Markierungsfarbe). `_align_annotated`
  berechnet per `cv2.findTransformECC` (MOTION_AFFINE, auf halber Aufloesung
  fuer Tempo) die affine Korrektur und richtet `annotated` per
  `cv2.warpAffine` wieder exakt auf das Originalfoto aus, BEVOR die
  Farbmasken extrahiert werden. `get_annotated` wendet das auf JEDES Ergebnis
  an -- auch auf bereits vorhandene Cache-Dateien (`._annotated.png`) aus der
  Zeit vor dieser Korrektur, die dadurch beim naechsten Laden automatisch
  mitkorrigiert und neu abgespeichert werden. Bereits VOM NUTZER manuell
  gesetzte Fenster-/Scheibenmarkierungen (in `<name>.json`) werden davon nicht
  rueckwirkend veraendert -- nur die farbige Erkennungs-Hilfsebene wird
  praeziser; schon platzierte Markierungen muessten bei Bedarf neu gesetzt
  werden.
- **Flood-Fill-Erkennung** (`calcImages.py`): `flood_region` flutet den
  zusammenhaengenden Bereich um einen Klickpunkt; `MIN_FILL_RATIO = 0.85`
  (gefuellte Pixel ÷ Bounding-Box-Flaeche) unterscheidet echte rechteckige
  Fenster/Scheiben (~99 %) von einer ins Hintergrund „entkommenen“ Flutfuellung
  um ein Hindernis herum (~55 %) – reine Flaechen-Schwellenwerte
  (`MAX_FILL_AREA_FRACTION = 0.6`) allein reichten dafuer nicht aus.
- **Ungeteiltes-Fenster-Fallback**: `allow_window_fallback=True` (Default bei
  echtem Einzelklick) lässt ein Fenster ohne lokale Scheiben-Kante komplett als
  eine Scheibe gelten; beim automatisierten Raster-Scan/Positionen-Einfuegen
  ist das deaktiviert (`allow_window_fallback=False`), sonst wuerde der erste
  Rasterpunkt im Rahmen-Rand faelschlich eine Mega-Scheibe anlegen, bevor die
  echten Teil-Scheiben gefunden werden.
- **Daten-Merge statt Ueberschreiben**: Beide Tools lesen vor jedem Speichern
  die aktuelle JSON-Datei neu ein und aktualisieren **nur ihre eigenen** Felder
  (Tab 1 → `windows`/`glassPanes`, Tab 2/3 → `ledBatches`/`dpi`/`chainOrder`/…).
  Ein blindes Ueberschreiben des ganzen Objekts hat frueher echte, muehsam
  markierte Fenster geloescht, sobald der jeweils andere Tab eine veraltete
  In-Memory-Kopie gespeichert hat.
- **LED-An/Aus-Zuordnung** (`_auto_assign` in `led_batch_editor.py`): pro
  Fenster gewinnt normalerweise die LED naechst der Fenstermitte; ab einer
  Kandidaten-Spannweite ≥ `LONG_RUN_MM = 30.0` mm bleiben alle beruehrenden
  LEDs aktiv. Manuell uebersteuerte LEDs (`manual: true`) nehmen an dieser
  Konkurrenz nicht teil, UND ihr `windowIndex` wird bei jedem Aufruf von
  `_auto_assign` bewusst NICHT geometrisch neu berechnet (nur `led['enabled']`
  war urspruenglich geschuetzt, `windowIndex` wurde trotzdem jedes Mal
  ueberschrieben -- das machte z.B. eine manuelle LED-Gruppierung im
  Ketten-Tab beim naechsten `_auto_assign`-Aufruf sofort wieder rueckgaengig).
- **Tab-Wechsel-Timing**: `winfo_width()`/`winfo_height()` liefern direkt nach
  einem Notebook-Tab-Wechsel kurzzeitig `1` (noch nicht gemappt) – das faengt
  ein simples `X or 800` NICHT ab, da `1` wahr ist. Fix: `update_idletasks()`
  erzwingen + expliziter `<= 1`-Check vor jeder Zoom/Fit-Berechnung
  (`_fit`, `_fit_chain`).
- **Mausrad in eingebetteten Listen**: ein direktes `<MouseWheel>`-Bind auf
  eine Scroll-Canvas greift nur, wenn der Cursor ueber deren nacktem
  Hintergrund liegt – nicht ueber den eingebetteten Karten/Buttons/Eintraegen,
  die praktisch die ganze sichtbare Flaeche einnehmen. `bind_wheel_scroll()`
  bindet das Rad daher global, aber nur solange der Cursor innerhalb der
  Wrapper-Flaeche ist (Enter/Leave-Events).
- **DIN/DOUT statt einem einzelnen Verbinder** (`connector_positions()` in
  `led_batch_editor.py`): jede Platzierung hat ZWEI Kabelverbinder-Punkte,
  nicht nur den mm-Ursprung (0,0). DIN sitzt am Ursprung, DOUT
  `CONNECTOR_W_MM` hinter `variant['leds'][-1]` – der LETZTEN LED IN
  LISTEN-/KETTENREIHENFOLGE (hoechster Index), NICHT der LED mit dem
  groessten `x_mm`. Diese Unterscheidung ist wichtig: bei einem nicht streng
  von links nach rechts angeklickten Layout (Zickzack o.ae.) waeren beide
  nicht dieselbe LED, und die tatsaechliche Datenfluss-Richtung (Index 0 =
  DIN-seitig, Index n-1 = DOUT-seitig) haette Vorrang vor der raeumlichen
  Position (unabhaengig vom gespiegelten Render-Zustand – das ist eine feste
  Eigenschaft der physischen Platine). Die Ketten-Verbindungslinie zwischen
  zwei Batches laeuft von DOUT(A) zu DIN(B): ein Anschluss origin-zu-origin
  (DIN-zu-DIN) wuerde bei jeder gespiegelten Platzierung zickzacken, weil DIN
  beim Spiegeln auf die jeweils andere Seite der Platzierung springt, DOUT aber
  spiegelbildlich mitwandert und die beiden Punkte so nie sauber in
  Kettenrichtung ausgerichtet waeren.
- **Tastaturfokus der Toolbar-Buttons**: alle Checkbuttons/Buttons in der
  LED-Batches-Toolbar haben `takefocus=0`, sonst wuerde ein Klick auf sie den
  Fokus von der Zeichenflaeche abziehen – ein nachfolgender Leertaste-Tipp
  (Spiegeln) wuerde dann zuerst die eingebaute `<space>`-Klassenbindung des
  zuletzt angeklickten Buttons ausloesen und dessen eigenen Zustand
  ungewollt nochmal umschalten. `_pick_tool()` ruft zusaetzlich explizit
  `self.cv.focus_set()` auf, um den Fokus verlaesslich zurueckzuholen.
- **PDF-Kontur-Koordinaten** (`pdfHouse._extract_outline`): das Eingabe-PDF
  braucht KEINE echten PDF-Ebenen (OCG) – Illustrator-interne Ebenen werden
  beim Export meist ohnehin nicht dorthin uebernommen. Stattdessen werden Foto
  (`page.get_images()`) und Kontur-Vektorpfade (`page.get_drawings()`) einfach
  als unterschiedliche Inhaltstypen auf derselben Seite unterschieden. Die
  Kontur-Punkte liegen in PDF-Seiten-Punkt-Koordinaten; die Umrechnung in
  Bild-Pixel-Koordinaten nutzt die Platzierungs-Rect des Fotos auf der Seite
  (`page.get_image_rects()`) als affine Skalierung – setzt eine achsparallele
  (nicht gedrehte/gescherte) Bildplatzierung voraus.
- **OCG-Sichtbarkeit braucht Save+Reopen**: `Document.set_layer()` aendert
  den `/OCProperties`-Zustand sofort, aber `Page.get_pixmap()` wertet ihn bei
  einem bereits offenen/gerenderten Dokument NICHT rückwirkend neu aus – ohne
  `doc.save()` + `fitz.open()` (frisches Parsen) zeigen beide Ebenen-Zustaende
  identische Pixel. Das ist unkritisch fuer den eigentlichen Zweck (ein
  echter PDF-Betrachter wie Acrobat oeffnet die Datei ja ohnehin frisch),
  aber wichtig beim Testen/Verifizieren der OCG-Trennung.

### Bekannte Lücken / offene Folgeschritte

- Die Website (`src/main.ts`) liest aktuell **nur** `windows` (`x,y,w,h`) –
  `glassPanes`, `ledBatches`, `chainOrder`, `disabledLeds`, `totalLedCount`,
  `totalPixelCount`, `dataChain` und `windows[].{ledIndex,pixelIndex}` sind
  vorbereitete Rohdaten fuer eine spaetere echte LED-Ansteuerung (z. B.
  Export-Skript fuer einen ESP32), aber noch nicht im Frontend verdrahtet.
- Eine feste, globale Verkabelungsreihenfolge **über mehrere Bilder/Häuser
  hinweg** (falls im Bau-Tab der Website mehrere Segmente hintereinander
  gehaengt werden) kennt dieses Tool nicht – muesste beim Zusammenbau in der
  Website oder in einem separaten Export-Skript zusaetzlich aufgeloest werden.
- `pdfHouse._extract_outline` unterstuetzt nur achsparallele (nicht gedrehte/
  gescherte) Bildplatzierungen auf der PDF-Seite; Bezier-Kurven in der Kontur
  werden nur naeherungsweise (Start-/Endpunkt) uebernommen -- fuer die reine
  Sichtreferenz ausreichend, aber keine pixelgenaue Pfadgeometrie.

---

## Benutzeroberfläche

Die Anwendung teilt sich in zwei Hauptbereiche auf:

### 1. Steuerung (Control-Tab)
Der Standard-Tab zeigt ein virtuelles **Modell-Stellwerk** (über ein geschütztes Iframe). Es synchronisiert sich sekündlich mit dem Hauptfenster und verfügt über folgende Elemente:
- **Modellbahn-Uhrzeit**: Live-Anzeige der simulierten Zeit.
- **Schnellsteuerung**: 
  - `💡 Alles AN` – Aktiviert alle Lichter aller platzierten Segmente.
  - `🌑 Alles AUS` – Deaktiviert alle Lichter.
  - `🎲 Zufalls-Mix` – Schaltet eine zufällige Auswahl an Fenstern an/aus.
  - `✨ Demo-Modus` – Platziert bei leerer Kulisse alle Häuser, wechselt in den Tag-Nacht-Zyklus mit 15-facher Geschwindigkeit und stellt die Uhrzeit auf 18:00 (Dämmerung), um das automatische Einschalten der Lichter zu präsentieren.
  - `🚨 NOT-AUS` – Schaltet alle Lichter ab, wechselt auf eine rote Alarmbeleuchtung und lässt das Stellwerk rot pulsieren.
- **System-Status**: Live-Anzeige über Anzahl verbundener Häuser-Segmente, Gesamtfenster, aktuell leuchtende Fenster und den aktiven Lichtmodus.
- **Ereignis-Protokoll**: Ein Mini-Terminal mit Zeitstempel, das jede Aktion im System mitprotokolliert.

### 2. Bauen (Build-Tab)
Hier gestalten Sie die Hintergrund-Modulkulisse:
- **Hinzufügen**: Über ein großes `+` in der Mitte (oder per Header-Button) öffnet sich das Segment-Auswahl-Popup. Die Vorschaubilder zeigen die **Häuser mit bereits farbig ausgefüllten Fenstern**, damit Sie die Positionen sofort erkennen.
- **Anordnung**: Jedes hinzugefügte Haus wird nebeneinander platziert. Über Schaltflächen können die Häuser nach links oder rechts verschoben oder komplett gelöscht werden.
- **Interaktive Fenster**: Jedes Fenster kann angeklickt werden, um es manuell ein- oder auszuschalten (gelbes Leuchten bei AN, abgedunkeltes Schwarz bei AUS).

---

## Einstellungen & Beleuchtungsmodi

Über das Zahnrad-Symbol oben rechts lässt sich die Beleuchtungskonfiguration anpassen. Alle Einstellungen werden automatisch im `localStorage` gesichert.

### A) 🔄 Tag-Nacht-Zyklus
Simuliert den zeitabhängigen Verlauf eines Modellbahntages:
- **Geschwindigkeit**: Stufenlos einstellbar von langsam (1 Sek. Echtzeit = 1 Min. Modellzeit) bis extrem schnell (1 Sek. = 1 Std.).
- **Dämmerung & Morgengrauen**: Zwischen 18:00 und 20:00 Uhr schalten sich die Fenster schrittweise und zeitlich versetzt (staggered) ein. Zwischen 06:00 und 08:00 Uhr schalten sie sich wieder ab.
- **Zusatz-Effekte**:
  - `💃 Party in der Nacht`: Schnelle, zufällige Farbwechsel in einzelnen Fenstern nach Einbruch der Dunkelheit.
  - `📺 Fernseher-Flackern`: Gemütlich unregelmäßiges, bläuliches Pulsieren in Wohnräumen.
  - `🔥 Kaminfeuer`: Warmes, orange-rotes Pulsieren.
  - `🏢 Büro-Dauerlicht`: Helles, kaltweißes Dauerlicht in Geschäftsfenstern, das auch tagsüber eingeschaltet bleibt.
  - `⚡ Schweißlicht`: Extrem helle, kurze blaue Lichtblitze (nur im Industriegebäude/Haus D).

### B) 🎨 Eigene Farbe
Ermöglicht das Pausieren des Zyklus, um eine statische Wunschfarbe zu erzwingen:
- Farb-Auswahl über einen runden Premium-Colorpicker.
- Vordefinierte Tasten für typische Modellbeleuchtungen: *Amber, Softgelb, Warmweiß, Kaltweiß, Violett* und *Rot*.

### C) 🔗 Node-Sequenz (Ablaufsteuerung)
Eine mächtige Ablaufsteuerung, um eigene Lichtshows in einer Endlosschleife zu programmieren:
- **Verzögerung (Delay)**: Wartezeit vor dem nächsten Schritt. Entweder als feste Dauer (z. B. 3,5s) oder als zufälliger Bereich (z. B. zwischen 1s und 5s).
- **Farbe ändern (Color)**: Setzt alle aktiven Fenster sofort auf eine feste Wunschfarbe oder eine vollkommen zufällige Farbe.
- **Übergang (Transition)**: Führt einen weichen, stufenlosen Farbübergang (Fading) zur gewünschten Zielfarbe über einen frei definierbaren Zeitraum $x$ aus.
- **Flackern (Flicker)**: Lässt alle aktiven Fenster für eine definierte Dauer mit einer Frequenz $x$ (in Hz) flackern (ideal für Gewittersimulationen, defekte Neonröhren oder Alarme).

---

## Drag & Drop

| Was                | Methode                                   |
|--------------------|-------------------------------------------|
| Gebäude-Segmente   | HTML5 Drag & Drop oder ◀▶ Buttons         |
| Node-Schritte      | HTML5 Drag & Drop oder ▲▼ Buttons         |

## Persistenz (`localStorage`)

| Schlüssel              | Inhalt                                      |
|------------------------|---------------------------------------------|
| `kulisse_scenery`      | Platzierte Segmente + alle Fenster-Settings |
| `kulisse_cycle_active` | Tag-Nacht-Zyklus aktiv/inaktiv             |
| `kulisse_cycle_speed`  | Simulationsgeschwindigkeit (1–60)           |

## Technische Details

- **Responsive Positionierung**: Die Fenster-Overlays werden auf den JPGs über relative Prozentkoordinaten gerendert (`left`, `top`, `width`, `height`). Dadurch bleibt das System auf allen Bildschirmauflösungen und Fenstergrößen vollkommen präzise.
- **Echtzeit-Kommunikation**: Da das Stellwerk im Iframe auf einer eigenen Seite (`/control/index.html`) läuft, kommunizieren Hauptfenster und Iframe über `window.postMessage`. Die Registrierung erfolgt automatisch über ein Intervall-Handshake-Verfahren.
- **Optimiertes CSS**: Alle flackernden Effekte und Lichtübergänge nutzen CSS-Keyframe-Animationen, um maximale Frameraten und minimale CPU-Last zu gewährleisten.
