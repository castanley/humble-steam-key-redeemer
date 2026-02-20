# eNkrypt's Steam Redeemer

If you've had a Humble Bundle subscription running for months (or years), you probably have dozens — maybe hundreds — of unclaimed Steam keys sitting in your library. Redeeming them one by one is painfully tedious: reveal the key, copy it, paste it into Steam, hit next, repeat. This tool does all of that for you in one shot.

Bulk-redeem your Humble Bundle Steam keys automatically. Detects games you already own so you don't waste rate limits, preserves gift links for unrevealed keys, and handles Steam's rate limiting with automatic retries.

## Features

**Auto-Redeem** — Log into Humble + Steam, and the tool redeems all your unowned keys hands-free. Already-owned games are skipped. Unrevealed keys are only revealed if you don't already own the game (preserving gift links). Rate limits are handled automatically with a 1-hour cooldown.

**Export** — Dump your entire Humble key library to a timestamped CSV. Optionally sign into Steam to annotate each key with ownership status. Choose whether to include revealed keys, unrevealed keys, or both.

**Humble Choice Chooser** — Interactive month-by-month selector for picking unredeemed Humble Choice games. Shows ratings, lets you pick by number, and optionally auto-redeems the keys on Steam after choosing.

## How It Works

1. Signs into Humble Bundle (credentials or saved session). If Humble Guard is enabled on your account, you'll be emailed a code to enter.
2. Fetches all your order details concurrently (30 workers)
3. You pick a mode (or `--auto` skips straight to Auto-Redeem)
4. For Auto-Redeem:
   - Signs into Steam — scan the QR code with your Steam mobile app, or type your credentials manually (supports 2FA codes, Steam Guard, and email codes)
   - Fetches the full Steam app catalog via Web API to check what you own
   - Fuzzy-matches game titles to catch DLC/edition variants
   - Redeems unowned keys, skips owned ones, waits out rate limits
   - Logs results to CSV files (`redeemed.csv`, `already_owned.csv`, `errored.csv`)

Both Humble and Steam sessions are saved to `.state/` so you only need to log in once. Subsequent runs (including `--auto`) reuse the saved sessions until they expire.

### Steam Login

When signing into Steam, the tool first tries QR code login:

```
    █▀▀▀▀▀▀▀█ ▄▀█▀▄ █▀▀▀▀▀▀▀█
    █ █▀▀▀█ █ █▄ ▄█ █ █▀▀▀█ █
    █ █   █ █  ▀█▀  █ █   █ █
    █ ▀▀▀▀▀ █▀▄▀▄▀▄ █ ▀▀▀▀▀ █
    ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
         (example only)
```

Open the **Steam mobile app** > **Steam Guard** > **Confirm Sign In** (or tap the QR scanner icon), scan the code, and you're logged in — no need to type your username, password, or 2FA code. Press Enter to skip and type credentials instead.

If you skip the QR code and use credentials with 2FA enabled, the tool shows a code prompt while simultaneously polling for Steam mobile app approval. You can either type your TOTP code or just tap "Approve" on your phone — whichever happens first, the tool proceeds automatically.

## Requirements

- Python 3.9+
- A [Steam Web API key](https://steamcommunity.com/dev/apikey) (optional, for ownership detection)

## Setup

```bash
pip install -r requirements.txt
```

For ownership detection (recommended), add your Steam Web API key to `config.yaml`:
```yaml
steam_api_key: YOUR_KEY_HERE
```
Get one at https://steamcommunity.com/dev/apikey. You can also set `STEAM_API_KEY` as an environment variable.

If no API key is configured, the tool will prompt you to enter one or skip. Without it, you'll be asked whether to reveal and redeem all keys or only attempt already-revealed ones (preserving unrevealed keys as gift links).

## Usage

```bash
steam-redeemer              # Interactive TUI — full menu
steam-redeemer --auto       # Non-interactive auto-redeem for cron/scheduled runs
steam-redeemer --help       # Show all flags
```

Or from source:
```bash
python steam_redeem.py
python -m src
```

The interactive TUI uses arrow-key navigation and single-keypress shortcuts — no need to hit Enter on menus.

### Scheduled / Cron Mode

The idea: **run interactively once to set up your sessions, then schedule `--auto` for hands-free runs.** No credentials are stored — only session cookies in `.state/`.

#### First-time setup (interactive)

```bash
steam-redeemer
```

Log into Humble and Steam when prompted. The tool saves both sessions to `.state/`. If you have a Steam Web API key, enter it when asked (or add it to `config.yaml`) — this enables ownership detection so the tool doesn't waste rate-limit attempts on games you already own.

#### Scheduled runs

```bash
steam-redeemer --auto
```

In `--auto` mode the tool:
- Reuses saved sessions from `.state/` — no login prompts
- Skips the mode menu and goes straight to auto-redeem
- Skips unrevealed keys by default (preserving gift links)
- Exits with code 1 if either session has expired, with a clear error message

If sessions expire, just run interactively once to refresh them.

#### Cron example

Redeem new keys every 6 hours:
```
0 */6 * * * /path/to/steam-redeemer --auto >> /path/to/redeem.log 2>&1
```

#### Flags

| Flag | Description |
|------|-------------|
| `--auto` | Non-interactive mode — requires valid saved sessions in `.state/` |
| `--reveal-all` | With `--auto`: reveal and redeem unrevealed keys even without ownership data. By default, `--auto` only redeems already-revealed keys to preserve gift links for games you might want to give away. Use this flag if you don't care about gift links and want everything redeemed. |

## Portable Binary

The binaries are provided for convenience — you don't need them if you have Python installed. Just clone the repo, `pip install -r requirements.txt`, and run `python steam_redeem.py` directly.

Pre-built Windows and Linux binaries are available on the [Releases](../../releases) page for those who don't want to install Python or manage dependencies.

### Windows

1. Download `steam-redeemer.exe` from the latest release
2. Put it in its own folder (it creates `config.yaml` and `.state/` next to itself)
3. Double-click or run from Command Prompt / PowerShell
4. Windows SmartScreen may warn "Windows protected your PC" since the binary isn't signed — click **More info** then **Run anyway**

### Linux

1. Download `steam-redeemer` from the latest release
2. `chmod +x steam-redeemer && ./steam-redeemer`

### Build from source

```bash
pip install -r requirements.txt pyinstaller
pyinstaller steam-redeemer.spec
# Binary in dist/
```

## Rate Limits

Steam enforces strict activation limits (~50 successful / ~10 failed keys per hour). The auto-redeemer detects rate limiting and automatically waits 1 hour before retrying. Ownership detection helps minimize wasted attempts.

## Output Files

| File | Contents |
|------|----------|
| `redeemed.csv` | Successfully redeemed keys |
| `already_owned.csv` | Keys skipped (already owned or used elsewhere) |
| `errored.csv` | Keys that failed (region locked, invalid, etc.) |
| `skipped.txt` | Games with uncertain ownership (edit and rerun to retry) |

These files are also used to filter keys on subsequent runs so you don't re-attempt the same keys.

## File Structure

```
config.yaml          # Steam API key and settings
.state/
  humble.cookies     # Humble Bundle session
  steam.cookies      # Steam session
```

Delete `.state/` to force fresh logins. Delete `config.yaml` to reset settings.

## Dependencies

| Package | Purpose |
|---------|---------|
| `cryptography` | RSA encryption for Steam login |
| `fuzzywuzzy` | Fuzzy string matching for ownership detection |
| `python-Levenshtein` | Fast string matching backend for fuzzywuzzy |
| `requests` | HTTP client |
| `requests-futures` | Concurrent order fetching |
| `cloudscraper` | Bypasses Humble's CloudFlare protection |
| `rich` | Terminal UI (panels, spinners, tables, colors) |
| `qrcode` | QR code generation for Steam mobile app login |
