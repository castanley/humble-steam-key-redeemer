"""Steam login via Valve's IAuthenticationService API."""

from __future__ import annotations

import base64
import secrets
import sys
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from rich.prompt import Prompt

from src import STEAM_COOKIE_FILE
from src.utils import (
    STEAM_KEYS_PAGE,
    console,
    export_cookies,
    print_error,
    print_info,
    print_rule,
    print_success,
    print_warning,
    try_recover_cookies,
    verify_logins_session,
)

STEAM_API = "https://api.steampowered.com"
STEAM_LOGIN_URL = "https://login.steampowered.com"
STEAM_USERDATA_API = "https://store.steampowered.com/dynamicstore/userdata/"
STEAM_REDEEM_API = "https://store.steampowered.com/account/ajaxregisterkey/"


def steam_login() -> requests.Session:
    """Sign into Steam web using the IAuthenticationService API. Returns an authenticated session."""
    # Attempt to use saved session
    r = requests.Session()
    if try_recover_cookies(STEAM_COOKIE_FILE, r) and verify_logins_session(r)[1]:
        return r

    # Saved state doesn't work — interactive login
    print_rule("Steam Login")

    session = requests.Session()
    s_username = Prompt.ask("[bold cyan]Username[/bold cyan]")
    s_password = Prompt.ask(
        f"[bold cyan]Password[/bold cyan] [dim]({s_username})[/dim]", password=True
    )

    while True:
        # Step 1: Get RSA public key
        rsa_resp = session.get(
            f"{STEAM_API}/IAuthenticationService/GetPasswordRSAPublicKey/v1",
            params={"account_name": s_username},
            timeout=15,
        ).json()["response"]

        mod = int(rsa_resp["publickey_mod"], 16)
        exp = int(rsa_resp["publickey_exp"], 16)
        rsa_timestamp = rsa_resp["timestamp"]

        public_key = RSAPublicNumbers(e=exp, n=mod).public_key()
        encrypted_password = base64.b64encode(
            public_key.encrypt(s_password.encode("utf-8"), PKCS1v15())
        ).decode("ascii")

        # Step 2: Begin auth session
        begin_resp = session.post(
            f"{STEAM_API}/IAuthenticationService/BeginAuthSessionViaCredentials/v1",
            data={
                "persistence": "1",
                "encrypted_password": encrypted_password,
                "account_name": s_username,
                "encryption_timestamp": rsa_timestamp,
            },
            timeout=15,
        )

        begin_data = begin_resp.json().get("response", {})
        if "client_id" not in begin_data:
            print_error("Login failed — check your username and password.")
            s_password = Prompt.ask(
                f"[bold cyan]Password[/bold cyan] [dim]({s_username})[/dim]",
                password=True,
            )
            continue

        client_id = begin_data["client_id"]
        steam_id = begin_data["steamid"]
        request_id = begin_data["request_id"]

        # Step 3: Handle 2FA / email guard if required
        conf_types = [
            c.get("confirmation_type")
            for c in begin_data.get("allowed_confirmations", [])
        ]

        if 3 in conf_types:
            if 4 in conf_types:
                # Both code and push notification available
                print_info(
                    "Approve the login on your Steam app, "
                    "or enter your 2FA code below."
                )
                twofactor_code = Prompt.ask(
                    "[bold cyan]2FA code[/bold cyan] [dim](Enter to wait for app)[/dim]",
                    default="",
                )
            else:
                twofactor_code = Prompt.ask("[bold cyan]2FA code[/bold cyan]")
            if twofactor_code:
                session.post(
                    f"{STEAM_API}/IAuthenticationService/UpdateAuthSessionWithSteamGuardCode/v1",
                    data={
                        "client_id": client_id,
                        "steamid": steam_id,
                        "code": twofactor_code,
                        "code_type": "3",
                    },
                    timeout=15,
                )
        elif 4 in conf_types:
            print_info("Confirm the login on your Steam mobile app…")
        elif 2 in conf_types:
            email_code = Prompt.ask(
                "[bold cyan]Steam Guard email code[/bold cyan]"
            )
            session.post(
                f"{STEAM_API}/IAuthenticationService/UpdateAuthSessionWithSteamGuardCode/v1",
                data={
                    "client_id": client_id,
                    "steamid": steam_id,
                    "code": email_code,
                    "code_type": "2",
                },
                timeout=15,
            )

        # Step 4: Poll for auth completion
        refresh_token = None
        with console.status(
            "Waiting for Steam authentication…", spinner="dots"
        ):
            for _ in range(30):
                poll_resp = (
                    session.post(
                        f"{STEAM_API}/IAuthenticationService/PollAuthSessionStatus/v1",
                        data={"client_id": client_id, "request_id": request_id},
                        timeout=15,
                    )
                    .json()
                    .get("response", {})
                )

                if "refresh_token" in poll_resp:
                    refresh_token = poll_resp["refresh_token"]
                    break
                time.sleep(2)

        if not refresh_token:
            print_error("Authentication timed out.")
            sys.exit(1)

        # Step 5: Finalize login via JWT to get session cookies
        for init_url in [
            "https://steamcommunity.com",
            "https://store.steampowered.com",
        ]:
            session.get(init_url)
        session_id = session.cookies.get("sessionid", domain="steamcommunity.com")
        if not session_id:
            session_id = secrets.token_hex(12)
        for domain in [
            "store.steampowered.com",
            "help.steampowered.com",
            "steamcommunity.com",
        ]:
            session.cookies.set("sessionid", session_id, domain=domain)

        finalize_resp = session.post(
            f"{STEAM_LOGIN_URL}/jwt/finalizelogin",
            data={
                "nonce": refresh_token,
                "sessionid": session_id,
                "redir": "https://store.steampowered.com/login/home/?goto=",
            },
            timeout=15,
        ).json()

        steam_id_str = finalize_resp.get("steamID", "")

        # Try transfer URLs first
        for transfer in finalize_resp.get("transfer_info", []):
            url = transfer.get("url")
            params = transfer.get("params", {})
            params["steamID"] = steam_id_str
            if url:
                session.post(url, data=params, timeout=15)

        # Check if store got authenticated via transfer URLs
        has_store_login = any(
            c.name == "steamLoginSecure"
            and "store.steampowered" in (c.domain or "")
            for c in session.cookies
        )

        if not has_store_login:
            print_info("Transfer URLs didn't set store cookies, setting manually…")
            for transfer in finalize_resp.get("transfer_info", []):
                url = transfer.get("url", "")
                params = transfer.get("params", {})
                auth_token = params.get("auth", "")
                if not auth_token:
                    continue
                domain = urlparse(url).hostname
                if domain:
                    cookie_value = f"{steam_id_str}%7C%7C{auth_token}"
                    session.cookies.set(
                        "steamLoginSecure", cookie_value, domain=domain, secure=True
                    )
                    print_info(f"Set steamLoginSecure for {domain}")

        # Verify store authentication
        verify = session.get(STEAM_KEYS_PAGE, allow_redirects=False)
        if verify.status_code in (301, 302):
            print_warning(
                f"Store NOT authenticated (redirect {verify.status_code})"
            )
        else:
            print_success(
                f"Store authenticated (status {verify.status_code})"
            )

        export_cookies(STEAM_COOKIE_FILE, session)
        return session
