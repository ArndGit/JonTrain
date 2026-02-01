# JonTrain

## Konzept

Dieser Grundschul-Rechentrainer trainiert das 1×1 als Multiplikation und Division, sowie Division mit Rest.
Es wurde von Grundschülern getestet und ist auf Lernspaß und Bedienbarkeit optimiert.

Ein besonderes Merkmal ist das Eingabefeld, welches die 10er und die 1er Nummern separat eingeben lässt.
Dadurch muss ein Kind sich – wie beim Schreiben – keine Gedanken um die Reihenfolge der Eingabe machen.

---

## Lokal ausführen (mit `uv`)

### Voraussetzungen
- Python **3.10+** (empfohlen: **3.11**)
- `uv` installiert

### Setup
```bash
uv sync
```

### Start
```bash
uv run python main.py
```

### Hinweis zu Kivy-Wheels (wichtig)
Wenn die Installation von Kivy versucht, aus Source zu bauen und fehlschlägt, nutzt das Projekt zusätzlich
den offiziellen Kivy-Wheel-Index über `pyproject.toml` (`[tool.uv.pip].extra-index-url`).

Falls es dennoch Probleme gibt:
- Prüfe, dass **Python 3.11** verwendet wird (3.12/3.13 sind oft problematischer).
- Cache leeren:
  ```bash
  uv cache clean
  uv sync -r
  ```

---

## Android Build (Buildozer)

### Voraussetzungen
Buildozer funktioniert am zuverlässigsten unter **Linux** (oder WSL2).
Die Android-SDK/NDK-Toolchain wird dabei größtenteils automatisch verwaltet.

### Wichtiger Hinweis zu Abhängigkeiten
Buildozer nutzt **nicht** automatisch `requirements.txt` oder `pyproject.toml`.

Alle zur Laufzeit benötigten Pakete müssen in `buildozer.spec` stehen.
Für den aktuellen Funktionsumfang sind mindestens nötig:

- `kivy`
- `pyjnius` (Android-APIs: Vibration, Share, SAF)
- `pyzipper` (verschlüsseltes Backup)
- ggf. `pycryptodomex` (Crypto-Backend für pyzipper)

Wenn die APK startet, aber Features fehlen oder sie direkt crasht, ist dies die häufigste Ursache.

### Build (Debug APK)
```bash
uv run buildozer -v android debug
```

Die APK liegt anschließend unter `bin/*.apk`.

---

## Emulator / Gerät testen

### Reales Android-Gerät (empfohlen)
1. Entwickleroptionen aktivieren, **USB-Debugging** einschalten.
2. Gerät anschließen.
3. APK installieren:
   ```bash
   adb install -r bin/*.apk
   ```
4. Logs ansehen:
   ```bash
   adb logcat | grep -i python
   ```

### Android Emulator (AVD)
1. Android Studio installieren.
2. SDK Manager:
   - Android SDK Platform
   - Android SDK Platform-Tools
   - Android Emulator
3. AVD Manager → neues Gerät (z. B. Pixel) anlegen.
4. Emulator starten.
5. APK installieren:
   ```bash
   adb install -r bin/*.apk
   ```

Hinweis: Emulatoren sind meist **x86_64**.
Falls die APK nur ARM-ABIs enthält, muss `android.arch` in `buildozer.spec` angepasst werden.

---

## GitHub Actions

Der GitHub-Workflow baut eine Debug-APK auf `ubuntu-22.04`.
Gecacht werden:
- `.buildozer_global`
- `.buildozer`
- `.uv-cache`

Das Runner-OS selbst wird **nicht** gecacht (jede Pipeline läuft auf einem frischen Image).

---

## Tester
Danke an **Jona, Vincent und Ben** fürs Testen!

## Unterstützen
Bitte unterstützt einfach einen Verein, der sich für Jugendbildung stark macht,
z. B. das Planetarium Laupheim e.V. (Spendenlink in der App unter „Über“).

## Lizenz
Siehe Lizenz: [License.txt](./License.txt)
