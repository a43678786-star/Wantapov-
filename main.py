"""
Retro Game Library — Python-only, Kivy + PyBoy
------------------------------------------------
A touch-first, landscape-locked frontend for running Game Boy ROMs that the
user supplies themselves. The emulation core is PyBoy (open source, pure
Python) — this file focuses on the frontend: library, search/settings,
ROM import, and an in-game touch overlay (D-Pad, A/B, Start/Select).

REQUIREMENTS (install on your dev machine / target these in buildozer.spec):
    pip install kivy pyboy plyer

NOTE ON THE PyBoy API:
    PyBoy's public API changed between major versions. This file is written
    against PyBoy 2.x:
        pyboy = PyBoy(rom_path, window="null")   # headless render, we pull frames ourselves
        pyboy.tick()                              # advance one frame
        pyboy.screen.ndarray                      # (144, 160, 4) RGBA numpy array
        pyboy.button(name)                        # e.g. "a", "b", "up", "down", "left",
                                                    #      "right", "start", "select"
                                                    #      -> press, auto-released by PyBoy
        pyboy.button_release(name)                # not used for the auto version above
        pyboy.save_state(file_like) / load_state(file_like)
    If your installed PyBoy version differs, the calls in GBCore below are the
    only place you should need to adjust (search for "PYBOY API").

WHY NO FROM-SCRATCH CPU/PPU:
    A cycle-accurate Game Boy core (LR35902 CPU, PPU, timers, MBC banking,
    APU) is thousands of lines and months of hardware-accuracy debugging.
    PyBoy already does this reliably in pure Python, so we use it as the
    "emulators/gameboy" core and spend our effort on the platform around it.

LANDSCAPE LOCK:
    Kivy itself can't lock phone orientation — that's an OS-level setting.
    On Android this is controlled by buildozer.spec:
        orientation = landscape
    (see the buildozer.spec file provided alongside this one). On desktop,
    we just size the dev window landscape so the layout can be tested.
"""

import os
import json
import time

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, RoundedRectangle, Ellipse
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.properties import StringProperty, BooleanProperty
from kivy.metrics import dp

# Desktop dev sizing only — has no effect on a packaged Android build.
Window.size = (960, 540)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
ROMS_DIR = os.path.join(DATA_DIR, "roms", "gameboy")
SAVES_DIR = os.path.join(DATA_DIR, "saves")
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")

for d in (DATA_DIR, ROMS_DIR, SAVES_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Palette — dark cards on a bright blue/cyan gradient, matches the brief.
# ---------------------------------------------------------------------------
COL_BG_TOP = (0.02, 0.53, 0.98, 1)
COL_BG_BOTTOM = (0.0, 0.93, 0.99, 1)
COL_CARD = (0.06, 0.07, 0.10, 0.92)
COL_CARD_BORDER = (1, 1, 1, 0.08)
COL_ACCENT = (0.0, 0.93, 0.99, 1)
COL_TEXT = (1, 1, 1, 0.95)
COL_TEXT_DIM = (1, 1, 1, 0.55)
COL_BTN = (1, 1, 1, 0.14)


# ---------------------------------------------------------------------------
# Library persistence
# ---------------------------------------------------------------------------
def load_library():
    if os.path.exists(LIBRARY_FILE):
        try:
            with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"games": [], "favorites": [], "recent": []}


def save_library(lib):
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)


LIBRARY = load_library()


# ---------------------------------------------------------------------------
# Background: soft diagonal gradient, no image assets needed
# ---------------------------------------------------------------------------
class GradientBG(Widget):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self._build_texture()
        self.bind(pos=self._update, size=self._update)

    def _build_texture(self):
        tex = Texture.create(size=(2, 2), colorfmt="rgba")
        top = bytes(int(c * 255) for c in COL_BG_TOP)
        bot = bytes(int(c * 255) for c in COL_BG_BOTTOM)
        tex.blit_buffer(bot + bot + top + top, colorfmt="rgba", bufferfmt="ubyte")
        tex.wrap = "clamp_to_edge"
        self._rect.texture = tex

    def _update(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size


# ---------------------------------------------------------------------------
# Reusable "card" style button for the library grid
# ---------------------------------------------------------------------------
class GameCard(BoxLayout):
    def __init__(self, title, subtitle, on_press, **kw):
        super().__init__(orientation="vertical", padding=dp(10), spacing=dp(4), **kw)
        with self.canvas.before:
            Color(*COL_CARD)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            Color(*COL_CARD_BORDER)
            self._border = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(pos=self._sync, size=self._sync)

        thumb = Widget(size_hint=(1, 0.62))
        with thumb.canvas:
            Color(0.15, 0.85, 0.95, 0.18)
            self._thumb_rect = RoundedRectangle(pos=thumb.pos, size=thumb.size, radius=[dp(10)])
        thumb.bind(pos=lambda *_: setattr(self._thumb_rect, "pos", thumb.pos),
                   size=lambda *_: setattr(self._thumb_rect, "size", thumb.size))
        self.add_widget(thumb)

        lbl = Label(text=title, color=COL_TEXT, bold=True, font_size=dp(14),
                     size_hint=(1, 0.22), halign="left", valign="middle")
        lbl.bind(size=lambda *_: setattr(lbl, "text_size", lbl.size))
        self.add_widget(lbl)

        sub = Label(text=subtitle, color=COL_TEXT_DIM, font_size=dp(11),
                    size_hint=(1, 0.16), halign="left", valign="top")
        sub.bind(size=lambda *_: setattr(sub, "text_size", sub.size))
        self.add_widget(sub)

        self._on_press = on_press

    def _sync(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.pos = self.pos
        self._border.size = self.size

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and touch.grab_current is None:
            self._on_press()
            return True
        return super().on_touch_up(touch)


# ---------------------------------------------------------------------------
# Library screen — the main screen. Sidebar categories, grid of games,
# Search + Settings tucked at the bottom as small entries (not big tiles).
# ---------------------------------------------------------------------------
class LibraryScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.active_filter = "all"
        self.search_query = ""

        root = BoxLayout(orientation="horizontal")
        self.add_widget(GradientBGHost(root))

        # --- sidebar ---
        sidebar = BoxLayout(orientation="vertical", size_hint=(0.22, 1),
                             padding=dp(14), spacing=dp(8))
        title = Label(text="[b]GAME LIBRARY[/b]", markup=True, color=COL_TEXT,
                      font_size=dp(16), size_hint=(1, None), height=dp(36))
        sidebar.add_widget(title)

        self.filter_buttons = {}
        categories = [
            ("all", "كل الألعاب"),
            ("gb", "Game Boy"),
            ("gbc", "Game Boy Color"),
            ("nes", "NES"),
            ("sega", "Sega"),
            ("favorites", "المفضلة"),
            ("recent", "آخر الألعاب"),
        ]
        for key, label in categories:
            b = self._sidebar_button(label, key)
            self.filter_buttons[key] = b
            sidebar.add_widget(b)

        sidebar.add_widget(Widget())  # spacer pushes settings/search to bottom

        search_btn = self._sidebar_button("🔍 البحث", "search", small=True)
        settings_btn = self._sidebar_button("⚙️ الإعدادات", "settings", small=True)
        sidebar.add_widget(search_btn)
        sidebar.add_widget(settings_btn)

        root.add_widget(sidebar)

        # --- main content: search bar + grid ---
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))

        topbar = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(8))
        self.search_input = TextInput(
            hint_text="ابحث عن لعبة...", multiline=False, size_hint=(0.6, 1),
            background_color=(1, 1, 1, 0.08), foreground_color=COL_TEXT,
            hint_text_color=COL_TEXT_DIM, cursor_color=COL_ACCENT, padding=[dp(10), dp(10)],
        )
        self.search_input.bind(text=self._on_search_text)
        import_btn = self._flat_button("+ استيراد ROM", self._import_rom)
        topbar.add_widget(self.search_input)
        topbar.add_widget(Widget(size_hint=(0.15, 1)))
        topbar.add_widget(import_btn)
        content.add_widget(topbar)

        scroll = ScrollView(size_hint=(1, 1))
        self.grid = GridLayout(cols=4, spacing=dp(12), size_hint_y=None, padding=dp(4))
        self.grid.bind(minimum_height=self.grid.setter("height"))
        scroll.add_widget(self.grid)
        content.add_widget(scroll)

        root.add_widget(content)

        self._refresh_grid()

    def _sidebar_button(self, text, key, small=False):
        btn = Button(text=text, size_hint=(1, None), height=dp(30) if small else dp(36),
                     background_normal="", background_color=(0, 0, 0, 0),
                     color=COL_TEXT_DIM if small else COL_TEXT,
                     font_size=dp(12) if small else dp(13), halign="left")
        btn.bind(size=lambda *_: setattr(btn, "text_size", btn.size))

        def _press(instance, key=key):
            if key == "search":
                App.get_running_app().root.current = "library"
                self.search_input.focus = True
                return
            if key == "settings":
                App.get_running_app().root.current = "settings"
                return
            self.active_filter = key
            self._refresh_grid()

        btn.bind(on_release=_press)
        return btn

    def _flat_button(self, text, callback):
        btn = Button(text=text, size_hint=(0.25, 1), background_normal="",
                     background_color=COL_BTN, color=COL_TEXT, font_size=dp(12))
        btn.bind(on_release=lambda *_: callback())
        return btn

    def _on_search_text(self, instance, value):
        self.search_query = value.strip().lower()
        self._refresh_grid()

    def _import_rom(self):
        # Uses plyer's native file chooser (works on Android with storage
        # permission granted; falls back to a simple path prompt on desktop
        # if plyer/native chooser isn't available).
        try:
            from plyer import filechooser
            filechooser.open_file(on_selection=self._on_rom_chosen,
                                   filters=[("Game Boy ROM", "*.gb", "*.gbc")])
        except Exception as e:
            self._show_message(f"تعذر فتح منتقي الملفات: {e}\n"
                                f"ضع ملفات ROM يدويًا داخل: {ROMS_DIR}")

    def _on_rom_chosen(self, selection):
        if not selection:
            return
        src = selection[0]
        if not src.lower().endswith((".gb", ".gbc")):
            self._show_message("الملف يجب أن يكون بصيغة .gb أو .gbc")
            return
        import shutil
        filename = os.path.basename(src)
        dest = os.path.join(ROMS_DIR, filename)
        try:
            if os.path.abspath(src) != os.path.abspath(dest):
                shutil.copy(src, dest)
        except Exception as e:
            self._show_message(f"فشل نسخ الملف: {e}")
            return

        system = "gbc" if filename.lower().endswith(".gbc") else "gb"
        entry = {
            "id": filename,
            "title": os.path.splitext(filename)[0],
            "system": system,
            "path": dest,
        }
        if not any(g["id"] == entry["id"] for g in LIBRARY["games"]):
            LIBRARY["games"].append(entry)
            save_library(LIBRARY)
        self._refresh_grid()

    def _show_message(self, text):
        # Lightweight inline banner instead of a blocking popup, to keep
        # things touch/light as requested.
        print(text)  # also surfaced in logs; replace with a Kivy Popup if desired

    def _matching_games(self):
        games = LIBRARY["games"]
        f = self.active_filter
        if f == "favorites":
            games = [g for g in games if g["id"] in LIBRARY["favorites"]]
        elif f == "recent":
            recent_ids = LIBRARY["recent"][:12]
            games = [g for g in games if g["id"] in recent_ids]
            games.sort(key=lambda g: recent_ids.index(g["id"]))
        elif f != "all":
            games = [g for g in games if g["system"] == f]

        if self.search_query:
            games = [g for g in games if self.search_query in g["title"].lower()]
        return games

    def _refresh_grid(self):
        self.grid.clear_widgets()
        games = self._matching_games()
        if not games:
            self.grid.add_widget(Label(
                text="لا توجد ألعاب هنا بعد.\nاضغط \"+ استيراد ROM\" لإضافة لعبة.",
                color=COL_TEXT_DIM, size_hint_y=None, height=dp(120)))
            return
        for g in games:
            card = GameCard(
                title=g["title"], subtitle=g["system"].upper(),
                on_press=(lambda g=g: self._launch(g)),
                size_hint=(None, None), size=(dp(180), dp(150)),
            )
            self.grid.add_widget(card)

    def _launch(self, game):
        if game["id"] not in LIBRARY["recent"]:
            LIBRARY["recent"].insert(0, game["id"])
        else:
            LIBRARY["recent"].remove(game["id"])
            LIBRARY["recent"].insert(0, game["id"])
        LIBRARY["recent"] = LIBRARY["recent"][:20]
        save_library(LIBRARY)

        sm = App.get_running_app().root
        play_screen = sm.get_screen("play")
        play_screen.load_game(game)
        sm.current = "play"

    def on_pre_enter(self):
        self._refresh_grid()


class GradientBGHost(BoxLayout):
    """Wraps content with the gradient painted behind it."""
    def __init__(self, content, **kw):
        super().__init__(**kw)
        self._bg = GradientBG(size=self.size, pos=self.pos)
        self.add_widget(self._bg)
        self.add_widget(content)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size


# ---------------------------------------------------------------------------
# Settings screen — deliberately small/secondary, per the brief
# ---------------------------------------------------------------------------
class SettingsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(12))
        self.add_widget(GradientBGHost(root))

        back = self._btn("← رجوع", lambda: self._go("library"))
        root.add_widget(back)
        root.add_widget(Label(text="[b]الإعدادات[/b]", markup=True, color=COL_TEXT,
                               font_size=dp(20), size_hint=(1, None), height=dp(40)))
        root.add_widget(Label(text="مجلد ROMs:\n" + ROMS_DIR, color=COL_TEXT_DIM,
                               size_hint=(1, None), height=dp(60)))
        root.add_widget(Label(text="مجلد الحفظ:\n" + SAVES_DIR, color=COL_TEXT_DIM,
                               size_hint=(1, None), height=dp(60)))
        root.add_widget(Widget())

    def _btn(self, text, cb):
        b = Button(text=text, size_hint=(None, None), size=(dp(120), dp(36)),
                   background_normal="", background_color=COL_BTN, color=COL_TEXT)
        b.bind(on_release=lambda *_: cb())
        return b

    def _go(self, name):
        App.get_running_app().root.current = name


# ---------------------------------------------------------------------------
# Touch overlay: D-Pad + A/B + Start/Select, translucent, doesn't block screen
# ---------------------------------------------------------------------------
class TouchButton(Widget):
    """A round translucent touch button that reports press/release."""
    pressed = BooleanProperty(False)

    def __init__(self, label, on_press, on_release, radius=dp(28), **kw):
        super().__init__(size=(radius * 2, radius * 2), **kw)
        self.radius = radius
        self.label_text = label
        self._on_press = on_press
        self._on_release = on_release
        self._touch_id = None
        with self.canvas:
            self._col = Color(1, 1, 1, 0.18)
            self._circle = Ellipse(pos=self.pos, size=self.size)
        self._lbl = Label(text=label, color=(1, 1, 1, 0.85), font_size=dp(13), bold=True)
        self.add_widget(self._lbl)
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *a):
        self._circle.pos = self.pos
        self._circle.size = self.size
        self._lbl.center = (self.center_x, self.center_y)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self._touch_id is None:
            self._touch_id = touch.uid
            touch.grab(self)
            self._col.a = 0.38
            self._on_press()
            return True
        return False

    def on_touch_up(self, touch):
        if touch.grab_current is self and touch.uid == self._touch_id:
            touch.ungrab(self)
            self._touch_id = None
            self._col.a = 0.18
            self._on_release()
            return True
        return False


class DPad(Widget):
    """Four directional touch zones arranged as a plus, mapped to GB input."""
    def __init__(self, on_dir, size=dp(140), **kw):
        super().__init__(size=(size, size), **kw)
        self._on_dir = on_dir  # callback(direction, pressed: bool)
        self._active = set()
        with self.canvas:
            Color(1, 1, 1, 0.14)
            self._bg = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _direction_for(self, x, y):
        cx, cy = self.center
        dx, dy = x - cx, y - cy
        if (dx * dx + dy * dy) ** 0.5 < self.width * 0.15:
            return None
        import math
        angle = math.degrees(math.atan2(dy, dx))
        if -45 <= angle < 45:
            return "right"
        if 45 <= angle < 135:
            return "up"
        if -135 <= angle < -45:
            return "down"
        return "left"

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.grab(self)
            d = self._direction_for(*touch.pos)
            if d:
                self._active.add(d)
                self._on_dir(d, True)
            return True
        return False

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            new_d = self._direction_for(*touch.pos)
            for old in list(self._active):
                if old != new_d:
                    self._active.discard(old)
                    self._on_dir(old, False)
            if new_d and new_d not in self._active:
                self._active.add(new_d)
                self._on_dir(new_d, True)
            return True
        return False

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            for d in list(self._active):
                self._on_dir(d, False)
            self._active.clear()
            return True
        return False


# ---------------------------------------------------------------------------
# Game Boy emulation core wrapper (PyBoy)
# ---------------------------------------------------------------------------
class GBCore:
    def __init__(self, rom_path):
        from pyboy import PyBoy  # imported lazily so the library screen
                                   # works even before pyboy is installed
        # PYBOY API: window="null" means we pull frames manually instead of
        # letting PyBoy open its own SDL2 window (we render into our own
        # Kivy texture instead).
        self.pyboy = PyBoy(rom_path, window="null", sound_emulated=False)
        self.rom_path = rom_path

    def tick(self):
        self.pyboy.tick()

    def frame_rgba(self):
        # PYBOY API: pyboy.screen.ndarray -> (144, 160, 4) uint8 RGBA
        return self.pyboy.screen.ndarray

    def button(self, name, pressed):
        # PYBOY API: pyboy.button(name) presses+auto-releases; for held
        # input (D-pad while moving) we instead call the low level API if
        # available, falling back to the simple press call.
        try:
            if pressed:
                self.pyboy.button_press(name)
            else:
                self.pyboy.button_release(name)
        except AttributeError:
            # Older/alternate PyBoy versions: single-shot press only.
            if pressed:
                self.pyboy.button(name)

    def save_state(self, path):
        with open(path, "wb") as f:
            self.pyboy.save_state(f)

    def load_state(self, path):
        if os.path.exists(path):
            with open(path, "rb") as f:
                self.pyboy.load_state(f)

    def stop(self):
        self.pyboy.stop(save=False)


# ---------------------------------------------------------------------------
# Play screen
# ---------------------------------------------------------------------------
class PlayScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.core = None
        self.game = None
        self.paused = False
        self._event = None

        self.layout = BoxLayout(orientation="horizontal")
        self.add_widget(self.layout)

        with self.layout.canvas.before:
            Color(0.02, 0.02, 0.03, 1)
            self._bg_rect = Rectangle(pos=self.layout.pos, size=self.layout.size)
        self.layout.bind(pos=self._sync_bg, size=self._sync_bg)

        # left control cluster
        left = BoxLayout(orientation="vertical", size_hint=(0.22, 1), padding=dp(14))
        self.dpad = DPad(on_dir=self._on_dpad, size_hint=(1, 0.7))
        # DPad expects a fixed pixel size widget; wrap it centered
        dpad_holder = BoxLayout(size_hint=(1, 0.7))
        self.dpad = DPad(on_dir=self._on_dpad)
        dpad_holder.add_widget(Widget())
        dpad_holder.add_widget(self.dpad)
        dpad_holder.add_widget(Widget())
        left.add_widget(dpad_holder)

        transport = BoxLayout(size_hint=(1, 0.3), spacing=dp(8))
        self.btn_pause = self._small_btn("⏸", self._toggle_pause)
        self.btn_reset = self._small_btn("⟲", self._reset)
        self.btn_back = self._small_btn("←", self._go_back)
        transport.add_widget(self.btn_back)
        transport.add_widget(self.btn_pause)
        transport.add_widget(self.btn_reset)
        left.add_widget(transport)

        self.layout.add_widget(left)

        # center: the actual game screen
        center = BoxLayout(orientation="vertical", size_hint=(0.56, 1),
                            padding=dp(10))
        self.game_image = Image(size_hint=(1, 1), allow_stretch=True, keep_ratio=True)
        center.add_widget(self.game_image)
        self.layout.add_widget(center)

        # right control cluster: A/B + Start/Select
        right = BoxLayout(orientation="vertical", size_hint=(0.22, 1), padding=dp(14))
        ab_row = BoxLayout(size_hint=(1, 0.6))
        self.btn_b = TouchButton("B", lambda: self._button("b", True),
                                  lambda: self._button("b", False))
        self.btn_a = TouchButton("A", lambda: self._button("a", True),
                                  lambda: self._button("a", False))
        ab_row.add_widget(Widget())
        ab_row.add_widget(self.btn_b)
        ab_row.add_widget(self.btn_a)
        right.add_widget(ab_row)

        ss_row = BoxLayout(size_hint=(1, 0.25), spacing=dp(10))
        self.btn_select = TouchButton("SELECT", lambda: self._button("select", True),
                                       lambda: self._button("select", False), radius=dp(22))
        self.btn_start = TouchButton("START", lambda: self._button("start", True),
                                      lambda: self._button("start", False), radius=dp(22))
        ss_row.add_widget(self.btn_select)
        ss_row.add_widget(self.btn_start)
        right.add_widget(ss_row)
        right.add_widget(Widget(size_hint=(1, 0.15)))

        self.layout.add_widget(right)

    def _sync_bg(self, *a):
        self._bg_rect.pos = self.layout.pos
        self._bg_rect.size = self.layout.size

    def _small_btn(self, text, cb):
        b = Button(text=text, background_normal="", background_color=COL_BTN,
                   color=COL_TEXT, font_size=dp(16))
        b.bind(on_release=lambda *_: cb())
        return b

    # -- lifecycle --------------------------------------------------------
    def load_game(self, game):
        self.game = game
        if self.core:
            self.core.stop()
            self.core = None
        if game["system"] not in ("gb", "gbc"):
            print(f"لا يوجد محاكي مدعوم بعد لنظام: {game['system']}")
            App.get_running_app().root.current = "library"
            return
        try:
            self.core = GBCore(game["path"])
        except Exception as e:
            print(f"فشل تشغيل اللعبة: {e}")
            App.get_running_app().root.current = "library"
            return

        save_path = os.path.join(SAVES_DIR, game["id"] + ".state")
        self.core.load_state(save_path)

        self.paused = False
        self.btn_pause.text = "⏸"
        if self._event:
            self._event.cancel()
        # ~60 fps game loop
        self._event = Clock.schedule_interval(self._step, 1 / 60.0)

    def _step(self, dt):
        if self.core is None or self.paused:
            return
        self.core.tick()
        frame = self.core.frame_rgba()  # (144,160,4) uint8, top-to-bottom
        tex = Texture.create(size=(160, 144), colorfmt="rgba")
        # Kivy textures are bottom-up; flip vertically for correct orientation.
        buf = frame[::-1, :, :].tobytes()
        tex.blit_buffer(buf, colorfmt="rgba", bufferfmt="ubyte")
        self.game_image.texture = tex

    def _on_dpad(self, direction, pressed):
        if self.core:
            self.core.button(direction, pressed)

    def _button(self, name, pressed):
        if self.core:
            self.core.button(name, pressed)

    def _toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.text = "▶" if self.paused else "⏸"

    def _reset(self):
        if self.game:
            self.load_game(self.game)

    def _go_back(self):
        if self.core and self.game:
            save_path = os.path.join(SAVES_DIR, self.game["id"] + ".state")
            try:
                self.core.save_state(save_path)
            except Exception as e:
                print(f"تعذر حفظ اللعبة: {e}")
        if self._event:
            self._event.cancel()
            self._event = None
        if self.core:
            self.core.stop()
            self.core = None
        App.get_running_app().root.current = "library"

    def on_leave(self, *a):
        if self._event:
            self._event.cancel()
            self._event = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class RetroLibraryApp(App):
    def build(self):
        self.title = "Retro Game Library"
        sm = ScreenManager(transition=NoTransition())
        sm.add_widget(LibraryScreen(name="library"))
        sm.add_widget(SettingsScreen(name="settings"))
        sm.add_widget(PlayScreen(name="play"))
        sm.current = "library"
        return sm

    def on_start(self):
        # Request Android storage permission for ROM import, if on Android.
        try:
            from android.permissions import request_permissions, Permission  # noqa
            request_permissions([Permission.READ_EXTERNAL_STORAGE,
                                  Permission.WRITE_EXTERNAL_STORAGE])
        except Exception:
            pass  # not running on Android / plyer not present — fine on desktop


if __name__ == "__main__":
    RetroLibraryApp().run()
