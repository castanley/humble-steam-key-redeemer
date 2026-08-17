"""Entry point for eNkrypt's Steam Redeemer (python -m src)."""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import as_completed

import cloudscraper
from requests_futures.sessions import FuturesSession

from src.chooser import humble_chooser_mode
from src.export import export_mode
from src.humble_api import HUMBLE_ORDER_DETAILS_API, HUMBLE_ORDERS_API
from src.redeemer import redeem_steam_keys
from src.utils import (
    console,
    find_dict_keys,
    print_info,
    print_rule,
    print_success,
    print_warning,
    prompt_menu,
)

_MODES = ["Auto-Redeem", "Export keys", "Humble Choice chooser"]


def prompt_mode() -> str:
    """Prompt the user to select an operating mode."""
    print_rule("Select Mode")
    idx = prompt_menu(_MODES)
    return str(idx + 1)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="steam-redeemer",
        description="Bulk-redeem Humble Bundle Steam keys.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Non-interactive mode for cron/scheduled runs. "
        "Requires valid saved sessions in .state/.",
    )
    parser.add_argument(
        "--reveal-all",
        action="store_true",
        help="With --auto: reveal and redeem unrevealed keys even without "
        "ownership data. Default is to skip unrevealed keys to preserve gift links.",
    )
    return parser.parse_args(argv)


def _fetch_order_details(
    humble_session,
    orders: list[dict],
    *,
    max_workers: int = 15,
    retries: int = 3,
) -> tuple[list[dict], list[str]]:
    """Fetch every order's details, retrying transient failures.

    A single dropped TLS connection (e.g. ``[SSL: UNEXPECTED_EOF_WHILE_READING]``)
    among the concurrent requests used to crash the whole run (issue #7). Now
    failed orders are collected and retried sequentially with backoff, and any
    that still fail are returned to the caller rather than raising.
    """

    def url(gamekey: str) -> str:
        return f"{HUMBLE_ORDER_DETAILS_API}{gamekey}?all_tpkds=true"

    order_details: list[dict] = []

    # First pass: concurrent fetch.
    with FuturesSession(session=humble_session, max_workers=max_workers) as retriever:
        futures = {
            retriever.get(url(order["gamekey"])): order["gamekey"] for order in orders
        }
        pending: list[str] = []
        for future in as_completed(futures):
            gamekey = futures[future]
            try:
                order_details.append(future.result().json())
            except Exception:
                pending.append(gamekey)

    # Sequential retries with backoff for transient TLS / Cloudflare hiccups.
    for attempt in range(retries):
        if not pending:
            break
        time.sleep(2 * (attempt + 1))
        still_failing: list[str] = []
        for gamekey in pending:
            try:
                order_details.append(humble_session.get(url(gamekey)).json())
            except Exception:
                still_failing.append(gamekey)
        pending = still_failing

    return order_details, pending


def main(argv: list[str] | None = None) -> None:
    """Main orchestration: Humble login -> fetch orders -> mode selection -> dispatch."""
    from src.humble_api import humble_login

    args = _parse_args(argv)

    # Redirect stderr to error.log
    sys.stderr = open("error.log", "a")

    # Create a consistent session for Humble API use
    humble_session = cloudscraper.CloudScraper()
    humble_login(humble_session, auto=args.auto)
    print_success("Successfully signed in on Humble.")

    orders = humble_session.get(HUMBLE_ORDERS_API).json()

    with console.status(
        f"Fetching [bold]{len(orders)}[/bold] order details…", spinner="dots"
    ):
        order_details, failed = _fetch_order_details(humble_session, orders)

    print_success(f"Fetched {len(order_details)} orders from Humble.")
    if failed:
        print_warning(
            f"Couldn't fetch {len(failed)} of {len(orders)} orders after retries "
            f"(likely a transient Humble/Cloudflare hiccup) — continuing without "
            f"them. Re-run to pick them up."
        )

    if not args.auto:
        desired_mode = prompt_mode()
        if desired_mode == "2":
            export_mode(humble_session, order_details)
            sys.exit()
        if desired_mode == "3":
            humble_chooser_mode(humble_session, order_details)
            sys.exit()

    # Auto-Redeem mode
    steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))

    filters = ["errored.csv", "already_owned.csv", "redeemed.csv"]
    original_length = len(steam_keys)
    for filter_file in filters:
        try:
            with open(filter_file, "r") as f:
                keycols = f.read()
            filtered_keys = [
                keycol for keycol in keycols.replace("\n", ",").split(",")
            ]
            steam_keys = [
                key for key in steam_keys if key["gamekey"] not in filtered_keys
            ]
        except Exception:
            pass
    if len(steam_keys) != original_length:
        print_info(
            f"Filtered {original_length - len(steam_keys)} keys from previous runs"
        )

    revealed = sum(1 for k in steam_keys if "redeemed_key_val" in k)
    unrevealed = len(steam_keys) - revealed

    print_rule("Key Summary")
    console.print(f"[bold]{len(steam_keys)}[/bold] Steam keys total")
    console.print(
        f"[green]{revealed}[/green] revealed  ·  "
        f"[yellow]{unrevealed}[/yellow] unrevealed"
    )
    console.print()

    redeem_steam_keys(
        humble_session, steam_keys, auto=args.auto, reveal_all=args.reveal_all
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n  [dim]Interrupted by user.[/dim]")
        sys.exit(130)
