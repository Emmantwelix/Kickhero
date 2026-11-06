#!/usr/bin/env python3
"""Command-line entry point kept at the project root; the code lives in kickhero/pipeline/song2drums.py."""

from kickhero.pipeline.song2drums import *  # noqa: F401,F403  (song2drums_gui.py uses build_parser, SONG_EXTS)
from kickhero.pipeline.song2drums import main

if __name__ == "__main__":
    main()
