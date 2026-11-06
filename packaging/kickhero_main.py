"""Entry point for the packaged app (PyInstaller). Also handles `Kickhero.exe --pipeline ...`."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from kickhero.app import main

    main()
