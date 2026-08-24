"""Steam ownership detection and fuzzy string matching."""

from __future__ import annotations

import os
from typing import Any

import requests
from fuzzywuzzy import fuzz

from rich.prompt import Prompt

from src import load_config, save_config
from src.steam_auth import STEAM_USERDATA_API
from src.utils import console, print_error, print_info, print_success, print_warning


def load_steam_api_key() -> str | None:
    """Load Steam Web API key from config.yaml or STEAM_API_KEY env var."""
    key = os.environ.get("STEAM_API_KEY", "").strip()
    if key:
        return key
    config = load_config()
    key = str(config.get("steam_api_key", "")).strip()
    return key or None


def fetch_app_list(api_key: str) -> list[dict[str, Any]]:
    """Fetch full Steam app list using IStoreService/GetAppList (requires API key)."""
    all_apps: list[dict[str, Any]] = []
    last_appid = 0
    while True:
        params: dict[str, str] = {
            "key": api_key,
            "include_games": "true",
            "include_dlc": "true",
            "include_software": "true",
            "max_results": "50000",
        }
        if last_appid:
            params["last_appid"] = str(last_appid)
        resp = requests.get(
            "https://api.steampowered.com/IStoreService/GetAppList/v1/",
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            raise Exception(f"IStoreService/GetAppList returned {resp.status_code}")
        data = resp.json().get("response", {})
        apps = data.get("apps", [])
        all_apps.extend(apps)
        if not data.get("have_more_results", False):
            break
        last_appid = data.get("last_appid", 0)
        if not last_appid:
            break
    return all_apps


def get_owned_apps(steam_session, *, auto: bool = False) -> dict[int, str]:
    """Get the user's owned content from Steam. Returns {appid: name} dict."""
    owned_content = steam_session.get(STEAM_USERDATA_API).json()
    owned_app_ids = set(owned_content["rgOwnedPackages"] + owned_content["rgOwnedApps"])

    api_key = load_steam_api_key()

    if api_key:
        try:
            with console.status("Fetching Steam app list…", spinner="dots"):
                app_list = fetch_app_list(api_key)
            print_success(f"Fetched {len(app_list)} apps")
        except Exception as e:
            print_error(f"IStoreService/GetAppList error: {e}")
            print_warning("Could not fetch Steam app list, skipping ownership detection")
            return {}
    else:
        if auto:
            print_info("No Steam Web API key found — skipping ownership detection.")
            return {}

        print_warning("No Steam Web API key found.")
        console.print(
            "[dim]A Steam Web API key lets us check which games you already own\n"
            "so we don't waste attempts on duplicates.[/dim]"
        )
        console.print(
            "[dim]Get one at:[/dim] [cyan]https://steamcommunity.com/dev/apikey[/cyan]"
        )
        console.print()

        api_key = Prompt.ask(
            "[bold cyan]API key[/bold cyan] [dim](Enter to skip)[/dim]",
            default="",
        ).strip()

        if not api_key:
            print_info("Skipping ownership detection — all keys will be attempted.")
            return {}

        # Save for future runs
        config = load_config()
        config["steam_api_key"] = api_key
        save_config(config)
        print_info("Saved to [cyan]config.yaml[/cyan] for next time.")
        try:
            with console.status("Fetching Steam app list…", spinner="dots"):
                app_list = fetch_app_list(api_key)
            print_success(f"Fetched {len(app_list)} apps")
        except Exception as e:
            print_error(f"IStoreService/GetAppList error: {e}")
            print_warning("Could not fetch Steam app list, skipping ownership detection")
            return {}

    return {
        app["appid"]: app["name"]
        for app in app_list
        if app["appid"] in owned_app_ids
    }


# Historical defaults. token_set_ratio is looser than token_sort_ratio, so the
# filter pass and the final acceptance check have always used different cutoffs.
DEFAULT_FILTER_THRESHOLD = 70
DEFAULT_MATCH_THRESHOLD = 35


def match_ownership(
    owned_app_details: dict[int, str],
    game: dict[str, Any],
    filter_threshold: int = DEFAULT_FILTER_THRESHOLD,
    match_threshold: int = DEFAULT_MATCH_THRESHOLD,
) -> tuple[int, int | None]:
    """Fuzzy-match *game* against owned apps. Returns (score, appid) or (0, None).

    *filter_threshold* gates the initial token_set_ratio pass; *match_threshold*
    is the minimum token_sort_ratio score required to accept the best remaining
    candidate. The defaults can let loosely-related titles match (e.g. 'Spirit'
    matching 'The Spirit Lift', 'Book of Demons' matching 'Book of Hours').
    Passing the same, higher value for both (e.g. 85) makes matching stricter
    at the cost of missing some legitimate DLC/edition variants.
    """
    matches = [
        (fuzz.token_set_ratio(appname, game["human_name"]), appid)
        for appid, appname in owned_app_details.items()
    ]
    refined_matches = [
        (fuzz.token_sort_ratio(owned_app_details[appid], game["human_name"]), appid)
        for score, appid in matches
        if score > filter_threshold
    ]
    if refined_matches:
        best_match = max(refined_matches, key=lambda item: item[0])
    else:
        best_match = (0, None)
    if best_match[0] < match_threshold:
        best_match = (0, None)
    return best_match
