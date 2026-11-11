"""Run the integration against an isolated Home Assistant config directory."""

from pathlib import Path

import pytest


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Let Home Assistant load the integration through its normal loader."""
    (tmp_path / "custom_components").symlink_to(
        Path(__file__).resolve().parents[1] / "custom_components", target_is_directory=True
    )
    return str(tmp_path)


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations: None) -> None:
    """Enable Home Assistant's custom component discovery."""
