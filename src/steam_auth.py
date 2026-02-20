"""Steam login via Valve's IAuthenticationService API."""

from __future__ import annotations

import base64
import io
import secrets
import sys
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from rich.prompt import Prompt
from rich.text import Text

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
    prompt_menu,
    try_recover_cookies,
    verify_logins_session,
)

STEAM_API = "https://api.steampowered.com"
STEAM_LOGIN_URL = "https://login.steampowered.com"
STEAM_USERDATA_API = "https://store.steampowered.com/dynamicstore/userdata/"
STEAM_REDEEM_API = "https://store.steampowered.com/account/ajaxregisterkey/"


def _render_qr(url: str) -> str | None:
    """Render *url* as an ASCII QR code string centered for the terminal. Returns None if qrcode isn't installed."""
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()


def _finalize_session(session: requests.Session, refresh_token: str) -> requests.Session:
    """Exchange a refresh token for full session cookies on Steam store/community."""
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


def _try_qr_login(session: requests.Session) -> requests.Session | None:
    """Attempt QR-code login via BeginAuthSessionViaQR. Returns session on success, None on skip/failure."""
    begin_resp = session.post(
        f"{STEAM_API}/IAuthenticationService/BeginAuthSessionViaQR/v1",
        data={"device_friendly_name": "eNkrypt Steam Redeemer"},
        timeout=15,
    )
    begin_data = begin_resp.json().get("response", {})
    challenge_url = begin_data.get("challenge_url")
    client_id = begin_data.get("client_id")
    request_id = begin_data.get("request_id")

    if not challenge_url or not client_id:
        return None

    qr_text = _render_qr(challenge_url)
    if not qr_text:
        return None

    # Center and display the QR code
    console.print()
    for line in qr_text.strip().splitlines():
        console.print(Text(line), justify="center")
    console.print()
    print_info("Scan with your [bold]Steam mobile app[/bold] to sign in.")
    print_info("Press [bold]Enter[/bold] to type credentials instead.")
    console.print()

    # Poll for approval while watching for Enter key
    import selectors
    import threading

    enter_pressed = threading.Event()

    def _wait_for_enter():
        try:
            input()
        except EOFError:
            pass
        enter_pressed.set()

    input_thread = threading.Thread(target=_wait_for_enter, daemon=True)
    input_thread.start()

    refresh_token = None
    with console.status("Waiting for QR scan…", spinner="dots"):
        for _ in range(90):  # ~3 minutes
            if enter_pressed.is_set():
                return None  # User wants manual login

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
        return None

    print_success("QR login approved!")
    return _finalize_session(session, refresh_token)


def _credential_login(session: requests.Session) -> requests.Session:
    """Interactive username/password login with 2FA support."""
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

        return _finalize_session(session, refresh_token)


def steam_login() -> requests.Session:
    """Sign into Steam web. Tries QR code first, falls back to credentials."""
    # Attempt to use saved session
    r = requests.Session()
    if try_recover_cookies(STEAM_COOKIE_FILE, r) and verify_logins_session(r)[1]:
        return r

    # Saved state doesn't work — interactive login
    print_rule("Steam Login")

    session = requests.Session()

    # Try QR login first
    result = _try_qr_login(session)
    if result is not None:
        return result

    # QR skipped or failed — fall back to credentials
    print_rule("Steam Login")
    return _credential_login(session)
