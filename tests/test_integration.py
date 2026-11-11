"""Exercise real config flows, device registration, and service calls with mock HTTP."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sonos_web_reboot import RestartPending, Runtime
from custom_components.sonos_web_reboot.const import (
    BASE_URL,
    CONF_HOUSEHOLD,
    CONF_PLAYERS,
    CONF_SESSION_COOKIE,
    DOMAIN,
)

HH = "Sonos_test.family"
ARC = "RINCON_AABBCCDDEE0101400"
SUB = "RINCON_AABBCCDDEE0201400"
OTHER = "RINCON_AABBCCDDEE0301400"
COOKIE = "__Secure-session-token.0=fakeA; __Secure-session-token.1=fakeB"
FRESH_COOKIE = "__Secure-session-token=fake-fresh"
HOUSEHOLDS_URL = f"{BASE_URL}/households"
GROUPS_URL = f"{HOUSEHOLDS_URL}/{HH}/groups"
ARC_URL = f"{BASE_URL}/players/{ARC}/management/reboot"
OTHER_URL = f"{BASE_URL}/players/{OTHER}/management/reboot"
HOUSEHOLDS = {"households": [{"id": HH}]}
GROUPS = {
    "groups": [{"id": f"{OTHER}:4", "coordinatorId": OTHER, "playerIds": [ARC, OTHER]}],
    "players": [
        {
            "id": ARC,
            "name": "Den",
            "deviceIds": [ARC, SUB],
            "devices": [
                {"id": SUB, "modelDisplayName": "Sub"},
                {"deviceId": ARC, "modelDisplayName": "Era 300"},
            ],
        },
        {"id": OTHER, "name": "Kitchen", "devices": []},
        {"id": f"{ARC}:2", "name": "Not a player ID"},
        {"id": "RINCON_AABBCCDDEE0401400", "name": "Spare", "isUnregistered": True},
    ],
}


async def _setup(hass, aioclient_mock, selected=(ARC, OTHER)):
    aioclient_mock.get(HOUSEHOLDS_URL, json=HOUSEHOLDS)
    aioclient_mock.get(GROUPS_URL, json=GROUPS)
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert flow["step_id"] == "user"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SESSION_COOKIE: f"Cookie: {COOKIE}"}
    )
    assert flow["step_id"] == "players"
    options = next(iter(flow["data_schema"].schema.values())).config["options"]
    assert {item["value"] for item in options} == {ARC, OTHER}
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_PLAYERS: list(selected)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert result["result"].state is ConfigEntryState.LOADED
    assert {call[0] for call in aioclient_mock.mock_calls} == {"GET"}
    return result["result"]


def _entity(hass, player_id):
    return er.async_get(hass).async_get_entity_id("button", DOMAIN, player_id)


async def _press(hass, player_id):
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity(hass, player_id)}, blocking=True
    )


async def test_selected_player_restarts_independently_of_group(hass, aioclient_mock):
    builtin = MockConfigEntry(domain="sonos", title="Local Sonos")
    builtin.add_to_hass(hass)
    registry = dr.async_get(hass)
    existing = registry.async_get_or_create(
        config_entry_id=builtin.entry_id, identifiers={("sonos", ARC)}, name="Existing TV"
    )
    entry = await _setup(hass, aioclient_mock, (ARC,))
    assert entry.data[CONF_PLAYERS] == {ARC: {"name": "Den", "model": "Era 300"}}
    assert _entity(hass, OTHER) is None
    assert _entity(hass, SUB) is None
    assert hass.states.get(_entity(hass, ARC)).attributes["device_class"] == "restart"
    assert registry.async_get(existing.id).name == "Existing TV"
    device = registry.async_get_device_by_identifier((DOMAIN, ARC), entry.entry_id)
    assert device.id != existing.id
    assert ("sonos", ARC) in device.identifiers
    assert er.async_get(hass).async_get(_entity(hass, ARC)).device_id == device.id

    aioclient_mock.post(ARC_URL, status=200)
    await _press(hass, ARC)
    requests = [call for call in aioclient_mock.mock_calls if call[0] == "POST"]
    assert len(requests) == 1
    _, url, body, headers = requests[0]
    assert str(url) == ARC_URL
    assert body == {}
    assert headers["Cookie"] == COOKIE
    assert headers["Origin"] == "https://play.sonos.com"


async def test_multi_household_setup_scopes_discovery(hass, aioclient_mock):
    second = "Sonos_other.house"
    aioclient_mock.get(HOUSEHOLDS_URL, json={"households": [{"id": HH}, {"id": second}]})
    aioclient_mock.get(f"{HOUSEHOLDS_URL}/{second}/groups", json=GROUPS)
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SESSION_COOKIE: COOKIE}
    )
    assert flow["step_id"] == "household"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_HOUSEHOLD: second})
    assert flow["step_id"] == "players"
    assert str(aioclient_mock.mock_calls[-1][1]) == f"{HOUSEHOLDS_URL}/{second}/groups"


async def test_expired_session_reauth_keeps_entity_ids(hass, aioclient_mock):
    entry = await _setup(hass, aioclient_mock)
    original_ids = {p: _entity(hass, p) for p in (ARC, OTHER)}
    aioclient_mock.post(ARC_URL, status=401)
    with pytest.raises(HomeAssistantError) as error:
        await _press(hass, ARC)
    assert error.value.translation_key == "session_expired"
    await hass.async_block_till_done()
    assert all(hass.states.get(entity).state == "unavailable" for entity in original_ids.values())
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["entry_id"] == entry.entry_id

    aioclient_mock.clear_requests()
    aioclient_mock.get(HOUSEHOLDS_URL, json={"households": [{"id": "Sonos_wrong"}]})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SESSION_COOKIE: FRESH_COOKIE}
    )
    assert result["errors"] == {"base": "wrong_household"}
    assert entry.data[CONF_SESSION_COOKIE] == COOKIE

    aioclient_mock.clear_requests()
    aioclient_mock.get(HOUSEHOLDS_URL, json=HOUSEHOLDS)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SESSION_COOKIE: FRESH_COOKIE}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_SESSION_COOKIE] == FRESH_COOKIE
    assert {p: _entity(hass, p) for p in original_ids} == original_ids
    assert all(hass.states.get(entity).state != "unavailable" for entity in original_ids.values())


async def test_reconfigure_deselection_removes_only_its_button(hass, aioclient_mock):
    entry = await _setup(hass, aioclient_mock)
    old_entity = _entity(hass, OTHER)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLAYERS: [ARC]}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert _entity(hass, OTHER) is None
    assert hass.states.get(old_entity) is None
    assert _entity(hass, ARC) is not None
    assert all(call[0] == "GET" for call in aioclient_mock.mock_calls)


async def test_expired_session_during_reconfigure_offers_reauth(hass, aioclient_mock):
    entry = await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(GROUPS_URL, status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["reason"] == "reauth_required"
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["step_id"] == "reauth_confirm"


@pytest.mark.parametrize(
    ("response", "key"),
    [
        ({"status": 403}, "permission_denied"),
        (
            {"status": 401, "headers": {"WWW-Authenticate": 'Bearer error="insufficient_scope"'}},
            "permission_denied",
        ),
        ({"json": {"globalError": {"errorCode": "ERROR_NO_PERMISSION"}}}, "permission_denied"),
        ({"status": 404}, "restart_rejected"),
        ({"status": 503}, "restart_unconfirmed"),
        ({"text": "<html>Unexpected response</html>"}, "restart_unconfirmed"),
        ({"exc": TimeoutError()}, "restart_unconfirmed"),
    ],
)
async def test_restart_errors_and_cooldown(hass, aioclient_mock, response, key):
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(ARC_URL, **response)
    aioclient_mock.post(OTHER_URL, status=204)
    with pytest.raises(HomeAssistantError) as error:
        await _press(hass, ARC)
    assert error.value.translation_key == key
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    if key == "restart_unconfirmed":
        with pytest.raises(HomeAssistantError) as repeat:
            await _press(hass, ARC)
        assert repeat.value.translation_key == "restart_pending"
    await _press(hass, OTHER)
    requests = [str(call[1]) for call in aioclient_mock.mock_calls if call[0] == "POST"]
    assert requests == [ARC_URL, OTHER_URL]


async def test_concurrent_duplicate_and_cancelled_request():
    started = asyncio.Event()

    async def restart(_):
        started.set()
        await asyncio.Future()

    client = AsyncMock()
    client.restart.side_effect = restart
    runtime = Runtime(client, {ARC}, "entry")
    task = asyncio.create_task(runtime.restart(ARC))
    try:
        await started.wait()
        with pytest.raises(RestartPending):
            await runtime.restart(ARC)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with pytest.raises(RestartPending):
        await runtime.restart(ARC)
    client.restart.assert_awaited_once_with(ARC)


async def test_bad_setup_cookie_is_not_sent_and_expired_cookie_gets_error(hass, aioclient_mock):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    invalid = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SESSION_COOKIE: "cookie=value\r\nX-Other: invalid"}
    )
    assert invalid["errors"] == {"base": "invalid_cookie"}
    assert aioclient_mock.call_count == 0
    aioclient_mock.get(HOUSEHOLDS_URL, status=401)
    expired = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_SESSION_COOKIE: COOKIE}
    )
    assert expired["errors"] == {"base": "invalid_auth"}
    assert not hass.config_entries.async_entries(DOMAIN)
