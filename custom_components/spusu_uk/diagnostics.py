"""Diagnostics deliberately omit all identifiers, credentials, and raw responses."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "renewing_session": coordinator.renewing,
        "reauthentication_required": coordinator.auth_failed,
        "metric_count": len(coordinator.data or {}),
        "categories": sorted(
            {metric.category for metric in (coordinator.data or {}).values()}
        ),
    }
