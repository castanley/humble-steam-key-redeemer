# eNkrypt's Steam Redeemer

If you've had a Humble Bundle subscription running for months (or years), you probably have dozens — maybe hundreds — of unclaimed Steam keys sitting in your library. Redeeming them one by one is painfully tedious: reveal the key, copy it, paste it into Steam, hit next, repeat. This tool does all of that for you in one shot.

Bulk-redeem your Humble Bundle Steam keys automatically. Detects games you already own so you don't waste rate limits, preserves gift links for unrevealed keys, and handles Steam's rate limiting with automatic retries.

## Features

**Auto-Redeem** — Log into Humble + Steam, and the tool redeems all your unowned keys hands-free. Already-owned games are skipped. Unrevealed keys are only revealed if you don't already own the game (preserving gift links). Rate limits are handled automatically with a 1-hour cooldown.

**Export** — Dump your entire Humble key library to a timestamped CSV. Optionally sign into Steam to annotate each key with ownership status. Choose whether to include revealed keys, unrevealed keys, or both.

**Humble Choice Chooser** — Interactive month-by-month selector for picking unredeemed Humble Choice games. Shows ratings, lets you pick by number, and optionally auto-redeems the keys on Steam after choosing.

## How It Works

1. Signs into Humble Bundle (credentials or saved session)
2. Fetches all your order details concurrently (30 workers)
3. You pick a mode
4. For Auto-Redeem:
   - Signs into Steam via IAuthenticationService (supports 2FA, Steam Guard, email codes)
   - Fetches the full Steam app catalog via Web API to check what you own
   - Fuzzy-matches game titles to catch DLC/edition variants
   - Redeems unowned keys, skips owned ones, waits out rate limits
   - Logs results to CSV files (`redeemed.csv`, `already_owned.csv`, `errored.csv`)

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

If no API key is configured, the tool will prompt you to enter one or skip. Without it, only already-revealed keys are redeemed (unrevealed keys are preserved as gift links since ownership can't be verified).

## Usage

```bash
python steam_redeem.py
# or
python -m src
```

The TUI uses arrow-key navigation and single-keypress shortcuts — no need to hit Enter on menus.

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
