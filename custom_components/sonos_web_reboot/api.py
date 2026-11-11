"""Client for the Sonos Web player's same-origin control proxy."""

import json
import re
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp

from .const import BASE_URL, ORIGIN, REQUEST_TIMEOUT

_PLAYER_ID = re.compile(r"RINCON_[0-9A-F]{17}")
_COOKIE_PAIR = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+=[\x20-\x7e]*")


class SonosError(Exception):
    """A Sonos error whose message never includes a response body or cookie."""


class SessionExpired(SonosError):
    """The web session must be replaced."""


class PermissionDenied(SonosError):
    """The session lacks permission to perform the request."""


class DiscoveryFailed(SonosError):
    """Household or player discovery could not be completed."""


class RestartRejected(SonosError):
    """Sonos rejected the request."""


class RestartUnconfirmed(SonosError):
    """The request may have been delivered without a usable response."""


@dataclass(frozen=True, slots=True)
class Player:
    """A player advertised by the authenticated household."""

    id: str
    name: str
    model: str | None


def normalize_cookie(value: str) -> str:
    """Accept a single Cookie header, including chunked session cookies."""
    if len(value) > 16384 or any(not 32 <= ord(char) < 127 for char in value):
        raise ValueError("Invalid Cookie header")
    value = value.strip()
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    if not all(_COOKIE_PAIR.fullmatch(pair.strip()) for pair in value.split(";")):
        raise ValueError("Invalid Cookie header")
    return value


class SonosWebClient:
    """Use an existing owner session, restricted to the Sonos Web origin."""

    def __init__(self, session: aiohttp.ClientSession, cookie: str) -> None:
        self._session = session
        self._cookie = cookie

    async def households(self) -> dict[str, str]:
        """Get the household IDs and names available to this session."""
        data = await self._request("GET", "/households")
        if not isinstance(items := data.get("households"), list):
            raise DiscoveryFailed("Unexpected household list")

        return {
            household_id: name
            if isinstance(name := item.get("name"), str) and name
            else f"Home · {household_id[-8:]}"
            for item in items
            if isinstance(item, dict)
            and isinstance(household_id := item.get("id"), str)
            and household_id not in {"", ".", ".."}
        }

    async def players(self, household_id: str) -> dict[str, Player]:
        """List individually addressable players, regardless of playback grouping."""
        data = await self._request("GET", f"/households/{quote(household_id, safe='')}/groups")
        if not isinstance(items := data.get("players"), list):
            raise DiscoveryFailed("Unexpected player list")

        players: dict[str, Player] = {}
        for item in items:
            if not isinstance(item, dict) or item.get("isUnregistered") is True:
                continue
            player_id = item.get("id")
            if not isinstance(player_id, str) or not _PLAYER_ID.fullmatch(player_id):
                continue
            name = item.get("name")
            model = None
            if isinstance(devices := item.get("devices"), list):
                for device in devices:
                    if isinstance(device, dict) and player_id in (
                        device.get("id"),
                        device.get("deviceId"),
                    ):
                        model = device.get("modelDisplayName")
                        break
            players[player_id] = Player(
                player_id,
                name if isinstance(name, str) and name else player_id,
                model if isinstance(model, str) and model else None,
            )
        return players

    async def restart(self, player_id: str) -> None:
        """Send one reboot request for one physical player ID."""
        if not _PLAYER_ID.fullmatch(player_id):
            raise RestartRejected("Invalid player ID")
        await self._request("POST", f"/players/{player_id}/management/reboot")

    async def _request(self, method: str, path: str) -> dict:
        restart = method == "POST"
        headers = {"Cookie": self._cookie, "Accept": "application/json"}
        if restart:
            headers["Origin"] = ORIGIN
        try:
            async with self._session.request(
                method,
                BASE_URL + path,
                headers=headers,
                json={} if restart else None,
                allow_redirects=False,
                raise_for_status=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                status = response.status
                if status == 403 or (
                    status == 401
                    and "insufficient_scope" in response.headers.get("WWW-Authenticate", "")
                ):
                    raise PermissionDenied("Sonos denied permission")
                if status == 401 or 300 <= status < 400:
                    raise SessionExpired("Sonos Web sign-in is required")
                if not 200 <= status < 300:
                    if restart and status >= 500:
                        raise RestartUnconfirmed(f"Sonos returned HTTP {status}")
                    error = RestartRejected if restart else DiscoveryFailed
                    raise error(f"Sonos returned HTTP {status}")

                body = await response.read()
                if restart and not body.strip():
                    return {}
                data = json.loads(body)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            error = RestartUnconfirmed if restart else DiscoveryFailed
            raise error(f"Sonos returned no usable response ({type(err).__name__})") from None

        if not isinstance(data, dict):
            error = RestartUnconfirmed if restart else DiscoveryFailed
            raise error("Unexpected Sonos response format")
        global_error = data.get("globalError")
        error_code = data.get("errorCode")
        if isinstance(global_error, dict):
            error_code = error_code or global_error.get("errorCode")
        if error_code == "ERROR_NO_PERMISSION":
            raise PermissionDenied("Sonos denied permission")
        if error_code or global_error or data.get("error") or data.get("success") is False:
            error = RestartRejected if restart else DiscoveryFailed
            raise error("Sonos reported an error")
        return data
