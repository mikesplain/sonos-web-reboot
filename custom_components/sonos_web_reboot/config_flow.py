"""Set up, update, and reauthenticate Sonos Web Reboot from the UI."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from . import async_web_session
from .api import (
    PermissionDenied,
    Player,
    SessionExpired,
    SonosError,
    SonosWebClient,
    normalize_cookie,
)
from .const import CONF_HOUSEHOLD, CONF_PLAYERS, CONF_SESSION_COOKIE, DOMAIN

_COOKIE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SESSION_COOKIE): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)


class SonosWebRebootConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add restart buttons for the explicitly selected players in a household."""

    VERSION = 1

    def __init__(self) -> None:
        self._cookie = ""
        self._households: dict[str, str] = {}
        self._household_id = ""
        self._players: dict[str, Player] = {}

    @contextmanager
    def _client(self, cookie: str) -> Iterator[SonosWebClient]:
        session = async_web_session(self.hass, auto_cleanup=False)
        try:
            yield SonosWebClient(session, cookie)
        finally:
            session.detach()

    async def _check_cookie(self, user_input: dict[str, Any]) -> str | None:
        """Validate with read-only discovery and return the UI error key, if any."""
        try:
            cookie = normalize_cookie(user_input[CONF_SESSION_COOKIE])
        except ValueError:
            return "invalid_cookie"
        try:
            with self._client(cookie) as client:
                households = await client.households()
        except SessionExpired, PermissionDenied:
            return "invalid_auth"
        except SonosError:
            return "cannot_connect"
        self._cookie = cookie
        self._households = households
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Prompt for the signed-in browser's Cookie request header."""
        if user_input is not None:
            error = await self._check_cookie(user_input)
            if error is None:
                if not self._households:
                    return self.async_abort(reason="no_households")
                if len(self._households) == 1:
                    return await self._choose_household(next(iter(self._households)))
                return await self.async_step_household()
            return self.async_show_form(
                step_id="user", data_schema=_COOKIE_SCHEMA, errors={"base": error}
            )
        return self.async_show_form(step_id="user", data_schema=_COOKIE_SCHEMA)

    async def async_step_household(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let users with multiple systems choose the intended household."""
        if user_input is not None:
            return await self._choose_household(user_input[CONF_HOUSEHOLD])
        choices = [
            selector.SelectOptionDict(value=key, label=name)
            for key, name in self._households.items()
        ]
        return self.async_show_form(
            step_id="household",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOUSEHOLD): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=choices, mode=selector.SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def _choose_household(self, household_id: str) -> ConfigFlowResult:
        """Discover players without sending a reboot or a playback command."""
        await self.async_set_unique_id(household_id)
        self._abort_if_unique_id_configured()
        self._household_id = household_id
        try:
            with self._client(self._cookie) as client:
                self._players = await client.players(household_id)
        except SessionExpired, PermissionDenied:
            return self.async_abort(reason="invalid_auth")
        except SonosError:
            return self.async_abort(reason="cannot_connect")
        if not self._players:
            return self.async_abort(reason="no_players")
        return await self.async_step_players()

    def _player_form(
        self, step_id: str, current: dict[str, Any] | None = None, error: str | None = None
    ) -> ConfigFlowResult:
        current = current or {}
        choices = [
            selector.SelectOptionDict(
                value=player.id,
                label=f"{player.name} · {player.model or 'Sonos'} · {player.id[-9:]}",
            )
            for player in sorted(
                self._players.values(), key=lambda player: (player.name.casefold(), player.id)
            )
        ]
        choices.extend(
            selector.SelectOptionDict(
                value=player_id, label=f"{player['name']} · {player_id[-9:]} · not listed by Sonos"
            )
            for player_id, player in current.items()
            if player_id not in self._players
        )
        field = (
            vol.Required(CONF_PLAYERS, default=list(current))
            if current
            else vol.Required(CONF_PLAYERS)
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    field: selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=choices, multiple=True, mode=selector.SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            errors={"base": error} if error else {},
        )

    def _selected_players(self, requested: list[str], current: dict[str, Any]) -> dict[str, Any]:
        return {
            player_id: {"name": player.name, "model": player.model}
            if (player := self._players.get(player_id)) is not None
            else current[player_id]
            for player_id in requested
        }

    async def async_step_players(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save exactly the players selected by the user."""
        if user_input is not None:
            requested = user_input[CONF_PLAYERS]
            if requested and set(requested) <= self._players.keys():
                return self.async_create_entry(
                    title=f"Sonos Web Reboot · {self._households[self._household_id]}",
                    data={
                        CONF_SESSION_COOKIE: self._cookie,
                        CONF_HOUSEHOLD: self._household_id,
                        CONF_PLAYERS: self._selected_players(requested, {}),
                    },
                )
            return self._player_form("players", error="select_players")
        return self._player_form("players")

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start Home Assistant's linked reauthentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the cookie while retaining the same household and player IDs."""
        if user_input is not None:
            entry = self._get_reauth_entry()
            error = await self._check_cookie(user_input)
            if error is None:
                if entry.data[CONF_HOUSEHOLD] in self._households:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_SESSION_COOKIE: self._cookie}
                    )
                error = "wrong_household"
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=_COOKIE_SCHEMA, errors={"base": error}
            )
        return self.async_show_form(step_id="reauth_confirm", data_schema=_COOKIE_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change which players have buttons, retaining the same Sonos account."""
        entry = self._get_reconfigure_entry()
        current = entry.data[CONF_PLAYERS]
        if user_input is None:
            try:
                with self._client(entry.data[CONF_SESSION_COOKIE]) as client:
                    self._players = await client.players(entry.data[CONF_HOUSEHOLD])
            except SessionExpired:
                # Home Assistant allows only one of these flows per entry. Start
                # reauthentication after this reconfigure flow finishes aborting.
                self.hass.loop.call_soon(entry.async_start_reauth, self.hass)
                return self.async_abort(reason="reauth_required")
            except PermissionDenied:
                return self.async_abort(reason="invalid_auth")
            except SonosError:
                return self.async_abort(reason="cannot_connect")
            return self._player_form("reconfigure", current)

        requested = user_input[CONF_PLAYERS]
        if not requested or not set(requested) <= self._players.keys() | current.keys():
            return self._player_form("reconfigure", current, "select_players")
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        for removed_id in current.keys() - set(requested):
            entity_id = entities.async_get_entity_id("button", DOMAIN, removed_id)
            entity = entities.async_get(entity_id) if entity_id is not None else None
            if entity is not None and entity.config_entry_id == entry.entry_id:
                entities.async_remove(entity.entity_id)
            device = devices.async_get_device_by_identifier((DOMAIN, removed_id), entry.entry_id)
            if device is not None:
                devices.async_remove_device(device.id)
        return self.async_update_reload_and_abort(
            entry, data_updates={CONF_PLAYERS: self._selected_players(requested, current)}
        )
