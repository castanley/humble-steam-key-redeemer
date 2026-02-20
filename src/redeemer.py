"""Steam key redemption logic and rate-limit handling."""

from __future__ import annotations

import json
import time
from typing import Any

from rich import box
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from src.humble_api import redeem_humble_key
from src.ownership import get_owned_apps, match_ownership
from src.steam_auth import STEAM_REDEEM_API, steam_login
from src.utils import (
    console,
    print_info,
    print_rule,
    print_success,
    print_warning,
    prompt_yes_no,
    valid_steam_key,
    write_skipped,
)

# Short labels for error codes (used in the compact status display)
_SHORT_ERRORS: dict[int, str] = {
    9: "already owned",
    13: "region locked",
    14: "invalid key",
    15: "used elsewhere",
    24: "requires base game",
    36: "requires PS3",
    50: "wallet code",
    53: "rate limited",
}


def redeem_steam_key(session, key: str) -> int:
    """Redeem a single Steam key. Returns 0 on success or an error code.

    Does NOT print anything — the caller handles all display.
    """
    if key == "":
        return 0
    session_id = session.cookies.get_dict()["sessionid"]
    r = session.post(STEAM_REDEEM_API, data={"product_key": key, "sessionid": session_id})
    try:
        blob = r.json()
    except json.JSONDecodeError:
        return 53  # Treat as rate limit so the caller retries

    if blob["success"] == 1:
        return 0

    error_code = blob.get("purchase_result_details")
    if error_code is None:
        error_code = blob.get("purchase_receipt_info")
        if error_code is not None:
            error_code = error_code.get("result_detail")
    return error_code or 53


class KeyFileManager:
    """Context manager for CSV output files (redeemed, already_owned, errored)."""

    def __init__(self) -> None:
        self._files: dict[str, Any] = {}

    def __enter__(self) -> KeyFileManager:
        return self

    def __exit__(self, *exc: object) -> None:
        for f in self._files.values():
            f.close()
        self._files.clear()

    def write_key(self, code: int, key: dict[str, Any]) -> None:
        """Append a key result to the appropriate CSV file."""
        if code in (15, 9):
            filename = "already_owned.csv"
        elif code != 0:
            filename = "errored.csv"
        else:
            filename = "redeemed.csv"

        if filename not in self._files:
            self._files[filename] = open(filename, "a", encoding="utf-8-sig")

        human_name = key.get("human_name", "").replace(",", ".")
        gamekey = key.get("gamekey", "")
        redeemed_key_val = key.get("redeemed_key_val", "")
        self._files[filename].write(f"{gamekey},{human_name},{redeemed_key_val}\n")
        self._files[filename].flush()


_MAX_LOG_LINES = 20


class RedeemDisplay:
    """Manages the scrolling log + fixed status panel for the Live display."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.redeemed = 0
        self.owned = 0
        self.errors = 0
        self._log: list[str] = []
        self._current = "Starting…"
        self._extra = ""

    @property
    def done(self) -> int:
        return self.redeemed + self.owned + self.errors

    def log(self, line: str) -> None:
        self._log.append(line)
        if len(self._log) > _MAX_LOG_LINES:
            self._log = self._log[-_MAX_LOG_LINES:]

    def set_current(self, name: str, extra: str = "") -> None:
        self._current = name
        self._extra = extra

    def build(self) -> Text:
        """Build the full renderable: scrolling log + status panel."""
        parts: list[str] = []

        # Log section
        if self._log:
            parts.append("\n".join(self._log))
            parts.append("")

        # Status panel content
        name_esc = escape(self._current)
        status_lines = [f"[bold]Game:[/bold] {name_esc}"]
        if self._extra:
            status_lines.append(f"  {self._extra}")
        status_lines.append(
            f"[green]{self.redeemed} redeemed[/green]  |  "
            f"[yellow]{self.owned} owned[/yellow]  |  "
            f"[red]{self.errors} errors[/red]  |  "
            f"[dim]{self.done}/{self.total}[/dim]"
        )

        status_panel = Panel(
            "\n".join(status_lines),
            border_style="dim",
            box=box.ROUNDED,
            padding=(0, 1),
        )

        # Combine log text + panel
        group = Text.from_markup("\n".join(parts)) if parts else Text()
        from rich.console import Group as RichGroup
        return RichGroup(group, status_panel) if parts else status_panel


def redeem_steam_keys(humble_session, humble_keys: list[dict]) -> None:
    """Full auto-redeem pipeline: Steam login, ownership check, redeem with rate-limit handling."""
    session = steam_login()

    print_success("Successfully signed in on Steam.")
    print_info(
        "Getting your owned content to avoid attempting to register keys already owned…"
    )

    owned_app_details = get_owned_apps(session)
    have_ownership = bool(owned_app_details)

    if have_ownership:
        with console.status("Checking ownership…", spinner="dots"):
            noted_keys = [
                key for key in humble_keys if key["steam_app_id"] not in owned_app_details
            ]
            skipped_games: dict[str, dict] = {}
            unowned_games: list[dict] = []

            for game in noted_keys:
                best_match = match_ownership(owned_app_details, game)
                if best_match[1] is not None and best_match[1] in owned_app_details:
                    skipped_games[game["human_name"].strip()] = game
                else:
                    unowned_games.append(game)

        print_success(
            f"Filtered out already-owned keys — {len(unowned_games)} remaining."
        )

        if skipped_games:
            write_skipped(skipped_games)
    else:
        # No ownership data — warn and let user decide
        revealed = [k for k in humble_keys if "redeemed_key_val" in k]
        unrevealed_count = len(humble_keys) - len(revealed)

        if unrevealed_count:
            print_warning(
                f"No API key — can't check which games you already own."
            )
            print_warning(
                f"If an unrevealed key gets revealed for a game you already own, "
                f"you lose the ability to gift it."
            )
            console.print()
            redeem_all = prompt_yes_no(
                f"Reveal and redeem all {len(humble_keys)} keys "
                f"({unrevealed_count} unrevealed)?",
                default=False,
            )
            if redeem_all:
                unowned_games = list(humble_keys)
                print_info(f"All {len(unowned_games)} keys will be attempted.")
            else:
                unowned_games = revealed
                print_info(
                    f"{len(unowned_games)} already-revealed keys will be attempted, "
                    f"{unrevealed_count} unrevealed keys preserved."
                )
        else:
            unowned_games = revealed
            print_info(f"{len(unowned_games)} revealed keys will be attempted.")

    seen: set = set()
    total = len(unowned_games)
    display = RedeemDisplay(total)

    print_rule("Key Redemption")

    with Live(display.build(), console=console, refresh_per_second=4) as live:
        with KeyFileManager() as kfm:
            for key in unowned_games:
                name = key["human_name"]
                display.set_current(name)
                live.update(display.build())

                # Duplicate check
                if name in seen or (
                    key["steam_app_id"] is not None
                    and key["steam_app_id"] in seen
                ):
                    kfm.write_key(9, key)
                    display.owned += 1
                    display.log(f"[yellow]⊘[/yellow] {escape(name)} [dim]— duplicate[/dim]")
                    live.update(display.build())
                    continue
                else:
                    if key["steam_app_id"] is not None:
                        seen.add(key["steam_app_id"])
                    seen.add(name)

                # Reveal unrevealed keys on Humble
                if "redeemed_key_val" not in key:
                    display.set_current(name, "[dim]Revealing key on Humble…[/dim]")
                    live.update(display.build())
                    redeemed_key = redeem_humble_key(humble_session, key)
                    key["redeemed_key_val"] = redeemed_key

                # Invalid key format
                if not valid_steam_key(key["redeemed_key_val"]):
                    kfm.write_key(1, key)
                    display.errors += 1
                    display.log(f"[red]✗[/red] {escape(name)} [dim]— invalid key format[/dim]")
                    live.update(display.build())
                    continue

                # Redeem on Steam
                display.set_current(name, "[dim]Redeeming on Steam…[/dim]")
                live.update(display.build())
                code = redeem_steam_key(session, key["redeemed_key_val"])

                # Rate limit — wait 1 hour then retry
                seconds = 0
                wait_time = 3600
                while code == 53:
                    time.sleep(1)
                    seconds += 1
                    remaining = wait_time - (seconds % wait_time)
                    rm, rs = divmod(remaining, 60)
                    m, s = divmod(seconds, 60)
                    display.set_current(
                        name,
                        f"[bold yellow]Rate limited[/bold yellow] — retrying in {rm}m {rs}s [dim](waited {m}m {s}s)[/dim]",
                    )
                    live.update(display.build())
                    if seconds % wait_time == 0:
                        display.set_current(name, "[dim]Retrying…[/dim]")
                        live.update(display.build())
                        code = redeem_steam_key(session, key["redeemed_key_val"])

                # Tally result
                if code == 0:
                    display.redeemed += 1
                    display.log(f"[green]✓[/green] {escape(name)}")
                elif code in (9, 15):
                    display.owned += 1
                    display.log(f"[yellow]⊘[/yellow] {escape(name)} [dim]— already owned[/dim]")
                else:
                    display.errors += 1
                    short = _SHORT_ERRORS.get(code, f"error {code}")
                    display.log(f"[red]✗[/red] {escape(name)} [dim]— {short}[/dim]")

                kfm.write_key(code, key)
                display.set_current(name)
                live.update(display.build())

    # Final summary
    console.print()
    console.print(
        f"[bold]Done![/bold]  "
        f"[green]✓ {display.redeemed} redeemed[/green]  ·  "
        f"[yellow]⊘ {display.owned} owned[/yellow]  ·  "
        f"[red]✗ {display.errors} errors[/red]"
    )
