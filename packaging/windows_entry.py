"""PyInstaller entry point for the Windows executable build.

Not part of the installable package - used only by
``.github/workflows/release-windows-exe.yml`` to produce ``formharvester.exe``.
"""

from formharvester.cli import main

if __name__ == "__main__":
    main()
