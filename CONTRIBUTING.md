# Contributing to YDL Studio

Thanks for taking the interest. This file covers what a good contribution looks like
here; if something is unclear, open an issue and ask.

## Before you start

- Windows 10 or 11, and Python 3.10 or newer.
- Read [README.md](README.md) — the *Development* section has the layout of the package.
- For anything larger than a typo fix, open an issue first so we can agree on the shape
  before you spend the time.

## Environment

```powershell
git clone https://github.com/mufaddalhirani/YDL-studio.git
cd YDL-studio

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
python -m ydl_studio
```

## Making a change

1. Branch off `main`: `git checkout -b fix/playlist-item-range`.
2. Keep the change to one idea. A bug fix should not carry unrelated cleanup.
3. Add or adjust a test when behaviour changes. Tests must not hit the network — see
   `tests/test_integration.py` for the local HTTP server pattern.
4. Run the checks:

   ```powershell
   pytest
   ruff check ydl_studio scripts tests
   ```

5. If you changed the UI, run the app and look at it in both dark and light themes.
   Colour and spacing bugs are easy to miss in a single screenshot.
6. Update [CHANGELOG.md](CHANGELOG.md) under *Unreleased* if the change is user-visible.
7. Open a pull request that explains **what** changed and **why**. Link the issue.

## Conventions

- Python 3.10 syntax with `from __future__ import annotations`; 100-column lines.
- Ruff is the linter (`E4`, `E7`, `E9`, `F`, `I`, `UP`, `B`). Keep it clean; CI will not
  let it slide.
- Colours, fonts and spacing live in `ydl_studio/theme.py`. Add a token there rather than
  hard-coding a hex value in a widget.
- Nothing heavy runs on the UI thread. Background work communicates through the queues in
  `ydl_studio/queue.py` and is drained by `App._pump`.
- User input is validated in `ydl_studio/config.py` on load, so a hand-edited
  `config.json` can never crash the app or inject arguments into yt-dlp.

## Reporting a bug

Include the app version (bottom of the sidebar), the exact steps, and what you expected
instead. Site-specific download failures are usually yt-dlp problems rather than app
problems — attach the console output or the log tail from **Settings → Output → Folders →
Logs**, and say whether `pip install -U yt-dlp` already fixed it.

## Suggestions

Feature requests are welcome, with one caveat: this app is a front end for yt-dlp, not a
media library. Anything that duplicates yt-dlp's own options belongs in the *Advanced*
argument field rather than a new button.

## License

By opening a pull request you confirm the contribution is yours to give and you license
it under the [MIT License](LICENSE).
