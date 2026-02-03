# Copyright (C) 2025 Arnd Brandes.
# Dieses Programm kann durch jedermann gemäß den Bestimmungen der Deutschen Freien Software Lizenz genutzt werden.

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, Line
from kivy.utils import platform as kivy_platform

from datetime import datetime
import math
from random import randint
import os
import json
import webbrowser
import io
import struct
import wave

__version__ = "0.8"

# Operator glyphs (German style)
OP_MUL = "\u00B7"  # middle dot
OP_DIV = ":"       # colon

# Highscore schema
HIGHSCORE_SCHEMA_VERSION = "1.0"
HIGHSCORE_FILENAME = f"highscores_schema_{HIGHSCORE_SCHEMA_VERSION}.json"
LEGACY_HIGHSCORE_FILE = "highscores.json"

# Backup settings
BACKUP_PASSWORD = "JonTrain-Extrasicher"
BACKUP_EXTENSION_ZIP = ".jontrain.zip"
BACKUP_EXTENSION_AES = ".jontrain.aes"

# AES Zip writer/reader
try:
    import pyzipper  # dependency: pyzipper
except Exception:
    pyzipper = None

# AES-GCM fallback (uses pycryptodome)
try:
    from Crypto.Cipher import AES  # type: ignore
    from Crypto.Protocol.KDF import PBKDF2  # type: ignore
    from Crypto.Hash import SHA256  # type: ignore
    _HAVE_PYCRYPTODOME = True
except Exception:
    AES = None  # type: ignore
    PBKDF2 = None  # type: ignore
    SHA256 = None  # type: ignore
    _HAVE_PYCRYPTODOME = False

# Backup header (for AES-GCM fallback)
_BACKUP_MAGIC = b"JTBK1"
# Platform detection
IS_ANDROID = (kivy_platform == "android")
IS_IOS = (kivy_platform == "ios")
_JARRAY_AVAILABLE = False
_JBYTEARRAY_CLS = None

if IS_ANDROID:
    try:
        from jnius import autoclass, jarray  # type: ignore
        _JARRAY_AVAILABLE = True
    except Exception:
        from jnius import autoclass  # type: ignore
        jarray = None  # type: ignore

    if not _JARRAY_AVAILABLE:
        try:
            _JBYTEARRAY_CLS = autoclass("[B")
        except Exception:
            _JBYTEARRAY_CLS = None

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Intent = autoclass("android.content.Intent")
    String = autoclass("java.lang.String")
    Build_VERSION = autoclass("android.os.Build$VERSION")
    Context = autoclass("android.content.Context")
    VibrationEffect = autoclass("android.os.VibrationEffect")
    HapticFeedbackConstants = autoclass("android.view.HapticFeedbackConstants")
    ClipData = autoclass("android.content.ClipData")

    try:
        VibratorManager = autoclass("android.os.VibratorManager")
    except Exception:
        VibratorManager = None

    MediaStore_Images_Media = autoclass("android.provider.MediaStore$Images$Media")
    MediaStore_MediaColumns = autoclass("android.provider.MediaStore$MediaColumns")
    ContentValues = autoclass("android.content.ContentValues")

if IS_IOS:
    try:
        from pyobjus import autoclass as objc_autoclass, objc_str, objc_method, NSObject  # type: ignore
        _HAVE_PYOBJUS = True
    except Exception:
        objc_autoclass = None  # type: ignore
        objc_str = None  # type: ignore
        objc_method = None  # type: ignore
        NSObject = object  # type: ignore
        _HAVE_PYOBJUS = False

if IS_IOS and _HAVE_PYOBJUS:
    class IOSDocPickerDelegate(NSObject):
        def initWithOwner_(self, owner):
            self = super(IOSDocPickerDelegate, self).init()
            self._owner = owner
            return self

        @objc_method("v@:@@")
        def documentPicker_didPickDocumentsAtURLs_(self, picker, urls):
            try:
                if urls is None or urls.count() == 0:
                    self._owner._set_about_status("Keine Datei gewählt.")
                    return
                url = urls.objectAtIndex_(0)
                try:
                    if hasattr(url, "startAccessingSecurityScopedResource"):
                        url.startAccessingSecurityScopedResource()
                except Exception:
                    pass
                try:
                    path = str(url.path())
                    with open(path, "rb") as f:
                        data = f.read()
                    self._owner._import_backup_bytes(data)
                    self._owner._set_about_status("Import erfolgreich. Highscores übernommen.")
                finally:
                    try:
                        if hasattr(url, "stopAccessingSecurityScopedResource"):
                            url.stopAccessingSecurityScopedResource()
                    except Exception:
                        pass
            except Exception as e:
                self._owner._set_about_status(f"Import-Fehler: {e}")

        @objc_method("v@:@")
        def documentPickerWasCancelled_(self, picker):
            try:
                self._owner._set_about_status("Abgebrochen.")
            except Exception:
                pass

CATEGORIES = {
    "Mal-nehmen": "mult",
    "Teilen": "div",
    "Mal-nehmen und Teilen ohne Rest": "mult_div",
    "Teilen mit Rest": "div_rest",
    "Teilen mit und ohne Rest": "div_divrest",
    "Alles gemischt": "all",
}


def convert_to_number(value: str) -> int:
    return int(value) if value.strip() else 0


def scale_font(base_size: int) -> int:
    screen_width, _ = Window.size
    scale_factor = screen_width / 600
    return int(base_size * scale_factor)


class MathTrainer(App):
    # Android SAF request codes
    REQ_EXPORT_BACKUP = 1101
    REQ_IMPORT_BACKUP = 1102

    def build(self):
        self.layout = BoxLayout(orientation="vertical")
        self.current_view = "menu"  # menu/training/about/license/highscore/success/endgame
        self._popup = None

        self.category = None
        self.points = 0
        self.question = None
        self.time_left = 300
        self.current_question = None

        self.answer = {"tens": "", "ones": "", "remainder": ""}
        self.button_refs = {"tens": None, "ones": None, "remainder": None}

        self.last_new_entry = None
        self._sound_success = None
        self._sound_failure = None
        self._sounds_ready = False

        self.highscores = {}
        self.load_highscores()

        # Android bindings
        self._activity = None
        self._vibrator = None
        if IS_ANDROID:
            try:
                self._activity = PythonActivity.mActivity
                self._activity.bind(on_activity_result=self._on_activity_result)
                self._vibrator = self._get_vibrator()
            except Exception:
                self._activity = None
                self._vibrator = None

        # Back key handling (Android navigation)
        Window.bind(on_keyboard=self._on_keyboard)

        self.main_menu()
        return self.layout

    # -------------------------
    # Android Back key / Navigation
    # -------------------------
    def _on_keyboard(self, window, key, scancode, codepoint, modifier):
        # Android "Back" is key=27 (Escape)
        if key != 27:
            return False

        # If a popup is open, close it
        if self._popup:
            try:
                self._popup.dismiss()
            except Exception:
                pass
            self._popup = None
            return True

        if self.current_view == "training":
            self.confirm_end_training()
            return True

        if self.current_view == "about":
            self.return_to_main_menu()
            return True

        if self.current_view == "license":
            self.show_about()
            return True

        if self.current_view in ("highscore", "success", "endgame"):
            self.return_to_main_menu()
            return True

        # menu: confirm app exit
        if self.current_view == "menu":
            self.confirm_exit_app()
            return True

        return False

    # -------------------------
    # Dialog helpers
    # -------------------------
    def _show_confirm(self, title: str, message: str, on_yes, on_no=None):
        content = BoxLayout(orientation="vertical", spacing=10, padding=10)
        content.add_widget(Label(text=message, font_size=scale_font(22)))

        btn_row = BoxLayout(size_hint_y=None, height=scale_font(60), spacing=10)
        yes_btn = Button(text="Ja", font_size=scale_font(22))
        no_btn = Button(text="Nein", font_size=scale_font(22))

        def _dismiss(*_):
            if self._popup:
                self._popup.dismiss()
            self._popup = None

        def _yes(*_):
            _dismiss()
            on_yes()

        def _no(*_):
            _dismiss()
            if on_no:
                on_no()

        yes_btn.bind(on_press=_yes)
        no_btn.bind(on_press=_no)
        btn_row.add_widget(no_btn)
        btn_row.add_widget(yes_btn)
        content.add_widget(btn_row)

        self._popup = Popup(
            title=title,
            content=content,
            size_hint=(0.8, 0.4),
            auto_dismiss=False,
        )
        self._popup.open()

    def confirm_end_training(self):
        self._show_confirm(
            "Training beenden?",
            "Möchtest du das Training wirklich beenden?",
            on_yes=self.return_to_main_menu,
        )

    def confirm_exit_app(self):
        self._show_confirm(
            "App beenden?",
            "Möchtest du JonTrain wirklich schließen?",
            on_yes=self.stop,
        )

    # -------------------------
    # Vibration (Android)
    # -------------------------
    def _get_vibrator(self):
        if not IS_ANDROID or not self._activity:
            return None
        try:
            api = int(Build_VERSION.SDK_INT)
        except Exception:
            api = 0

        vib = None
        if api >= 31 and VibratorManager is not None:
            try:
                mgr = self._activity.getSystemService(Context.VIBRATOR_MANAGER_SERVICE)
                if mgr:
                    vib = mgr.getDefaultVibrator()
            except Exception:
                vib = None

        if vib is None:
            try:
                vib = self._activity.getSystemService(Context.VIBRATOR_SERVICE)
            except Exception:
                vib = None

        return vib

    def _try_haptic_feedback(self):
        if not IS_ANDROID or not self._activity:
            return False
        try:
            view = self._activity.getWindow().getDecorView()
            return bool(view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP))
        except Exception:
            return False

    # -------------------------
    # iOS Haptics / Share / Files
    # -------------------------
    def _ios_present_view_controller(self, vc):
        if not IS_IOS or not _HAVE_PYOBJUS:
            return False
        try:
            UIApplication = objc_autoclass("UIApplication")
            app = UIApplication.sharedApplication()
            window = app.keyWindow()
            if window is None:
                windows = app.windows()
                if windows and windows.count() > 0:
                    window = windows.objectAtIndex_(0)
            if window is None:
                return False
            root = window.rootViewController()
            if root is None:
                return False
            root.presentViewController_animated_completion_(vc, True, None)
            return True
        except Exception:
            return False

    def _ios_haptic(self, success: bool):
        if not IS_IOS or not _HAVE_PYOBJUS:
            return False
        try:
            UINotificationFeedbackGenerator = objc_autoclass("UINotificationFeedbackGenerator")
            gen = UINotificationFeedbackGenerator.alloc().init()
            gen.prepare()
            # 0 = Success, 1 = Warning, 2 = Error
            gen.notificationOccurred_(0 if success else 2)
            return True
        except Exception:
            return False

    def _ios_share_image(self, path: str, title: str = "Teilen"):
        if not IS_IOS or not _HAVE_PYOBJUS:
            return False
        try:
            UIImage = objc_autoclass("UIImage")
            UIActivityViewController = objc_autoclass("UIActivityViewController")
            NSArray = objc_autoclass("NSArray")
            image = UIImage.imageWithContentsOfFile_(objc_str(path))
            if image is None:
                return False
            items = NSArray.arrayWithObject_(image)
            vc = UIActivityViewController.alloc().initWithActivityItems_applicationActivities_(items, None)
            return self._ios_present_view_controller(vc)
        except Exception:
            return False

    def _ios_share_file(self, path: str, title: str = "Teilen"):
        if not IS_IOS or not _HAVE_PYOBJUS:
            return False
        try:
            NSURL = objc_autoclass("NSURL")
            UIActivityViewController = objc_autoclass("UIActivityViewController")
            NSArray = objc_autoclass("NSArray")
            url = NSURL.fileURLWithPath_(objc_str(path))
            items = NSArray.arrayWithObject_(url)
            vc = UIActivityViewController.alloc().initWithActivityItems_applicationActivities_(items, None)
            return self._ios_present_view_controller(vc)
        except Exception:
            return False

    def vibrate(self, times=1):
        if IS_IOS:
            # Use iOS haptics; no multi-pulse support here
            return self._ios_haptic(success=(times <= 1))
        if not IS_ANDROID:
            return False

        if not self._vibrator:
            self._vibrator = self._get_vibrator()
        if not self._vibrator:
            return self._try_haptic_feedback()

        try:
            if hasattr(self._vibrator, "hasVibrator") and not self._vibrator.hasVibrator():
                return self._try_haptic_feedback()
        except Exception:
            pass

        pulse_ms = 140
        gap_ms = 90

        scheduled = False

        def _pulse(_dt):
            try:
                api = int(Build_VERSION.SDK_INT)
                if api >= 26:
                    eff = VibrationEffect.createOneShot(pulse_ms, VibrationEffect.DEFAULT_AMPLITUDE)
                    self._vibrator.vibrate(eff)
                else:
                    self._vibrator.vibrate(pulse_ms)
            except Exception:
                self._try_haptic_feedback()

        t = 0.0
        for _ in range(max(1, int(times))):
            Clock.schedule_once(_pulse, t)
            t += (pulse_ms + gap_ms) / 1000.0
            scheduled = True

        return scheduled

    def _tone_path(self, name: str) -> str:
        os.makedirs(self.user_data_dir, exist_ok=True)
        return os.path.join(self.user_data_dir, name)

    def _generate_tone(self, path: str, freq: float, duration: float, volume: float = 0.35):
        sample_rate = 44100
        frames = int(sample_rate * max(0.05, duration))
        amp = int(32767 * max(0.0, min(1.0, volume)))
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for i in range(frames):
                s = int(amp * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
                wf.writeframes(struct.pack("<h", s))

    def _ensure_feedback_sounds(self):
        if self._sounds_ready:
            return
        self._sounds_ready = True

        try:
            success_path = self._tone_path("success.wav")
            fail_path = self._tone_path("failure.wav")

            if not os.path.exists(success_path):
                self._generate_tone(success_path, freq=880.0, duration=0.14)
            if not os.path.exists(fail_path):
                self._generate_tone(fail_path, freq=220.0, duration=0.22)

            self._sound_success = SoundLoader.load(success_path)
            self._sound_failure = SoundLoader.load(fail_path)
        except Exception:
            self._sound_success = None
            self._sound_failure = None

    def _play_feedback_sound(self, success: bool):
        self._ensure_feedback_sounds()
        sound = self._sound_success if success else self._sound_failure
        if sound:
            try:
                sound.stop()
            except Exception:
                pass
            sound.play()

    def _feedback(self, success: bool):
        if IS_IOS and self._ios_haptic(success):
            return
        if self.vibrate(1 if success else 2):
            return
        self._play_feedback_sound(success)

    # -------------------------
    # Highscore persistence (App.user_data_dir)
    # -------------------------
    def get_highscore_path(self):
        os.makedirs(self.user_data_dir, exist_ok=True)
        return os.path.join(self.user_data_dir, HIGHSCORE_FILENAME)

    def get_legacy_paths(self):
        paths = [os.path.abspath(LEGACY_HIGHSCORE_FILE)]
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            paths.append(os.path.join(self.user_data_dir, LEGACY_HIGHSCORE_FILE))
        except Exception:
            pass
        return paths

    def _default_highscores_data(self):
        return {cat: [] for cat in CATEGORIES.values()}

    def _wrap_highscores(self, highscores_data):
        return {
            "schema_version": HIGHSCORE_SCHEMA_VERSION,
            "app_version": __version__,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": highscores_data,
        }

    def _try_load_json(self, path):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return None
        return None

    def load_highscores(self):
        schema_path = self.get_highscore_path()

        obj = self._try_load_json(schema_path)
        if isinstance(obj, dict) and obj.get("schema_version") == HIGHSCORE_SCHEMA_VERSION and "data" in obj:
            data = obj.get("data")
            if isinstance(data, dict):
                merged = self._default_highscores_data()
                for k, v in data.items():
                    if k in merged and isinstance(v, list):
                        merged[k] = v
                self.highscores = merged
                return

        legacy_obj = None
        for p in self.get_legacy_paths():
            tmp = self._try_load_json(p)
            if tmp is not None:
                legacy_obj = tmp
                break

        migrated = self._default_highscores_data()

        if isinstance(legacy_obj, dict) and "schema_version" not in legacy_obj and "data" not in legacy_obj:
            for cat_key, entries in legacy_obj.items():
                if cat_key in migrated and isinstance(entries, list):
                    migrated[cat_key] = entries
        elif isinstance(legacy_obj, dict) and isinstance(legacy_obj.get("data"), dict):
            data = legacy_obj.get("data")
            for cat_key, entries in data.items():
                if cat_key in migrated and isinstance(entries, list):
                    migrated[cat_key] = entries

        self.highscores = migrated
        self._save_highscores_file()

    def _save_highscores_file(self):
        path = self.get_highscore_path()
        wrapper = self._wrap_highscores(self.highscores)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, indent=4, ensure_ascii=False)

    # -------------------------
    # Android bytes helper (FIX: OutputStream/InputStream + pyjnius)
    # -------------------------
    def _to_jbytearray(self, data: bytes):
        """Convert Python bytes (0..255) to Java byte[] (-128..127) for pyjnius."""
        if not IS_ANDROID:
            return data  # type: ignore
        signed = [b - 256 if b > 127 else b for b in data]
        if _JARRAY_AVAILABLE and jarray:
            return jarray("b")(signed)
        if _JBYTEARRAY_CLS:
            arr = _JBYTEARRAY_CLS(len(signed))
            for i, v in enumerate(signed):
                arr[i] = v
            return arr
        return data  # type: ignore

    def _bytes_from_jbytearray(self, buf, n: int) -> bytes:
        """Convert Java byte[] (-128..127) to Python bytes (0..255)."""
        if isinstance(buf, (bytes, bytearray)):
            return bytes(buf[:n])
        return bytes(((int(buf[i]) + 256) & 0xFF) for i in range(n))

    # -------------------------
    # Backup (Android SAF file dialogs)
    # -------------------------
    def _set_about_status(self, text):
        if hasattr(self, "about_status_label") and self.about_status_label:
            self.about_status_label.text = text

    def _backup_suggested_name(self):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        ext = BACKUP_EXTENSION_ZIP if pyzipper is not None else BACKUP_EXTENSION_AES
        return f"jontrain-highscores-v{__version__}-schema{HIGHSCORE_SCHEMA_VERSION}-{stamp}{ext}"

    def _read_highscore_bytes(self) -> bytes:
        src_path = self.get_highscore_path()
        if not os.path.exists(src_path):
            self._save_highscores_file()
        with open(src_path, "rb") as f:
            return f.read()

    def _encrypt_backup_bytes_aes(self, payload: bytes) -> bytes:
        if not _HAVE_PYCRYPTODOME:
            raise RuntimeError("pycryptodome fehlt (AES-Backup nicht möglich)")

        salt = os.urandom(16)
        key = PBKDF2(
            BACKUP_PASSWORD.encode("utf-8"),
            salt,
            dkLen=32,
            count=200_000,
            hmac_hash_module=SHA256,
        )
        nonce = os.urandom(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(payload)
        return _BACKUP_MAGIC + salt + nonce + tag + ciphertext

    def _decrypt_backup_bytes_aes(self, data: bytes) -> bytes:
        if not _HAVE_PYCRYPTODOME:
            raise RuntimeError("pycryptodome fehlt (AES-Import nicht möglich)")

        if not data.startswith(_BACKUP_MAGIC):
            raise RuntimeError("Backup ungültig: AES-Header fehlt")

        salt = data[len(_BACKUP_MAGIC):len(_BACKUP_MAGIC) + 16]
        nonce = data[len(_BACKUP_MAGIC) + 16:len(_BACKUP_MAGIC) + 28]
        tag = data[len(_BACKUP_MAGIC) + 28:len(_BACKUP_MAGIC) + 44]
        ciphertext = data[len(_BACKUP_MAGIC) + 44:]

        key = PBKDF2(
            BACKUP_PASSWORD.encode("utf-8"),
            salt,
            dkLen=32,
            count=200_000,
            hmac_hash_module=SHA256,
        )
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)

    def _make_encrypted_backup_bytes(self):
        payload = self._read_highscore_bytes()

        if pyzipper is not None:
            buf = io.BytesIO()
            with pyzipper.AESZipFile(
                buf,
                "w",
                compression=pyzipper.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES,
            ) as zf:
                zf.setpassword(BACKUP_PASSWORD.encode("utf-8"))
                zf.writestr(HIGHSCORE_FILENAME, payload)
            return buf.getvalue()

        return self._encrypt_backup_bytes_aes(payload)

    def export_backup(self, instance=None):
        if pyzipper is None and not _HAVE_PYCRYPTODOME:
            self._set_about_status("Export nicht moeglich: pyzipper/pycryptodome fehlt.")
            return

        if IS_ANDROID and self._activity:
            try:
                self._pending_backup_bytes = self._make_encrypted_backup_bytes()
                intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                mime = "application/zip" if pyzipper is not None else "application/octet-stream"
                intent.setType(mime)
                intent.putExtra(Intent.EXTRA_TITLE, self._backup_suggested_name())
                self._activity.startActivityForResult(intent, self.REQ_EXPORT_BACKUP)
                self._set_about_status("Speicherort auswählen…")
            except Exception as e:
                self._set_about_status(f"Export-Fehler: {e}")
            return

        try:
            data = self._make_encrypted_backup_bytes()
            os.makedirs(self.user_data_dir, exist_ok=True)
            out_path = os.path.join(self.user_data_dir, self._backup_suggested_name())
            with open(out_path, "wb") as f:
                f.write(data)
            if IS_IOS:
                if self._ios_share_file(out_path, title="Backup exportieren"):
                    self._set_about_status("Backup bereit zum Teilen/Speichern (Dateien-App).")
                else:
                    self._set_about_status(f"Backup gespeichert:\n{out_path}")
            else:
                self._set_about_status(f"Backup gespeichert:\n{out_path}")
        except Exception as e:
            self._set_about_status(f"Export-Fehler: {e}")

    def import_backup(self, instance=None):
        if pyzipper is None and not _HAVE_PYCRYPTODOME:
            self._set_about_status("Hinweis: Backup deaktiviert (pyzipper/pycryptodome fehlt).")
        elif pyzipper is None:
            self._set_about_status("Hinweis: pyzipper fehlt. Backup nutzt AES-Format.")

        if IS_ANDROID and self._activity:
            try:
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("*/*")
                self._activity.startActivityForResult(intent, self.REQ_IMPORT_BACKUP)
                self._set_about_status("Backup-Datei auswählen…")
            except Exception as e:
                self._set_about_status(f"Import-Fehler: {e}")
            return

        if IS_IOS:
            self._ios_import_backup_via_picker()
            return

        self._set_about_status("Import ist auf Desktop hier nicht implementiert.")

    def _ios_import_backup_via_picker(self):
        if not IS_IOS or not _HAVE_PYOBJUS:
            self._set_about_status("Import nicht möglich: iOS/pyobjus fehlt.")
            return
        try:
            UIDocumentPickerViewController = objc_autoclass("UIDocumentPickerViewController")
            NSArray = objc_autoclass("NSArray")
            types = NSArray.arrayWithObject_(objc_str("public.data"))
            # 0 = UIDocumentPickerModeImport
            picker = UIDocumentPickerViewController.alloc().initWithDocumentTypes_inMode_(types, 0)
            delegate = IOSDocPickerDelegate.alloc().initWithOwner_(self)
            self._ios_doc_picker_delegate = delegate
            picker.setDelegate_(delegate)
            try:
                picker.setModalPresentationStyle_(1)
            except Exception:
                pass
            if not self._ios_present_view_controller(picker):
                self._set_about_status("Import nicht möglich: UI konnte nicht geöffnet werden.")
        except Exception as e:
            self._set_about_status(f"Import-Fehler: {e}")

    def _on_activity_result(self, request_code, result_code, intent):
        # Android.RESULT_OK = -1
        if result_code != -1 or intent is None:
            if request_code in (self.REQ_EXPORT_BACKUP, self.REQ_IMPORT_BACKUP):
                self._set_about_status("Abgebrochen.")
            return

        try:
            uri = intent.getData()
            if uri is None:
                self._set_about_status("Keine Datei gewählt.")
                return

            if request_code == self.REQ_EXPORT_BACKUP:
                self._write_bytes_to_uri(uri, getattr(self, "_pending_backup_bytes", b""))
                self._pending_backup_bytes = None
                self._set_about_status("Backup gespeichert.")

            elif request_code == self.REQ_IMPORT_BACKUP:
                raw = self._read_bytes_from_uri(uri)
                self._import_backup_bytes(raw)
                self._set_about_status("Import erfolgreich. Highscores übernommen.")

        except Exception as e:
            self._set_about_status(f"Fehler: {e}")

    def _write_bytes_to_uri(self, uri, data: bytes):
        resolver = self._activity.getContentResolver()
        stream = resolver.openOutputStream(uri)
        if stream is None:
            raise RuntimeError("Konnte OutputStream nicht öffnen")
        try:
            # FIX: Java OutputStream.write braucht Java byte[]
            stream.write(self._to_jbytearray(data))
            stream.flush()
        finally:
            stream.close()

    def _read_bytes_from_uri(self, uri) -> bytes:
        resolver = self._activity.getContentResolver()
        stream = resolver.openInputStream(uri)
        if stream is None:
            raise RuntimeError("Konnte InputStream nicht öffnen")
        try:
            out = io.BytesIO()

            if IS_ANDROID:
                # FIX: Java InputStream.read erwartet Java byte[]
                if _JARRAY_AVAILABLE and jarray:
                    buf = jarray("b")([0] * (64 * 1024))
                elif _JBYTEARRAY_CLS:
                    buf = _JBYTEARRAY_CLS(64 * 1024)
                else:
                    buf = bytearray(64 * 1024)
                while True:
                    n = stream.read(buf)
                    if n is None or n <= 0:
                        break
                    out.write(self._bytes_from_jbytearray(buf, int(n)))
            else:
                buf = bytearray(64 * 1024)
                while True:
                    n = stream.read(buf)
                    if n is None or n <= 0:
                        break
                    out.write(bytes(buf[:n]))

            return out.getvalue()
        finally:
            stream.close()

    def _import_backup_bytes(self, zip_bytes: bytes):
        if zip_bytes.startswith(_BACKUP_MAGIC):
            raw = self._decrypt_backup_bytes_aes(zip_bytes)
        else:
            if pyzipper is None:
                raise RuntimeError("pyzipper fehlt (ZIP-Import nicht moeglich)")
            buf = io.BytesIO(zip_bytes)
            with pyzipper.AESZipFile(buf, "r") as zf:
                zf.setpassword(BACKUP_PASSWORD.encode("utf-8"))
                names = zf.namelist()
                if HIGHSCORE_FILENAME not in names:
                    raise RuntimeError("Backup ungueltig: Datei fehlt im Archiv")
                raw = zf.read(HIGHSCORE_FILENAME)

        obj = json.loads(raw.decode("utf-8"))
        if not (isinstance(obj, dict) and "schema_version" in obj and "data" in obj):
            raise RuntimeError("Backup ungültig: Format nicht erkannt")

        if obj.get("schema_version") != HIGHSCORE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema inkompatibel: Backup {obj.get('schema_version')} / App {HIGHSCORE_SCHEMA_VERSION}"
            )

        data = obj.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Backup ungültig: Datenblock fehlt")

        merged = self._default_highscores_data()
        for k, v in data.items():
            if k in merged and isinstance(v, list):
                merged[k] = v

        self.highscores = merged
        self._save_highscores_file()

    # -------------------------
    # Share success badge (generated on demand)
    # -------------------------
    def _create_badge_widget(self, entry, category_display: str):
        w, h = 900, 520
        badge = BoxLayout(orientation="vertical", size_hint=(None, None), size=(w, h), padding=30, spacing=18)

        with badge.canvas.before:
            Color(0, 0, 0, 1)
            bg = Rectangle(pos=badge.pos, size=badge.size)
            Color(1, 1, 1, 1)
            border = Line(rectangle=(badge.x, badge.y, badge.width, badge.height), width=2)

        def _sync(*_):
            bg.pos = badge.pos
            bg.size = badge.size
            border.rectangle = (badge.x, badge.y, badge.width, badge.height)

        badge.bind(pos=_sync, size=_sync)

        title = Label(text="JONTRAIN  HIGHSCORE", font_size=40)
        sep = Label(text="====================", font_size=26)

        name = entry.get("name", "Anonym")
        pts = entry.get("points", 0)
        date = entry.get("date", "")
        mode = category_display

        l1 = Label(text=f"Name:   {name}", font_size=34, halign="left")
        l2 = Label(text=f"Modus:  {mode}", font_size=34, halign="left")
        l3 = Label(text=f"Punkte: {pts}", font_size=34, halign="left")
        l4 = Label(text=f"Datum:  {date}", font_size=26, halign="left")

        for l in (l1, l2, l3, l4):
            l.text_size = (w - 60, None)
            l.valign = "middle"

        footer = Label(text="geteilt aus JonTrain", font_size=22)

        badge.add_widget(title)
        badge.add_widget(sep)
        badge.add_widget(l1)
        badge.add_widget(l2)
        badge.add_widget(l3)
        badge.add_widget(l4)
        badge.add_widget(Widget())
        badge.add_widget(footer)
        return badge

    def _show_info(self, title: str, message: str):
        content = BoxLayout(orientation="vertical", spacing=10, padding=10)
        content.add_widget(Label(text=message, font_size=scale_font(20)))
        btn = Button(text="OK", font_size=scale_font(20), size_hint_y=None, height=scale_font(60))

        popup = Popup(title=title, content=content, size_hint=(0.85, 0.4))
        btn.bind(on_press=lambda *_: popup.dismiss())
        content.add_widget(btn)
        popup.open()

    def _desktop_copy_image_to_clipboard(self, png_path: str):
        import subprocess
        import sys
        from shutil import which

        # Linux Wayland: wl-copy
        if sys.platform.startswith("linux"):
            if which("wl-copy"):
                try:
                    with open(png_path, "rb") as f:
                        subprocess.run(["wl-copy", "--type", "image/png"], input=f.read(), check=True)
                    return True, "Bild wurde in die Zwischenablage kopiert (wl-copy)."
                except Exception as e:
                    return False, f"wl-copy fehlgeschlagen: {e}"

            # Linux X11: xclip
            if which("xclip"):
                try:
                    subprocess.run(
                        ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", png_path],
                        check=True,
                    )
                    return True, "Bild wurde in die Zwischenablage kopiert (xclip)."
                except Exception as e:
                    return False, f"xclip fehlgeschlagen: {e}"

            return False, "Kein wl-copy/xclip gefunden. Installiere z.B. 'wl-clipboard' oder 'xclip'."

        # macOS: AppleScript
        if sys.platform == "darwin":
            try:
                script = f'''
                set theFile to POSIX file "{png_path}"
                set theData to (read theFile as «class PNGf»)
                set the clipboard to theData
                '''
                subprocess.run(["osascript", "-e", script], check=True)
                return True, "Bild wurde in die Zwischenablage kopiert (macOS)."
            except Exception as e:
                return False, f"macOS clipboard fehlgeschlagen: {e}"

        # Windows: PowerShell (requires STA)
        if sys.platform.startswith("win"):
            try:
                ps = f"""
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $img = [System.Drawing.Image]::FromFile('{png_path}')
    [System.Windows.Forms.Clipboard]::SetImage($img)
    $img.Dispose()
    """
                subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], check=True)
                return True, "Bild wurde in die Zwischenablage kopiert (Windows)."
            except Exception as e:
                return False, f"Windows clipboard fehlgeschlagen: {e}"

        return False, "Unbekanntes Desktop-OS: kann nicht in Zwischenablage kopieren."


    def _preview_exported_image(self, path: str):
        try:
            from kivy.uix.image import Image as KivyImage

            content = BoxLayout(orientation="vertical", spacing=10, padding=10)
            img = KivyImage(source=path, allow_stretch=True, keep_ratio=True)
            content.add_widget(img)

            btn = Button(text="OK", font_size=scale_font(22), size_hint_y=None, height=scale_font(60))
            popup = Popup(title="Exportiertes Badge", content=content, size_hint=(0.9, 0.9))
            btn.bind(on_press=lambda *_: popup.dismiss())
            content.add_widget(btn)

            popup.open()
        except Exception:
            # Fallback: im Dateibrowser öffnen
            try:
                import webbrowser
                webbrowser.open("file://" + os.path.abspath(path))
            except Exception:
                pass



    def share_achievement(self, instance=None):
        if not self.last_new_entry or not self.category:
            return

        category_display = next((k for k, v in CATEGORIES.items() if v == self.category), self.category)

        badge = self._create_badge_widget(self.last_new_entry, category_display)

        # Zentriert ON-SCREEN platzieren (robust, damit sicher gerendert wird)
        w, h = badge.size
        badge.pos = ((Window.width - w) / 2, (Window.height - h) / 2)

        # Wichtig: NICHT opacity=0 setzen, sonst kann es „leer“ werden
        self.root.add_widget(badge)

        os.makedirs(self.user_data_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(self.user_data_dir, f"jontrain-badge-{stamp}.png")

        def _render_and_share(_dt):
            try:
                # Force update before export
                badge.do_layout()
                badge.canvas.ask_update()
                self.root.canvas.ask_update()

                badge.export_to_png(out_path)
            finally:
                try:
                    self.root.remove_widget(badge)
                except Exception:
                    pass

            # Android: teilen
            if IS_ANDROID and self._activity:
                self._android_share_image_via_mediastore(out_path, title="Highscore teilen")
            elif IS_IOS:
                if not self._ios_share_image(out_path, title="Highscore teilen"):
                    self._preview_exported_image(out_path)
            else:
                # Desktop: wenigstens anzeigen
                self._preview_exported_image(out_path)

        # Nicht 0! Gib Kivy Zeit für mindestens einen Draw-Pass
        Clock.schedule_once(_render_and_share, 0.2)


    def _android_share_image_via_mediastore(self, path: str, title="Teilen"):
        try:
            resolver = self._activity.getContentResolver()

            values = ContentValues()
            values.put(MediaStore_MediaColumns.MIME_TYPE, String("image/png"))
            values.put(MediaStore_MediaColumns.DISPLAY_NAME, String(os.path.basename(path)))

            # API 29+: optional, makes it show up in Pictures/
            api = int(Build_VERSION.SDK_INT)
            if api >= 29:
                values.put(MediaStore_MediaColumns.RELATIVE_PATH, String("Pictures/JonTrain"))
                try:
                    values.put(MediaStore_MediaColumns.IS_PENDING, 1)
                except Exception:
                    pass

            uri = resolver.insert(MediaStore_Images_Media.EXTERNAL_CONTENT_URI, values)
            if uri is None:
                raise RuntimeError("MediaStore insert fehlgeschlagen")

            stream = resolver.openOutputStream(uri)
            if stream is None:
                raise RuntimeError("Konnte MediaStore OutputStream nicht öffnen")

            try:
                with open(path, "rb") as f:
                    data = f.read()
                # FIX: Java OutputStream.write braucht Java byte[]
                stream.write(self._to_jbytearray(data))
                stream.flush()
            finally:
                stream.close()

            if api >= 29:
                try:
                    values = ContentValues()
                    values.put(MediaStore_MediaColumns.IS_PENDING, 0)
                    resolver.update(uri, values, None, None)
                except Exception:
                    pass

            intent = Intent(Intent.ACTION_SEND)
            intent.setType("image/png")
            try:
                intent.setDataAndType(uri, "image/png")
            except Exception:
                pass
            intent.putExtra(Intent.EXTRA_STREAM, uri)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            try:
                intent.setClipData(ClipData.newRawUri(String("image"), uri))
            except Exception:
                pass
            chooser = Intent.createChooser(intent, String(title))
            chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            self._activity.startActivity(chooser)
        except Exception:
            self._android_share_text("Ich habe einen Highscore in JonTrain geschafft!")

    def _android_share_text(self, text: str):
        try:
            intent = Intent(Intent.ACTION_SEND)
            intent.setType("text/plain")
            intent.putExtra(Intent.EXTRA_TEXT, String(text))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            chooser = Intent.createChooser(intent, String("Teilen"))
            chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            self._activity.startActivity(chooser)
        except Exception:
            pass

    # -------------------------
    # UI: About / License
    # -------------------------
    def show_about(self, instance=None):
        self.current_view = "about"
        self.layout.clear_widgets()

        self.layout.add_widget(Label(text="Über JonTrain", font_size=scale_font(28)))
        self.layout.add_widget(Label(text="Autor: Arnd", font_size=scale_font(24)))
        self.layout.add_widget(Label(text="Tester: Jona, Vincent, Ben", font_size=scale_font(24)))
        self.layout.add_widget(Label(text=f"Version: {__version__}", font_size=scale_font(24)))
        self.layout.add_widget(Label(text=f"Schema: {HIGHSCORE_SCHEMA_VERSION}", font_size=scale_font(24)))

        self.layout.add_widget(Label(text="Backup (Highscores)", font_size=scale_font(24)))

        export_btn = Button(text="Backup exportieren", font_size=scale_font(24), on_press=self.export_backup)
        import_btn = Button(text="Backup importieren", font_size=scale_font(24), on_press=self.import_backup)
        self.layout.add_widget(export_btn)
        self.layout.add_widget(import_btn)

        self.about_status_label = Label(text="", font_size=scale_font(16))
        self.layout.add_widget(self.about_status_label)

        if pyzipper is None and not _HAVE_PYCRYPTODOME:
            self._set_about_status("Import nicht moeglich: pyzipper/pycryptodome fehlt.")
            return

        license_btn = Button(text="Lizenz", font_size=scale_font(24), on_press=self.show_license)
        self.layout.add_widget(license_btn)

        support_btn = Button(text="Unterstütze meinen Verein", font_size=scale_font(24), on_press=self.open_support_link)
        self.layout.add_widget(support_btn)

        back_btn = Button(text="Zurück", font_size=scale_font(24), on_press=self.return_to_main_menu)
        self.layout.add_widget(back_btn)

    def show_license(self, instance=None):
        self.current_view = "license"
        self.layout.clear_widgets()
        self.layout.add_widget(Label(text="Lizenz (Deutsche Freie Software Lizenz)", font_size=scale_font(28)))

        license_text = """\
Copyright (C) 2025 Arnd Brandes.
Dieses Programm kann durch jedermann gemäß den Bestimmungen der Deutschen Freien Software Lizenz genutzt werden.

DEUTSCHE FREIE SOFTWARE LIZENZ (DFSL)

Präambel:
Diese Lizenz erlaubt es Ihnen, die Software frei zu nutzen, zu studieren, zu verändern und weiterzugeben, solange die Freiheit der Software erhalten bleibt.

1. Nutzungsrecht:
- Jeder darf die Software für beliebige Zwecke verwenden, ohne Einschränkung.

2. Verbreitung:
- Die Software darf in unveränderter oder modifizierter Form weitergegeben werden.
- Der Lizenztext muss mitgeliefert werden.
- Änderungen müssen gekennzeichnet und unter derselben Lizenz veröffentlicht werden.

3. Gewährleistungsausschluss:
- Diese Software wird ohne Garantie bereitgestellt.
- Der Autor übernimmt keine Haftung für Schäden, die durch die Nutzung der Software entstehen.

4. Freiheitserhalt:
- Diese Lizenz darf nicht durch andere Lizenzen ersetzt werden, die die Freiheit der Software einschränken.

Weitere Details finden Sie unter https://dfsl.de
"""
        scroll = ScrollView(size_hint=(1, 0.85))
        license_label = Label(
            text=license_text,
            font_size=scale_font(16),
            halign="left",
            valign="top",
            text_size=(Window.width - 40, None),
            size_hint_y=None,
        )
        license_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
        scroll.add_widget(license_label)

        back_btn = Button(text="Zurück", font_size=scale_font(24), size_hint=(1, 0.15), on_press=self.show_about)
        self.layout.add_widget(scroll)
        self.layout.add_widget(back_btn)

    def open_support_link(self, instance=None):
        url = "https://www.paypal.com/donate/?hosted_button_id=PND6Y8CGNZVW6"
        webbrowser.open(url)

    # -------------------------
    # Main menu / Highscore screens
    # -------------------------
    def main_menu(self):
        self.current_view = "menu"
        self.layout.clear_widgets()

        title = Label(text="JonTrain Rechentrainer", font_size=scale_font(32))
        self.layout.add_widget(title)

        for cat_name, cat_key in CATEGORIES.items():
            row = BoxLayout()
            btn = Button(
                text=cat_name,
                font_size=scale_font(24),
                on_press=lambda x, key=cat_key: self.start_training(key),
            )
            highscore_btn = Button(
                text="H",
                font_size=scale_font(24),
                on_press=lambda x, key=cat_key: self.show_highscore(key),
                size_hint_x=0.3,
            )
            row.add_widget(btn)
            row.add_widget(highscore_btn)
            self.layout.add_widget(row)

        about_btn = Button(text="Über", font_size=scale_font(24), on_press=self.show_about)
        self.layout.add_widget(about_btn)

    def show_highscore(self, category, new_entry=None):
        self.current_view = "highscore"
        self.layout.clear_widgets()
        display_name = next(k for k, v in CATEGORIES.items() if v == category)
        self.layout.add_widget(Label(text=f"Rangliste für {display_name}", font_size=scale_font(28)))

        scores = self.highscores.get(category, [])
        if scores:
            for rank, score in enumerate(scores, start=1):
                highlight = "[b]" if score == new_entry else ""
                reset = "[/b]" if score == new_entry else ""
                date_str = score.get("date", "")
                name_str = score.get("name", "Anonym")
                pts = score.get("points", 0)
                self.layout.add_widget(
                    Label(
                        text=f"{highlight}#{rank} {name_str} - {pts} Punkte ({date_str}){reset}",
                        font_size=scale_font(24),
                        markup=True,
                    )
                )
        else:
            self.layout.add_widget(Label(text="Keine Einträge vorhanden", font_size=scale_font(24)))

        back_btn = Button(text="Zurück", font_size=scale_font(24), on_press=self.return_to_main_menu)
        self.layout.add_widget(back_btn)

    def return_to_main_menu(self, instance=None):
        try:
            Clock.unschedule(self.update_timer)
        except Exception:
            pass
        self.main_menu()

    # -------------------------
    # Training screen / logic
    # -------------------------
    def clear_input(self):
        for key in self.button_refs:
            if self.button_refs[key]:
                self.button_refs[key].background_color = (1, 1, 1, 1)
        self.answer = {"tens": "", "ones": "", "remainder": ""}
        self.button_refs = {"tens": None, "ones": None, "remainder": None}
        self.update_answer_display()

    def start_training(self, category):
        self.current_view = "training"
        self.category = category
        self.points = 0
        self.time_left = 300
        self.layout.clear_widgets()

        top_bar = BoxLayout()
        left_spacer = Label(size_hint_x=0.15)
        self.prev_question_label = Label(text="", font_size=scale_font(24), halign="left")
        exit_btn = Button(
            text="X",
            font_size=scale_font(16),
            size_hint_x=0.15,
            on_press=lambda *_: self.confirm_end_training(),
        )

        top_bar.add_widget(left_spacer)
        top_bar.add_widget(self.prev_question_label)
        top_bar.add_widget(exit_btn)
        self.layout.add_widget(top_bar)

        separator = Label(text="―" * 50, font_size=scale_font(16), size_hint_y=None, height=scale_font(8))
        self.layout.add_widget(separator)

        self.question_label = Label(text="", font_size=scale_font(28))
        self.layout.add_widget(self.question_label)

        self.answer_label = Label(text="", font_size=scale_font(28))
        self.layout.add_widget(self.answer_label)

        separator2 = Label(text="―" * 50, font_size=scale_font(16), size_hint_y=None, height=scale_font(8))
        self.layout.add_widget(separator2)

        self.button_refs = {"tens": None, "ones": None, "remainder": None}

        num_buttons = [
            [("10", "tens"), ("20", "tens"), ("30", "tens"), ("40", "tens"), ("50", "tens"),
             ("60", "tens"), ("70", "tens"), ("80", "tens"), ("90", "tens"), ("100", "tens")],
            [("1", "ones"), ("2", "ones"), ("3", "ones"), ("4", "ones"),
             ("5", "ones"), ("6", "ones"), ("7", "ones"), ("8", "ones"), ("9", "ones"), ("10", "tens")],
            [("R0", "remainder"), ("R1", "remainder"), ("R2", "remainder"), ("R3", "remainder"),
             ("R4", "remainder"), ("R5", "remainder"), ("R6", "remainder"), ("R7", "remainder"),
             ("R8", "remainder"), ("R9", "remainder")]
        ]

        for row in num_buttons:
            button_row = BoxLayout()
            for num, group in row:
                btn = Button(text=num, font_size=scale_font(24), on_press=lambda x, grp=group: self.toggle_input(x, grp))
                button_row.add_widget(btn)
            self.layout.add_widget(button_row)

        control_row = BoxLayout()
        submit_btn = Button(text="EINGABE", font_size=scale_font(24), on_press=self.check_answer)
        clear_btn = Button(text="LÖSCHEN", font_size=scale_font(24), on_press=lambda *_: self.clear_input())
        control_row.add_widget(clear_btn)
        control_row.add_widget(submit_btn)
        self.layout.add_widget(control_row)

        self.timer_label = Label(text=f"Zeit: {self.time_left} s", font_size=scale_font(24))
        self.layout.add_widget(self.timer_label)

        self.points_label = Label(text=f"Punkte: {self.points}", font_size=scale_font(24))
        self.layout.add_widget(self.points_label)

        Clock.schedule_interval(self.update_timer, 1)
        self.generate_question()

    def generate_question(self):
        while True:
            case = randint(1, 10)

            if case < 5 and self.category in ["mult", "mult_div", "all"]:
                a, b = randint(1, 10), randint(1, 10)
                self.current_question = (a, b, "mult")
                self.question = f"{a} {OP_MUL} {b}"
                self.question_label.text = f"Was ist {a} {OP_MUL} {b}?"
                break

            if case < 8 and self.category in ["div", "mult_div", "div_divrest", "all"]:
                a, b = randint(1, 10), randint(1, 10)
                self.current_question = (a * b, b, "div")
                self.question = f"{a * b} {OP_DIV} {b}"
                self.question_label.text = f"Was ist {a * b} {OP_DIV} {b}?"
                break

            if case >= 8 and self.category in ["div_rest", "div_divrest", "all"]:
                a, b = randint(1, 10), randint(2, 10)
                remainder = randint(0, b - 1)
                self.current_question = (a * b + remainder, b, remainder, "div_rest")
                self.question = f"{a * b + remainder} {OP_DIV} {b}"
                self.question_label.text = f"Was ist {a * b + remainder} {OP_DIV} {b}?"
                break

    def toggle_input(self, instance, group):
        if self.button_refs[group]:
            self.button_refs[group].background_color = (1, 1, 1, 1)

        if self.button_refs[group] == instance:
            self.answer[group] = ""
            self.button_refs[group] = None
        else:
            self.answer[group] = instance.text
            self.button_refs[group] = instance
            instance.background_color = (0.5, 1, 0.5, 1)

        self.update_answer_display()

    def update_answer_display(self):
        tens = convert_to_number(self.answer["tens"] if self.answer["tens"] else "")
        ones = convert_to_number(self.answer["ones"] if self.answer["ones"] else "")
        remainder = self.answer["remainder"] if self.answer["remainder"] else ""
        self.answer_label.text = f"{tens + ones}{remainder}"

    def check_answer(self, instance):
        tens = convert_to_number(self.answer["tens"])
        ones = convert_to_number(self.answer["ones"])
        remainder = convert_to_number(self.answer["remainder"].replace("R", "")) if self.answer["remainder"] else 0
        user_answer = (tens + ones, remainder)

        if self.current_question[-1] == "mult":
            correct_answer = (self.current_question[0] * self.current_question[1], 0)
            points_awarded = 1 if user_answer == correct_answer else -5
        elif self.current_question[-1] == "div":
            correct_answer = (self.current_question[0] // self.current_question[1], 0)
            points_awarded = 2 if user_answer == correct_answer else -3
        else:  # div_rest
            correct_answer = (self.current_question[0] // self.current_question[1], self.current_question[2])
            points_awarded = 5 if user_answer == correct_answer else -3

        if user_answer == correct_answer:
            result_text = f"{user_answer[0]}" + (f" R{user_answer[1]}" if user_answer[1] else "") + " ist RICHTIG!"
            self.points += points_awarded
            self._feedback(True)
            self.prev_question_label.color = (0, 1, 0, 1)
        else:
            correct_text = f"{correct_answer[0]}" + (f" R{correct_answer[1]}" if correct_answer[1] else "")
            result_text = (
                f"{user_answer[0]}" + (f" R{user_answer[1]}" if user_answer[1] else "") +
                f" ist FALSCH!\n>>> {self.question} = {correct_text} <<<"
            )
            self.points = max(0, self.points + points_awarded)
            self._feedback(False)
            self.prev_question_label.color = (1, 0, 0, 1)

        self.prev_question_label.text = result_text
        self.points_label.text = f"Punkte: {self.points}"

        self.generate_question()
        self.clear_input()

    def update_timer(self, dt):
        if self.time_left > 0:
            self.time_left -= 1
            self.timer_label.text = f"Zeit: {self.time_left} s"
        else:
            Clock.unschedule(self.update_timer)
            self.end_game()

    def end_game(self):
        self.current_view = "endgame"
        self.layout.clear_widgets()

        self.layout.add_widget(Label(text=f"Zeit abgelaufen! Deine Punkte: {self.points}", font_size=scale_font(28)))
        self.name_input = TextInput(hint_text="Dein Name", font_size=scale_font(24), multiline=False)
        self.layout.add_widget(self.name_input)

        submit_btn = Button(text="Speichern", font_size=scale_font(24), on_press=self.save_highscore)
        self.layout.add_widget(submit_btn)

        cancel_btn = Button(text="Zurück zum Menü", font_size=scale_font(24), on_press=self.return_to_main_menu)
        self.layout.add_widget(cancel_btn)

    def save_highscore(self, instance):
        player_name = str(self.name_input.text).strip() if str(self.name_input.text).strip() else "Anonym"
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

        if self.category not in self.highscores:
            self.highscores[self.category] = []

        new_entry = {
            "name": player_name,
            "points": self.points,
            "date": timestamp,
            "app_version": __version__,
            "schema_version": HIGHSCORE_SCHEMA_VERSION,
        }

        self.highscores[self.category].append(new_entry)
        self.highscores[self.category] = sorted(
            self.highscores[self.category],
            key=lambda x: x.get("points", 0),
            reverse=True,
        )[:10]

        self._save_highscores_file()
        self.last_new_entry = new_entry

        self.show_success_screen(new_entry)

    def show_success_screen(self, entry):
        self.current_view = "success"
        self.layout.clear_widgets()

        category_display = next((k for k, v in CATEGORIES.items() if v == self.category), self.category)
        pts = entry.get("points", 0)
        name = entry.get("name", "Anonym")

        self.layout.add_widget(Label(text="Highscore gespeichert!", font_size=scale_font(30)))
        self.layout.add_widget(Label(text=f"{name} — {pts} Punkte", font_size=scale_font(28)))
        self.layout.add_widget(Label(text=f"Modus: {category_display}", font_size=scale_font(24)))

        share_btn = Button(text="Erfolg teilen", font_size=scale_font(24), on_press=self.share_achievement)
        self.layout.add_widget(share_btn)

        back_btn = Button(text="Zurück zum Menü", font_size=scale_font(24), on_press=self.return_to_main_menu)
        self.layout.add_widget(back_btn)


if __name__ == "__main__":
    MathTrainer().run()
