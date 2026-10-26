"""Frozen-application entry point used by ``scripts/YDL-Studio.spec``.

PyInstaller compiles the script it is given as a top-level ``__main__`` module,
so it cannot be ``ydl_studio/__main__.py`` itself: that file needs its package
context for relative imports. This launcher keeps the packaged build and
``python -m ydl_studio`` on exactly the same code path.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ydl_studio.__main__ import main  # noqa: E402 - needs the path above

if __name__ == "__main__":
    main()
