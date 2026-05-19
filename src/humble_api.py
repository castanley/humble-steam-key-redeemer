"""Humble Bundle login, API calls, and key fetching."""

from __future__ import annotations

import json
import sys
from typing import Any, Generator

from rich.prompt import Prompt

from src import HUMBLE_COOKIE_FILE
from src.utils import (
    cls,
    console,
    export_cookies,
    find_dict_keys,
    print_error,
    print_rule,
    try_recover_cookies,
    verify_logins_session,
)

# Humble endpoints
HUMBLE_LOGIN_PAGE = "https://www.humblebundle.com/login"
HUMBLE_SUB_PAGE = "https://www.humblebundle.com/subscription/"

HUMBLE_LOGIN_API = "https://www.humblebundle.com/processlogin"
HUMBLE_REDEEM_API = "https://www.humblebundle.com/humbler/redeemkey"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
HUMBLE_ORDER_DETAILS_API = "https://www.humblebundle.com/api/v1/order/"
HUMBLE_SUB_API = (
    "https://www.humblebundle.com/api/v1/subscriptions/"
    "humble_monthly/subscription_products_with_gamekeys/"
)

HUMBLE_PAY_EARLY = "https://www.humblebundle.com/subscription/payearly"
HUMBLE_CHOOSE_CONTENT = "https://www.humblebundle.com/humbler/choosecontent"

# Shared headers for Humble API calls
HUMBLE_HEADERS: dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def humble_login(session, *, auto: bool = False) -> bool:
    """Log into Humble Bundle. Updates *session* in place. Returns True on success."""
    cls()

    # Attempt to use saved session
    if (
        try_recover_cookies(HUMBLE_COOKIE_FILE, session)
        and verify_logins_session(session)[0]
    ):
        HUMBLE_HEADERS["CSRF-Prevention-Token"] = session.cookies["csrf_cookie"]
        return True
    else:
        session.cookies.clear()

    if auto:
        print_error("Humble session expired. Run interactively to re-authenticate.")
        sys.exit(1)

    # Saved session didn't work — interactive login
    print_rule("Humble Bundle Login")

    authorized = False
    while not authorized:
        username = Prompt.ask("[bold cyan]Email[/bold cyan]")
        password = Prompt.ask("[bold cyan]Password[/bold cyan]", password=True)
        session.get(HUMBLE_LOGIN_PAGE)

        payload = {
            "access_token": "",
            "access_token_provider_id": "",
            "goto": "/",
            "qs": "",
            "username": username,
            "password": password,
        }
        HUMBLE_HEADERS["CSRF-Prevention-Token"] = session.cookies["csrf_cookie"]

        r = session.post(HUMBLE_LOGIN_API, data=payload, headers=HUMBLE_HEADERS)
        login_json = r.json()

        if "errors" in login_json and "username" in login_json["errors"]:
            print_error(login_json["errors"]["username"][0])
            console.print()
            continue

        auth_response = None
        while "humble_guard_required" in login_json or "two_factor_required" in login_json:
            if "humble_guard_required" in login_json:
                humble_guard_code = Prompt.ask(
                    "[bold cyan]Humble Guard code[/bold cyan]"
                )
                payload["guard"] = humble_guard_code.upper()
                auth_response = session.post(
                    HUMBLE_LOGIN_API, data=payload, headers=HUMBLE_HEADERS
                )
                login_json = auth_response.json()

                if (
                    "user_terms_opt_in_data" in login_json
                    and login_json["user_terms_opt_in_data"]["needs_to_opt_in"]
                ):
                    print_error(
                        "TOS update required — please sign in to Humble on your browser."
                    )
                    sys.exit()
            elif (
                "two_factor_required" in login_json
                and "errors" in login_json
                and "authy-input" in login_json["errors"]
            ):
                code = Prompt.ask("[bold cyan]2FA code[/bold cyan]")
                payload["code"] = code
                auth_response = session.post(
                    HUMBLE_LOGIN_API, data=payload, headers=HUMBLE_HEADERS
                )
                login_json = auth_response.json()
            elif "errors" in login_json:
                print_error("Unexpected login error detected.")
                console.print_json(data=login_json["errors"])
                sys.exit()

            if auth_response is not None and auth_response.status_code == 200:
                break

        export_cookies(HUMBLE_COOKIE_FILE, session)
        return True


def redeem_humble_key(session, tpk: dict[str, Any]) -> str:
    """Reveal a key on Humble's API for the given *tpk* entry. Returns the key string."""
    payload = {
        "keytype": tpk["machine_name"],
        "key": tpk["gamekey"],
        "keyindex": tpk["keyindex"],
    }
    resp = session.post(HUMBLE_REDEEM_API, data=payload, headers=HUMBLE_HEADERS)

    resp_json = resp.json()
    if resp.status_code != 200 or "error_msg" in resp_json or not resp_json["success"]:
        print_error(f"Error redeeming key on Humble for {tpk['human_name']}")
        if "error_msg" in resp_json:
            print_error(resp_json["error_msg"])
        return ""
    try:
        return resp_json["key"]
    except Exception:
        return resp.text


def get_month_data(humble_session, month: dict) -> dict:
    """Fetch Humble Choice month data from the subscription page."""
    r = humble_session.get(HUMBLE_SUB_PAGE + month["product"]["choice_url"])

    data_indicator = '<script id="webpack-monthly-product-data" type="application/json">'
    json_text = r.text.split(data_indicator)[1].split("</script>")[0].strip()
    return json.loads(json_text)["contentChoiceOptions"]


def get_choices(
    humble_session, order_details: list[dict]
) -> Generator[dict, None, None]:
    """Yield Humble Choice months that still have unchosen games."""
    months = [
        month
        for month in order_details
        if month["product"].get("category") == "subscriptioncontent"
        and "choice_url" in month["product"]
    ]

    months = sorted(months, key=lambda m: m["created"])

    for month in months:
        if month["choices_remaining"] > 0:
            chosen_games = set(find_dict_keys(month["tpkd_dict"], "machine_name"))

            month["choice_data"] = get_month_data(humble_session, month)

            identifier = (
                "initial"
                if "initial" in month["choice_data"]["contentChoiceData"]
                else "initial-classic"
            )

            if identifier not in month["choice_data"]["contentChoiceData"]:
                for key in month["choice_data"]["contentChoiceData"]:
                    if "content_choices" in month["choice_data"]["contentChoiceData"][key]:
                        identifier = key

            choice_options = month["choice_data"]["contentChoiceData"][identifier][
                "content_choices"
            ]

            month["available_choices"] = [
                game[1]
                for game in choice_options.items()
                if set(find_dict_keys(game[1], "machine_name")).isdisjoint(chosen_games)
            ]

            month["parent_identifier"] = identifier
            yield month
