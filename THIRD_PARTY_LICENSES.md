# Third-party software

Kickhero itself is MIT-licensed (see [LICENSE](LICENSE)). The Windows installer bundles the following
open-source components, each under its own licence. Their full licence texts are included in the
installed app folder (in each package's `*.dist-info` folder, and `ffmpeg/LICENSE.txt`).

| Component | Used for | Licence |
|---|---|---|
| [Qt for Python (PySide6)](https://www.qt.io/qt-for-python) | user interface | LGPL-3.0 (dynamically linked; you may replace the Qt libraries in the install folder) |
| [PyTorch](https://pytorch.org) | running the separation models | BSD-3-Clause / Apache-2.0 |
| [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) | stem separation | MIT |
| [ONNX Runtime](https://onnxruntime.ai) | model runtime (audio-separator dependency) | MIT |
| [FFmpeg](https://ffmpeg.org) (LGPL build by [BtbN](https://github.com/BtbN/FFmpeg-Builds)) | reading and writing audio | LGPL-2.1-or-later; source: https://ffmpeg.org/download.html |
| [librosa](https://librosa.org) | onset and tempo detection | ISC |
| [NumPy](https://numpy.org), [SciPy](https://scipy.org), [Numba](https://numba.pydata.org) | numerics | BSD |
| [python-soxr](https://github.com/dofuuz/python-soxr) / libsoxr | resampling | LGPL-2.1-or-later |
| [soundfile](https://github.com/bastibe/python-soundfile) / libsndfile | audio files | BSD-3-Clause / LGPL-2.1 |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) / PortAudio | audio output | MIT |
| [python-rtmidi](https://github.com/SpotlightKid/python-rtmidi) / RtMidi | MIDI input from the kit | MIT |
| [pretty_midi](https://github.com/craffel/pretty-midi), [mido](https://github.com/mido/mido) | MIDI files | MIT |
| [Python](https://python.org) | runtime | PSF License |

## Separation models (not bundled)

The models are downloaded from their publishers on first use, into `~/.cache/audio-separator-models`:

- **htdemucs_ft** (Hybrid Transformer Demucs, fine-tuned) by Meta AI Research: MIT, https://github.com/facebookresearch/demucs
- **MDX23C DrumSep** by aufr33 and jarredou: https://github.com/jarredou/models

Please check the model licences yourself before using conversions commercially.
