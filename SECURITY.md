# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 2.x | Yes |
| 1.x (`yt-dlp-gui`) | No — the prototype is unmaintained |

YDL Studio ships fixes forward. If you are on an older 2.x release, reproduce the
problem on the latest one before reporting.

## Reporting a vulnerability

Please use [GitHub's private vulnerability reporting](https://github.com/mufaddalhirani/YDL-studio/security/advisories/new)
rather than a public issue. You should get a response within seven days. Do not open a
public issue, pull request or discussion for an unfixed vulnerability.

This project is a hobby desktop application maintained by one person, so there is no
bug bounty and no formal disclosure timeline. That does not change how seriously reports
are treated.

## What is in scope

- Anything that lets a malicious link, filename, playlist entry or `cookies.txt` file
  write outside the download folder, execute code, or leak data.
- Argument injection through the settings form or the *Advanced* arguments field.
- Path traversal when revealing or opening a downloaded file.
- A corrupt or hand-edited `config.json` / `history.json` crashing or hijacking the app.

## What is out of scope

- yt-dlp's own handling of a site. If a site serves something malicious, that is an
  upstream issue: report it to [yt-dlp](https://github.com/yt-dlp/yt-dlp#reporting-issues).
- Attacks that need you to hand over your machine, run an untrusted build, or approve a
  SmartScreen prompt for a file you did not download from this repository.
- Cookie extraction from your own browser at your request — that is the documented
  feature, and it only reads the browser you pick.

## How the app handles risky surface area

- yt-dlp is driven through its Python API, not a shell. No command line is ever
  constructed by string concatenation and there is no `shell=True` anywhere.
- Advanced arguments are parsed with `shlex` and run through `yt_dlp.parse_options` with
  `--ignore-config`; flags that would print help, exit, or self-update are rejected
  before they reach the downloader.
- Settings are validated on load against known-good value sets, and anything unusable
  falls back to a default instead of being trusted.
- Filename templates are checked before use, and output paths are confined to the
  download folder you chose.
- A corrupt settings or history file is moved aside with a timestamped `.corrupt-*`
  suffix rather than parsed, so a damaged file cannot become an injection vector.
- Cookies are read only when you ask for them and are never sent anywhere except the
  download you started.

## Privacy

- No telemetry, analytics, crash reporting or update pings. The app makes no network
  request except the ones yt-dlp makes for your downloads and the FFmpeg installer when
  you press that button.
- Settings, history and logs stay in `%APPDATA%\YDL Studio` on your machine. History
  records the source URL and saved path of each download; clear it from the History page
  if that matters to you.

## Supply chain

- Dependencies are declared in `pyproject.toml` and mirrored in `requirements.txt`:
  customtkinter, Pillow, yt-dlp and pystray. Nothing is fetched at install time beyond
  those.
- Release builds are produced by GitHub Actions from the tagged commit, so a build can be
  traced to a specific source revision. They are not code-signed, which is why
  SmartScreen warns on first run — see the README.
- The FFmpeg installer downloads the official gyan.dev build over HTTPS, verifies the
  archive unpacks and that the binaries report a version, and installs into the app's own
  data folder rather than a system directory.
