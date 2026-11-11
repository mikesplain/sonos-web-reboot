"""Provide a Home Assistant restart button for each selected Sonos player."""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RestartPending, SonosRebootConfigEntry
from .api import PermissionDenied, RestartRejected, RestartUnconfirmed, SessionExpired
from .const import CONF_PLAYERS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonosRebootConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selected player buttons."""
    async_add_entities(
        RestartButton(entry, player_id, player["name"], player.get("model"))
        for player_id, player in entry.data[CONF_PLAYERS].items()
    )


class RestartButton(ButtonEntity):
    """An explicit restart action for one Sonos player."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, entry: SonosRebootConfigEntry, player_id: str, name: str, model: str | None
    ) -> None:
        self._entry = entry
        self._player_id = player_id
        self._attr_unique_id = player_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, player_id), ("sonos", player_id)},
            name=name,
            manufacturer="Sonos",
            model=model,
        )

    @property
    def available(self) -> bool:
        """Keep buttons unavailable until the user replaces an expired session."""
        return not self._entry.runtime_data.auth_expired

    async def async_added_to_hass(self) -> None:
        """Update this button when the shared session expires."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._entry.runtime_data.auth_signal, self.async_write_ha_state
            )
        )

    async def async_press(self) -> None:
        """Request a restart and translate known failure outcomes."""
        runtime = self._entry.runtime_data
        try:
            await runtime.restart(self._player_id)
        except SessionExpired:
            runtime.async_mark_expired(self.hass, self._entry)
            key = "session_expired"
        except PermissionDenied:
            key = "permission_denied"
        except RestartPending:
            key = "restart_pending"
        except RestartRejected:
            key = "restart_rejected"
        except RestartUnconfirmed:
            key = "restart_unconfirmed"
        else:
            return
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key=key)
