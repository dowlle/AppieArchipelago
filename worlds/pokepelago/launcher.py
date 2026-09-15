"""Archipelago Launcher integration for Pokepelago.

The WebHost slot table links to ``archipelago://name:None@host:port?game=Pokepelago``.
The OS hands that link to the Archipelago Launcher. This module registers two Pokepelago
client components so the Launcher shows its normal "Connect to Multiworld" chooser for
Pokepelago links:

* **Pokepelago Web Client** - opens the web client with the slot/server prefilled, so it
  connects on load.
* **Pokepelago Desktop Client** - hands the connection to the desktop app through a
  ``pokepelago://connect`` deep link (the Electron wrapper registers that protocol).

The stock Text Client stays in the chooser as the standard fallback, and is also opened
alongside the chosen client when a slot link is used. Nothing is persisted, so the
chooser appears on every slot link.

Desktop protocol contract (implemented in the Electron wrapper):

    pokepelago://connect?host=<host>&port=<port>&name=<slot>&password=<password>

``password`` is omitted when the slot has none. The app should prefill its connection
form from these parameters and connect.
"""

from __future__ import annotations

import os
import subprocess
import urllib.parse
import webbrowser

from Utils import is_macos, is_windows, messagebox
from worlds.LauncherComponents import Component, Type, components, launch_textclient

GAME_NAME = "Pokepelago"
WEB_CLIENT_URL = "https://pokepelago.ap-pie.com/"
DESKTOP_PROTOCOL_URI = "pokepelago://connect"

MODE_WEB = "web"
MODE_DESKTOP = "desktop"


def is_pokepelago_uri(uri: str | None) -> bool:
    """True when ``uri`` is a WebHost link for a Pokepelago slot."""
    if not isinstance(uri, str) or "://" not in uri:
        return False
    url = urllib.parse.urlparse(uri)
    if url.scheme != "archipelago":
        return False
    return urllib.parse.parse_qs(url.query).get("game", [""])[0] == GAME_NAME


def parse_connection(uri: str) -> dict[str, str]:
    """Extract host/port/name/password from an ``archipelago://`` slot link."""
    url = urllib.parse.urlparse(uri)
    password = urllib.parse.unquote(url.password) if url.password else ""
    if password.lower() == "none":
        password = ""
    try:
        port = str(url.port) if url.port else ""
    except ValueError:
        port = ""
    return {
        "host": url.hostname or "",
        "port": port,
        "name": urllib.parse.unquote(url.username) if url.username else "",
        "password": password,
    }


def build_web_url(connection: dict[str, str]) -> str:
    params = {"host": connection.get("host", ""), "port": connection.get("port", ""),
              "name": connection.get("name", "")}
    if connection.get("password"):
        params["password"] = connection["password"]
    return f"{WEB_CLIENT_URL}?{urllib.parse.urlencode(params)}"


def build_desktop_uri(connection: dict[str, str]) -> str:
    params = {"host": connection.get("host", ""), "port": connection.get("port", ""),
              "name": connection.get("name", "")}
    if connection.get("password"):
        params["password"] = connection["password"]
    return f"{DESKTOP_PROTOCOL_URI}?{urllib.parse.urlencode(params)}"


def _open_external(uri: str) -> bool:
    if is_windows:
        startfile = getattr(os, "startfile", None)
        if startfile is not None:
            try:
                startfile(uri)
                return True
            except OSError:
                return False
        return False
    opener = "open" if is_macos else "xdg-open"
    try:
        subprocess.Popen([opener, uri])
    except OSError:
        return False
    return True


def _open_web(connection: dict[str, str] | None) -> None:
    webbrowser.open(build_web_url(connection) if connection else WEB_CLIENT_URL)


def _open_desktop(connection: dict[str, str] | None) -> None:
    uri = build_desktop_uri(connection) if connection else DESKTOP_PROTOCOL_URI
    if not _open_external(uri):
        messagebox(
            "Pokepelago Desktop Client",
            "The Pokepelago desktop client does not appear to be installed or did not register its "
            "pokepelago:// link. Install it from "
            "https://github.com/AfiliaFrostfang/PokepelagoDesktopClient/releases or choose the web client.",
            error=True,
        )


def _open_mode(mode: str, connection: dict[str, str] | None) -> None:
    if mode == MODE_WEB:
        _open_web(connection)
    elif mode == MODE_DESKTOP:
        _open_desktop(connection)


def _web_client(*args: str) -> None:
    _connect(MODE_WEB, *args)


def _desktop_client(*args: str) -> None:
    _connect(MODE_DESKTOP, *args)


def _connect(mode: str, *args: str) -> None:
    uri = args[0] if args else None
    if uri and is_pokepelago_uri(uri):
        _open_mode(mode, parse_connection(uri))
        # Keep the standard Text Client alongside the chosen client.
        launch_textclient(uri)
    else:
        # Manually launched from the Launcher with no room link.
        _open_mode(mode, None)


components.extend([
    Component(
        "Pokepelago Web Client",
        component_type=Type.CLIENT,
        func=_web_client,
        game_name=GAME_NAME,
        supports_uri=True,
        description="Open the Pokepelago web client and connect to this slot automatically.",
    ),
    Component(
        "Pokepelago Desktop Client",
        component_type=Type.CLIENT,
        func=_desktop_client,
        game_name=GAME_NAME,
        supports_uri=True,
        description="Open the Pokepelago desktop app and log in there.",
    ),
])
