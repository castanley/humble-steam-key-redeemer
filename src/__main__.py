"""Entry point for eNkrypt's Steam Redeemer (python -m src)."""

from __future__ import annotations

import argparse
import sys
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

    order_details: list[dict] = []
    with console.status(
        f"Fetching [bold]{len(orders)}[/bold] order details…", spinner="dots"
    ):
        with FuturesSession(session=humble_session, max_workers=30) as retriever:
            order_futures = [
                retriever.get(
                    f"{HUMBLE_ORDER_DETAILS_API}{order['gamekey']}?all_tpkds=true"
                )
                for order in orders
            ]
            for future in as_completed(order_futures):
                resp = future.result()
                order_details.append(resp.json())

    print_success(f"Fetched {len(order_details)} orders from Humble.")

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
            with open(filter_file, "r", encoding="utf-8-sig") as f:
                rows = [line.strip().split(",") for line in f if line.strip()]
            seen_steam_keys = {row[2] for row in rows if len(row) >= 3 and row[2]}
            steam_keys = [
                key for key in steam_keys
                if key.get("redeemed_key_val", "") not in seen_steam_keys
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
