"""Humble Choice game selector."""

from __future__ import annotations

import time
import webbrowser
from typing import Any

from rich import box
from rich.markup import escape
from rich.prompt import Prompt
from rich.table import Table

from src.humble_api import (
    HUMBLE_CHOOSE_CONTENT,
    HUMBLE_HEADERS,
    HUMBLE_ORDER_DETAILS_API,
    HUMBLE_SUB_PAGE,
    get_choices,
)
from src.redeemer import redeem_steam_keys
from src.utils import (
    cls,
    console,
    find_dict_keys,
    print_error,
    print_info,
    print_rule,
    print_success,
    print_warning,
    prompt_yes_no,
)


def choose_games(
    humble_session,
    choice_month_name: str,
    identifier: str,
    chosen: list[dict[str, Any]],
) -> None:
    """Submit chosen games for a Humble Choice month."""
    for choice in chosen:
        display_name = choice["display_item_machine_name"]
        if "tpkds" not in choice:
            url = f"{HUMBLE_SUB_PAGE}{choice_month_name}/{display_name}"
            console.print(f"[cyan]Open in browser:[/cyan] {url}")
            webbrowser.open(url)
        else:
            payload = {
                "gamekey": choice["tpkds"][0]["gamekey"],
                "parent_identifier": identifier,
                "chosen_identifiers[]": display_name,
                "is_multikey_and_from_choice_modal": "false",
            }
            res = humble_session.post(
                HUMBLE_CHOOSE_CONTENT, data=payload, headers=HUMBLE_HEADERS
            ).json()
            if "success" not in res or not res["success"]:
                print_error(f"Error choosing {escape(choice['title'])}")
                console.print(res)
            else:
                print_success(f"Chose game {escape(choice['title'])}")


def humble_chooser_mode(
    humble_session, order_details: list[dict[str, Any]]
) -> None:
    """Interactive Humble Choice game selection UI."""
    try_redeem_keys: list[str] = []
    months = get_choices(humble_session, order_details)
    first = True
    redeem_keys = False

    for month in months:
        redeem_all = None
        if first:
            redeem_keys = prompt_yes_no(
                "Auto-redeem keys after choosing? (requires Steam login)"
            )
            first = False

        ready = False
        while not ready:
            cls()
            remaining = month["choices_remaining"]
            choices = month["available_choices"]

            month_name = escape(month["product"]["human_name"])
            print_rule(
                f"{month_name}  ·  [cyan]{remaining}[/cyan] choices remaining"
            )

            # Build game listing table
            table = Table(
                show_header=True,
                header_style="bold cyan",
                border_style="bright_blue",
                box=box.ROUNDED,
                padding=(0, 1),
            )
            table.add_column("#", style="cyan", justify="right", width=4)
            table.add_column("Title", style="bold")
            table.add_column("Rating", style="green")
            table.add_column("Notes", style="yellow")

            for idx, choice in enumerate(choices):
                title = escape(choice["title"])
                rating_text = ""
                if (
                    "review_text" in choice.get("user_rating", {})
                    and "steam_percent|decimal" in choice.get("user_rating", {})
                ):
                    rating = choice["user_rating"]["review_text"].replace("_", " ")
                    percentage = (
                        str(int(choice["user_rating"]["steam_percent|decimal"] * 100))
                        + "%"
                    )
                    rating_text = f"{rating} ({percentage})"
                note = ""
                if "tpkds" not in choice:
                    note = "Must redeem via Humble"
                table.add_row(str(idx + 1), title, rating_text, note)

            console.print(table)

            if redeem_all is None and remaining == len(choices):
                redeem_all = prompt_yes_no("Redeem all?")
            else:
                redeem_all = False

            if redeem_all:
                user_input = [str(i + 1) for i in range(len(choices))]
            else:
                if redeem_keys:
                    auto_note = " [dim](webpage keys auto-redeemed after)[/dim]"
                else:
                    auto_note = ""

                console.print()
                console.print(
                    f"Indexes separated by commas "
                    f"(e.g. [bold]1[/bold] or [bold]1,2,3[/bold])"
                )
                console.print(
                    f"Type [bold]link[/bold] to open in browser{auto_note}"
                )
                console.print(
                    "Press [bold]Enter[/bold] to skip this month"
                )
                console.print()

                raw = Prompt.ask("[bold cyan]Selection[/bold cyan]", default="")
                user_input = [
                    uinput.strip()
                    for uinput in raw.split(",")
                    if uinput.strip()
                ]

            if len(user_input) == 0:
                ready = True
            elif user_input[0].lower() == "link":
                url = HUMBLE_SUB_PAGE + month["product"]["choice_url"]
                console.print(f"[cyan]Open in browser:[/cyan] {url}")
                webbrowser.open(url)
                Prompt.ask(
                    "[dim]Press Enter once you've made your picks in the browser[/dim]",
                    default="",
                )
                if redeem_keys:
                    try_redeem_keys.append(month["gamekey"])
                ready = True
            else:
                invalid_option = lambda option: (
                    not option.isnumeric()
                    or option == "0"
                    or int(option) > len(choices)
                )
                invalid = [opt for opt in user_input if invalid_option(opt)]

                if invalid:
                    print_error("Invalid options: " + ", ".join(invalid))
                    time.sleep(2)
                else:
                    user_input_set = set(int(opt) for opt in user_input)
                    chosen = [
                        choice
                        for idx, choice in enumerate(choices)
                        if idx + 1 in user_input_set
                    ]

                    if len(chosen) > remaining:
                        print_warning(
                            f"Too many — only {remaining} choices left"
                        )
                        time.sleep(2)
                    else:
                        console.print()
                        console.print("[bold]Selected:[/bold]")
                        for choice in chosen:
                            console.print(
                                f"  [green]{escape(choice['title'])}[/green]"
                            )
                        console.print()
                        confirmed = prompt_yes_no("Confirm selection?")
                        if confirmed:
                            choice_month_name = month["product"]["choice_url"]
                            identifier = month["parent_identifier"]
                            choose_games(
                                humble_session, choice_month_name, identifier, chosen
                            )
                            if redeem_keys:
                                try_redeem_keys.append(month["gamekey"])
                            ready = True

    if first:
        print_info("No Humble Choices need choosing — you're all up-to-date!")
    else:
        print_info("No more unchosen Humble Choices")
        if redeem_keys and try_redeem_keys:
            print_success("Redeeming keys now!")
            updated_monthlies = [
                humble_session.get(
                    f"{HUMBLE_ORDER_DETAILS_API}{order}?all_tpkds=true"
                ).json()
                for order in try_redeem_keys
            ]
            chosen_keys = list(
                find_dict_keys(updated_monthlies, "steam_app_id", True)
            )
            redeem_steam_keys(humble_session, chosen_keys)
