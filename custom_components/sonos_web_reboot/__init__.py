"""Add explicit Sonos Web restart buttons to Home Assistant."""

from __future__ import annotations

import time

from aiohttp import ClientSession, DummyCookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import PermissionDenied, RestartRejected, SessionExpired, SonosError, SonosWebClient
from .const import CONF_HOUSEHOLD, CONF_PLAYERS, CONF_SESSION_COOKIE, DOMAIN, RESTART_COOLDOWN

_PLATFORMS = (Platform.BUTTON,)


class RestartPending(SonosError):
    """A reboot request for this speaker is still within the cooldown."""


class Runtime:
    """Share the session and track restart attempts for a config entry."""

    def __init__(self, client: SonosWebClient, player_ids: set[str], entry_id: str) -> None:
        self.client = client
        self.player_ids = player_ids
        self.auth_expired = False
        self.auth_signal = f"{DOMAIN}_reauth_{entry_id}"
        self._next_press: dict[str, float] = {}

    async def restart(self, player_id: str) -> None:
        """Suppress duplicates even when the first outcome is uncertain."""
        if self.auth_expired:
            raise SessionExpired("Sonos Web sign-in is required")
        if player_id not in self.player_ids:
            raise RestartRejected("Player is not configured")
        if time.monotonic() < self._next_press.get(player_id, 0):
            raise RestartPending("A recent restart attempt is still pending")

        self._next_press[player_id] = float("inf")
        try:
            await self.client.restart(player_id)
        except SessionExpired, PermissionDenied, RestartRejected:
            self._next_press.pop(player_id)
            raise
        finally:
            if player_id in self._next_press:
                self._next_press[player_id] = time.monotonic() + RESTART_COOLDOWN

    @callback
    def async_mark_expired(self, hass: HomeAssistant, entry: SonosRebootConfigEntry) -> None:
        """Start one reauthentication flow and mark all this entry's buttons unavailable."""
        if not self.auth_expired:
            self.auth_expired = True
            entry.async_start_reauth(hass)
            async_dispatcher_send(hass, self.auth_signal)


type SonosRebootConfigEntry = ConfigEntry[Runtime]


@callback
def async_web_session(hass: HomeAssistant, *, auto_cleanup: bool = True) -> ClientSession:
    """Isolate each credential and ignore Set-Cookie responses from the proxy."""
    return async_create_clientsession(hass, auto_cleanup=auto_cleanup, cookie_jar=DummyCookieJar())


async def async_setup_entry(hass: HomeAssistant, entry: SonosRebootConfigEntry) -> bool:
    """Check credentials with read-only discovery and load the buttons."""
    client = SonosWebClient(async_web_session(hass), entry.data[CONF_SESSION_COOKIE])
    try:
        households = await client.households()
    except (SessionExpired, PermissionDenied) as err:
        raise ConfigEntryAuthFailed("Sonos Web session is not authorized for discovery") from err
    except SonosError as err:
        raise ConfigEntryNotReady(str(err)) from err
    if entry.data[CONF_HOUSEHOLD] not in households:
        raise ConfigEntryAuthFailed("The configured Sonos household is missing from this session")

    entry.runtime_data = Runtime(client, set(entry.data[CONF_PLAYERS]), entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SonosRebootConfigEntry) -> bool:
    """Unload the buttons."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
