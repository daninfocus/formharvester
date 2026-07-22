"""PyInstaller entry point for the Windows executable build.

Not part of the installable package - used only by
``.github/workflows/release-windows-exe.yml`` to produce ``formharvester.exe``.
The executable is the desktop app; the ``formharvester`` command installed by
pip is the CLI.
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

# Injected by PyInstaller, so it only exists inside a frozen build with a
# splash screen. Typed as Any because there is nothing to resolve against when
# running from source.
splash: Any
try:
    import pyi_splash  # ty: ignore[unresolved-import]

    splash = pyi_splash
except ImportError:
    splash = None

STAGES = ("loading modules", "starting browser engine", "preparing interface")


def _animate(stop: threading.Event) -> None:
    """Cycle the splash status text so the wait does not look frozen.

    The bootloader has already unpacked the archive by the time Python runs,
    so this covers the remaining cost: importing selenium, pywebview and
    pydantic, which is the slowest part of a cold start.
    """
    dots = itertools.cycle((".  ", ".. ", "..."))
    started = time.monotonic()
    while not stop.is_set():
        stage = STAGES[min(int((time.monotonic() - started) // 2), len(STAGES) - 1)]
        try:
            splash.update_text(f"{stage}{next(dots)}")
        except Exception:
            return  # splash already gone; nothing left to animate
        stop.wait(0.35)


def main() -> None:
    stop = threading.Event()
    if splash is not None:
        threading.Thread(target=_animate, args=(stop,), daemon=True).start()

    def close_splash() -> None:
        stop.set()
        if splash is not None:
            try:
                splash.close()
            except Exception:
                pass

    # Imported here, not at module scope, so the animation is already running
    # while the heavy imports happen.
    from formharvester.gui import launch

    launch(on_ready=close_splash)


if __name__ == "__main__":
    main()
