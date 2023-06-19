"""Tests for the Ruckus Unleashed integration."""
import aiohttp
from aioruckus import AjaxSession, RuckusApi
from typing import Any, List


from unittest.mock import AsyncMock, patch

from homeassistant.components.ruckus_unleashed import DOMAIN
from homeassistant.components.ruckus_unleashed.const import (
    API_AP_DEVNAME,
    API_AP_MAC,
    API_AP_MODEL,
    API_AP_SERIALNUMBER,
    API_CLIENT_AP_MAC,
    API_CLIENT_HOSTNAME,
    API_CLIENT_IP,
    API_CLIENT_MAC,
    API_MESH_NAME,
    API_MESH_PSK,
    API_SYS_IDENTITY,
    API_SYS_IDENTITY_NAME,
    API_SYS_SYSINFO,
    API_SYS_SYSINFO_SERIAL,
    API_SYS_SYSINFO_VERSION,
    API_SYS_UNLEASHEDNETWORK,
    API_SYS_UNLEASHEDNETWORK_TOKEN,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from tests.common import MockConfigEntry

DEFAULT_SYSTEM_INFO = {
    API_SYS_IDENTITY: {API_SYS_IDENTITY_NAME: "RuckusUnleashed"},
    API_SYS_SYSINFO: {
        API_SYS_SYSINFO_SERIAL: "123456789012",
        API_SYS_SYSINFO_VERSION: "200.7.10.202 build 141",
    },
    API_SYS_UNLEASHEDNETWORK: {
        API_SYS_UNLEASHEDNETWORK_TOKEN: "un1234567890121680060227001"
    },
}

DEFAULT_MESH_INFO = {
    API_MESH_NAME: "mesh-"
    + DEFAULT_SYSTEM_INFO[API_SYS_SYSINFO][API_SYS_SYSINFO_SERIAL],
    API_MESH_PSK: "'xLgkZhXhaE-Io5p7YUwbSNxmgUX68xBwWagWCg_5osPGLBGfIfw1AvcaJHH3ouc'",
}

DEFAULT_AP_INFO = [
    {
        API_AP_MAC: "00:11:22:33:44:55",
        API_AP_DEVNAME: "Test Device",
        API_AP_MODEL: "r510",
        API_AP_SERIALNUMBER: DEFAULT_SYSTEM_INFO[API_SYS_SYSINFO][
            API_SYS_SYSINFO_SERIAL
        ],
    }
]

CONFIG = {
    CONF_HOST: "1.1.1.1",
    CONF_USERNAME: "test-username",
    CONF_PASSWORD: "test-password",
}

TEST_CLIENT_ENTITY_ID = "device_tracker.ruckus_test_device"
TEST_CLIENT = {
    API_CLIENT_IP: "1.1.1.2",
    API_CLIENT_MAC: "AA:BB:CC:DD:EE:FF",
    API_CLIENT_HOSTNAME: "Ruckus Test Device",
    API_CLIENT_AP_MAC: DEFAULT_AP_INFO[0][API_AP_MAC],
}

DEFAULT_TITLE = DEFAULT_SYSTEM_INFO[API_SYS_IDENTITY][API_SYS_IDENTITY_NAME]
DEFAULT_UNIQUEID = (
    DEFAULT_SYSTEM_INFO[API_SYS_UNLEASHEDNETWORK][API_SYS_UNLEASHEDNETWORK_TOKEN]
    if API_SYS_UNLEASHEDNETWORK in DEFAULT_SYSTEM_INFO
    else DEFAULT_SYSTEM_INFO[API_SYS_IDENTITY][API_SYS_IDENTITY_NAME]
)


def mock_config_entry() -> MockConfigEntry:
    """Return a Ruckus Unleashed mock config entry."""

    return MockConfigEntry(
        domain=DOMAIN,
        title=DEFAULT_TITLE,
        unique_id=DEFAULT_UNIQUEID,
        data=CONFIG,
        options=None,
    )


# class MockAjaxSession:
#     """Mock Ruckus Ajax Session."""

#     def __init__(
#         self,
#         websession,
#         host: str,
#         username: str,
#         password: str,
#         auto_cleanup_websession=False,
#     ) -> None:
#         """Mock init."""
#         self.websession = websession
#         self.host = host
#         self.username = username
#         self.password = password
#         # self.api = RuckusApi(self)
#         self.api = aioruckus.RuckusAjaxApi(self)

#     async def __aenter__(self, *args, **kwargs) -> "MockAjaxSession":
#         """Async enter."""
#         return self

#     async def __aexit__(self, *args, **kwargs) -> None:
#         """Async exit."""

#     async def login(self) -> None:
#         """Mock login."""
#         print("IDF: login()")

#     async def close(self) -> None:
#         """Mock close."""

#     @classmethod
#     def async_create(cls, host: str, username: str, password: str) -> "MockAjaxSession":
#         """Mock async_create."""
#         print("IDF: async_create()")
#         return MockAjaxSession(None, host, username, password, True)


class MockSession(AjaxSession):
    """Mock Session"""

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        auto_cleanup_websession=False,
    ) -> None:
        super().__init__(websession, host, username, password, auto_cleanup_websession)
        self.mock_results = {}
        self._api = MockApi(self)

    async def __aenter__(self) -> "AjaxSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        pass

    async def login(self) -> None:
        pass

    async def close(self) -> None:
        pass

    @property
    def api(self) -> "MockApi":
        return self._api

    @classmethod
    def async_create(cls, host: str, username: str, password: str) -> "AjaxSession":
        return MockSession(None, host, username, password, True)

    # IDF item : ConfigItem
    async def get_conf_str(self, item, timeout: int | None = None) -> str:
        return self.mock_results[item.value]


class MockApi(RuckusApi):
    """Mock Session"""

    def __init__(self, session: MockSession):
        self.session = session

    async def get_active_clients(self, interval_stats: bool = False) -> List:
        """Mock get_active_clients"""
        if interval_stats:
            raise NotImplementedError(self)
        else:
            result_text = self.session.mock_results["active-client-stats1"]
            return self._ruckus_xml_unwrap(result_text, ["client"])


async def init_integration(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the Ruckus Unleashed integration in Home Assistant."""
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    # Make device tied to other integration so device tracker entities get enabled
    dr.async_get(hass).async_get_or_create(
        name="Device from other integration",
        config_entry_id=MockConfigEntry().entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, TEST_CLIENT[API_CLIENT_MAC])},
    )
    with patch(
        #     "homeassistant.components.ruckus_unleashed.RuckusUnleashedDataUpdateCoordinator._fetch_clients",
        #     return_value={
        #         TEST_CLIENT[API_CLIENT_AP_MAC]: TEST_CLIENT,
        #     },
        #     # ), patch(
        #     #     "homeassistant.components.ruckus_unleashed.aioruckus.AjaxSession.login",
        #     #     return_value={
        #     #         asyncio.Future(),
        #     #     },
        # ), patch(
        #     "homeassistant.components.ruckus_unleashed.AjaxSession.RuckusAjaxApi.get_system_info",
        #     new_callable=AsyncMock,
        # ) as async_mock_get_system_info, patch(
        "homeassistant.components.ruckus_unleashed.AjaxSession",
        # MockAjaxSession,
        MockSession,
    ):
        # async_mock_get_system_info.return_value = DEFAULT_SYSTEM_INFO
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry
