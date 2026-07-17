# LED Batch Editor

Platziert physische SK6812-RGBW-LED-Batches (PCB-Streifen) auf den Gebäudebildern
in `public/images` und speichert die Positionen als JSON neben dem jeweiligen Bild.

## Starten

```bash
pip install -r requirements.txt
python led_batch_editor.py
```

Die Bilder werden automatisch aus `../public/images` geladen (relativ zu diesem Ordner).

## Workflow

1. **Variante anlegen** – Klick auf `+ Neue Variante`. Im Designer-Fenster jede LED der
   physischen PCB anklicken (linkes Raster, 1 Kästchen = 10 mm). Die Klickreihenfolge
   ist die Kettenreihenfolge (0, 1, 2, …) der SK6812-Datenleitung. Bestehende LEDs
   lassen sich anfassen und verschieben, `Entf` löscht die ausgewählte LED. Name
   vergeben, `Speichern`.
2. **Bild wählen** – Links in der Liste (`public/images`) anklicken.
3. **Batch platzieren** – Variante oben in der Combobox wählen, dann auf dem Bild
   ziehen, um ein Rechteck aufzuziehen. Die LEDs der Variante werden proportional
   in dieses Rechteck einskaliert.
4. **Rechteck anpassen** – Rechteck anklicken (auswählen), an den blauen Eckpunkten/
   Kanten ziehen zum Skalieren, im Inneren ziehen zum Verschieben – bis es exakt über
   dem Fenster im Foto liegt.
5. **Einzelne LEDs deaktivieren** – Direkt auf einen LED-Punkt klicken schaltet ihn
   dauerhaft aus (grau) bzw. wieder ein (grün). Nützlich, wenn eine PCB mehr LEDs hat
   als am jeweiligen Fenster sichtbar/benötigt werden.
6. **Reihenfolge der Batches** – Im rechten Panel mit ▲/▼ die Reihenfolge der
   platzierten Batches ändern. Diese Reihenfolge bestimmt den `chainIndex` beim
   Speichern (siehe unten) und sollte der physischen Verkabelungsreihenfolge
   entsprechen.
7. Gespeichert wird automatisch (debounced) bei jeder Änderung, als
   `public/images/<bildname>.json`.

## Dateien / Datenformat

### `public/images/batch_variants.json` (gemeinsame Bibliothek der PCB-Typen)

```json
{
  "variants": [
    {
      "id": "strip6",
      "name": "6er Streifen 20mm Pitch",
      "leds": [
        { "x_mm": 0,   "y_mm": 0 },
        { "x_mm": 20,  "y_mm": 0 },
        { "x_mm": 40,  "y_mm": 0 }
      ]
    }
  ]
}
```

`x_mm`/`y_mm` sind reale, physische Koordinaten auf der PCB (Ursprung beliebig,
nur relative Abstände zählen). Die Reihenfolge im Array = Kettenreihenfolge auf
der PCB.

### `public/images/<bildname>.json` (pro Bild)

```json
{
  "name": "haus1",
  "windows": [
    { "x": 1152, "y": 836, "w": 63, "h": 82 }
  ],
  "ledBatches": [
    {
      "id": "a1b2c3d4",
      "variantId": "strip6",
      "rect": { "x": 1152, "y": 836, "w": 63, "h": 82 },
      "leds": [
        { "index": 0, "chainIndex": 0, "enabled": true },
        { "index": 1, "chainIndex": 1, "enabled": true },
        { "index": 2, "chainIndex": 2, "enabled": false }
      ]
    }
  ]
}
```

- `windows` wird automatisch aus den `rect`-Werten aller Batches erzeugt – damit
  bleibt das bestehende Format (das die Website heute schon lädt) kompatibel.
- `rect` (in Bild-Pixeln) ist das anpassbare Rechteck; die LED-mm-Koordinaten der
  Variante werden linear auf dieses Rechteck abgebildet (siehe `led_image_positions`
  in `led_batch_editor.py`).
- `chainIndex` ist eine fortlaufende Nummerierung über **alle** Batches des Bildes
  in der im rechten Panel festgelegten Reihenfolge – das ist der Ausgangspunkt für
  das spätere Senden der Pixel-Reihenfolge an den ESP32 (der Datenpin adressiert
  die SK6812 ja ebenfalls streng sequenziell). Deaktivierte LEDs behalten ihren
  Platz in der Kette (die physische LED existiert ja weiterhin), werden aber von
  Effekten/Steuerung ignoriert (`enabled: false`).

## Offene Folgeschritte (nicht Teil dieses Tools)

- Die Website (`src/main.ts`) liest aktuell nur `windows`. Um echte LED-Daten
  (`ledBatches`) zu nutzen, müsste der Loader dort erweitert werden.
- Eine feste, globale Verkabelungsreihenfolge über *mehrere* Bilder hinweg (falls
  im Bau-Tab mehrere Häuser hintereinander gehängt werden) kennt dieses Tool nicht –
  das müsste beim Zusammenbau in der Website oder in einem Export-Skript für den
  ESP32 zusätzlich aufgelöst werden.
