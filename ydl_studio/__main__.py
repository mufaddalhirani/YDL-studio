"""Command-line entry point for YDL Studio."""

from __future__ import annotations

import sys

from . import APP_NAME, __version__

_USAGE = f"""\
{APP_NAME} {__version__}

Usage:
  ydl-studio                 Open the app.
  ydl-studio URL [URL ...]   Open the app with links ready in the download bar.
  ydl-studio --version       Print the version and exit.
  ydl-studio --help          Show this message and exit.
"""


def main() -> None:
    args = sys.argv[1:]
    if any(argument in ("-h", "--help") for argument in args):
        print(_USAGE, end="")
        return
    if any(argument in ("-V", "--version") for argument in args):
        print(f"{APP_NAME} {__version__}")
        return

    urls: list[str] = []
    if args:
        from .media import parse_urls

        urls, invalid = parse_urls(" ".join(args))
        for token in invalid:
            print(f"Ignoring invalid URL: {token}", file=sys.stderr)
        if not urls:
            print("No valid URLs were provided.", file=sys.stderr)
            print(_USAGE, end="", file=sys.stderr)
            raise SystemExit(2)

    from .app import run

    run(urls or None)


if __name__ == "__main__":
    main()
