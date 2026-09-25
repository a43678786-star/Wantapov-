# Retro Game Library — first working slice

## Run it on desktop (fastest way to test)
```
pip install -r requirements.txt
python main.py
```
A landscape window opens with the library. Click **"+ استيراد ROM"** to import
a `.gb`/`.gbc` file you own the rights to, then tap its card to play.

## Run it on your Android phone
```
pip install buildozer
buildozer android debug deploy run
```
`buildozer.spec` already sets `orientation = landscape`, which is what forces
the phone into landscape when the app launches — this is an OS-level flag,
not something Kivy can do from Python alone, which is why it lives in the
spec file instead of `main.py`.

## What's real right now
- Full library UI: sidebar categories, search, grid of game cards, Settings
  and Search kept small at the bottom of the menu as you asked.
- ROM import (native file picker via `plyer`, falls back to a manual-copy
  instruction if the picker isn't available on your platform).
- A real, running Game Boy core via PyBoy — CPU/PPU/memory/timers/input all
  handled by PyBoy; this file renders its frame buffer into the Kivy UI.
- Touch D-Pad (single translucent circle, angle-based directions — feels
  better than 4 separate corner buttons) + A/B + Start/Select, translucent,
  press-and-release both wired to the core.
- Save state on exit, auto-load on re-entry, Pause/Resume, Reset.
- Landscape lock for the packaged Android build.

## What's NOT done yet (next steps)
1. **Verify the PyBoy call signatures against the version you install** —
   I wrote this against PyBoy 2.x's documented API (`window="null"`,
   `pyboy.screen.ndarray`, `button_press`/`button_release`). I don't have
   network access in this sandbox to `pip install` and run it myself, so
   please run it and tell me the first error, if any — likely a one-line fix.
2. **Split into the modular structure** (`ui/`, `emulators/`, `systems/`,
   `input/`, `settings/`) once you confirm this single file runs — I kept it
   as one file first, per your own fallback instruction.
3. **Other systems** (NES, Sega Master System, Game Gear, SNES, Genesis,
   PC Engine) — each needs its own emulation core the same way Game Boy uses
   PyBoy. There isn't one library that covers all of them, so each is a
   separate integration (e.g. a NES core would plug in the same way GBCore
   does here). Tell me which one to add next.
4. **Draggable/resizable touch buttons** — currently fixed layout; making
   them user-repositionable is a follow-up feature, not core plumbing.
5. **Real app icon / thumbnails** — cards currently show a placeholder tile;
   once you send real screenshots of your intended design I'll match it
   exactly instead of the current placeholder styling.
