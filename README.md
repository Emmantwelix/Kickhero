# Kickhero

Turn songs into drum lessons and practise them on any electronic drum kit.

1. **Convert**: a song goes in; the drums are separated from the mix, split into kick, snare,
   hi-hat, toms and cymbals, and written out as a drum MIDI file (tempo detected, beat 1 on bar 1).
2. **Practise**: notes scroll toward a hit line, one lane per drum. Play along on your kit over USB
   and every hit is graded (Perfect / Good / OK / Miss) with early/late feedback.

Works with any kit that sends MIDI over USB. A short setup asks you to hit each pad once, and a
tap-along test measures your setup's delay. No kit? Play with the computer keyboard.

## Features

- **Songs**: drag songs onto the window; they're converted in the background. Practise with the
  drumless song playing along.
- **Practice tools**: speed 40-150%, loop any bars, auto speed-up, "wait for me" mode, turn lanes off to
  practise one limb, hear the drum part, results with stars and timing advice.
- **Beginner course**: 29 lessons in 8 units (keeping time, rock beats, kick variations, sixteenths,
  cymbals, fills, rudiments, ghost notes), unlocked one by one.
- **Any kit**: pad setup wizard, latency calibration, optional drum sounds from the app.

## Install (Windows)

Download `Kickhero-Setup-<version>.exe` from the [releases](../../releases) page and run it. The first
song you convert downloads the separation models (~1 GB, once). Conversion runs on the CPU: expect a few
minutes per song.

Each converted song gets a folder with `<song>_drums.mid`, `backing.ogg` (the song without drums) and
`<song>_drums.json` (tempo, the shift that put beat 1 on bar 1, source file, conversion settings).

## Running from source (Windows)

```bat
python -m venv env
env\Scripts\pip install -e .[dev]
Kickhero.bat                    :: the app (add songs, practise, kit setup)
song2drums_gui.bat              :: the stand-alone converter window (optional)
```

The first conversion downloads the separation models (~1 GB) to `~/.cache/audio-separator-models`.
Running from source needs [ffmpeg](https://ffmpeg.org) on your PATH (the installer bundles it).

### Building the installer

```bat
env\Scripts\pip install -e .[build]
env\Scripts\python packaging\build.py        :: -> build\installer\Kickhero-Setup-<version>.exe
```

Needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer step. Pushing a tag like `v0.1.0`
builds the installer on GitHub Actions and attaches it to a release.

### Command line

```bat
env\Scripts\python song2drums.py path\to\songs      :: song(s) -> drum_midi\<song>\<song>_drums.mid
env\Scripts\python drums2midi.py stems_folder -o drums.mid
env\Scripts\python -m pytest                          :: tests
```

## Project layout

```
kickhero/
  app.py           main window and shared services
  pipeline/        song -> stems -> drum MIDI (song2drums.py, drums2midi.py)
  kit/             MIDI input, pad mapping, latency calibration
  engine/          lessons, scoring, practice session (transport/loop/wait mode), audio
  course/          the beginner course: beginner.json (lessons as drum patterns) + loader
  ui/              pages: songs, course, practice (scrolling lanes), my kit
tests/             pytest
```

## Writing lessons

Course lessons live in `kickhero/course/beginner.json`. Each lane's part is written on a 16th-note grid,
16 characters per bar: `x` hit, `X` accent, `g` ghost note, `.` rest, `|` between bars:

```json
{"id": "rock-basic", "title": "The basic rock beat", "bpm": 70, "repeats": 4,
 "tip": "Kick on 1 and 3, snare on 2 and 4.",
 "pattern": {"hihat": "x.x.x.x.x.x.x.x.", "snare": "....x.......x...", "kick": "x.......x......."}}
```

Lanes: `kick snare hihat ride crash tom1 tom2 tom3`. `pytest` checks every pattern is well-formed.

## Licence

MIT, see [LICENSE](LICENSE). Bundled components and their licences: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Separation uses [audio-separator](https://github.com/nomadkaraoke/python-audio-separator)
with the htdemucs_ft and MDX23C DrumSep models, which are downloaded at first use and keep their own licences.
Please only convert music you have the right to use.
