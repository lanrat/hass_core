"""Tests for the keyboard_remote click detector."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import time
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.keyboard_remote.click_detector import (
    ClickEventType,
    KeyClickDetector,
)
from homeassistant.core import HomeAssistant


def _mock_monotonic(*values: float) -> Callable[[], float]:
    """Create a mock for time.monotonic that returns values then falls back to real.

    The event loop also calls time.monotonic() internally (e.g., in call_later),
    so we provide specified values first and then fall back to the real
    implementation for any additional calls.
    """
    real = time.monotonic
    vals = list(values)

    def _monotonic() -> float:
        if vals:
            return vals.pop(0)
        return real()

    return _monotonic


@pytest.fixture
def fire_event() -> MagicMock:
    """Create a mock fire_event callback."""
    return MagicMock()


def _create_detector(
    hass: HomeAssistant,
    fire_event: MagicMock,
    *,
    click_enabled: bool = True,
    double_click_enabled: bool = True,
    long_click_enabled: bool = True,
    click_threshold: float = 0.400,
    double_click_timeout: float = 0.300,
    long_click_min: float = 0.400,
    long_click_max: float = 3.000,
) -> KeyClickDetector:
    """Create a KeyClickDetector with configurable parameters."""
    return KeyClickDetector(
        hass=hass,
        fire_event=fire_event,
        click_enabled=click_enabled,
        double_click_enabled=double_click_enabled,
        long_click_enabled=long_click_enabled,
        click_threshold=click_threshold,
        double_click_timeout=double_click_timeout,
        long_click_min=long_click_min,
        long_click_max=long_click_max,
    )


async def test_single_click(hass: HomeAssistant, fire_event: MagicMock) -> None:
    """Test short press followed by double-click timeout fires click."""
    detector = _create_detector(hass, fire_event, double_click_timeout=0.01)

    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    # Wait for the double-click timeout to expire
    await asyncio.sleep(0.05)

    fire_event.assert_called_once_with(30, ClickEventType.CLICK)


async def test_single_click_immediate_without_double_click(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test click fires immediately on key_up when double_click is disabled."""
    detector = _create_detector(hass, fire_event, double_click_enabled=False)

    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    # Click should fire immediately, no waiting
    fire_event.assert_called_once_with(30, ClickEventType.CLICK)


async def test_double_click(hass: HomeAssistant, fire_event: MagicMock) -> None:
    """Test two quick presses fire only double_click, not two clicks."""
    detector = _create_detector(hass, fire_event)

    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1, 0.2, 0.3)):
        detector.on_key_down(30)  # First press
        detector.on_key_up(30)  # First release (short press)
        detector.on_key_down(30)  # Second press (within timeout)
        detector.on_key_up(30)  # Second release

    fire_event.assert_called_once_with(30, ClickEventType.DOUBLE_CLICK)


async def test_long_click(hass: HomeAssistant, fire_event: MagicMock) -> None:
    """Test press held beyond click_threshold fires long_click."""
    detector = _create_detector(hass, fire_event)

    # Press for 1.0s (above click_threshold of 0.4s, below long_click_max of 3.0s)
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 1.0)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    fire_event.assert_called_once_with(30, ClickEventType.LONG_CLICK)


async def test_long_click_at_boundary(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test press exactly at click_threshold boundary fires long_click."""
    detector = _create_detector(
        hass, fire_event, click_threshold=0.4, long_click_min=0.4
    )

    # Press for exactly 0.4s (not < 0.4, so it goes to long_click check)
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.4)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    fire_event.assert_called_once_with(30, ClickEventType.LONG_CLICK)


async def test_hold_too_long(hass: HomeAssistant, fire_event: MagicMock) -> None:
    """Test press exceeding long_click_max fires no calculated event."""
    detector = _create_detector(hass, fire_event)

    # Press for 5.0s (above long_click_max of 3.0s)
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 5.0)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    fire_event.assert_not_called()


async def test_cancel_during_wait_double_click(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test cancel_all during WAIT_DOUBLE_CLICK prevents stale click."""
    detector = _create_detector(hass, fire_event, double_click_timeout=0.5)

    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    # Cancel before timeout expires
    detector.cancel_all()

    # Wait longer than timeout
    await asyncio.sleep(0.6)

    # No event should have fired
    fire_event.assert_not_called()


async def test_multiple_keys_independent(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test different key codes are tracked independently."""
    detector = _create_detector(hass, fire_event, double_click_enabled=False)

    # Key 30: short click, Key 31: long click
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.0, 0.1, 1.0)):
        detector.on_key_down(30)
        detector.on_key_down(31)
        detector.on_key_up(30)  # 0.1s duration -> click
        detector.on_key_up(31)  # 1.0s duration -> long_click

    assert fire_event.call_count == 2
    fire_event.assert_any_call(30, ClickEventType.CLICK)
    fire_event.assert_any_call(31, ClickEventType.LONG_CLICK)


async def test_unexpected_key_down_resets(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test key_down without preceding key_up resets state cleanly."""
    detector = _create_detector(hass, fire_event, double_click_enabled=False)

    # Two key_downs without key_up in between, then key_up
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 1.0, 1.1)):
        detector.on_key_down(30)
        detector.on_key_down(30)  # Reset, new press at t=1.0
        detector.on_key_up(30)  # Duration = 0.1s -> click

    fire_event.assert_called_once_with(30, ClickEventType.CLICK)


async def test_second_press_held_long_fires_double_click(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test double-click fires even if second press is held long."""
    detector = _create_detector(hass, fire_event)

    # First press: short. Second press: held long. Should still be double_click.
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1, 0.2, 5.0)):
        detector.on_key_down(30)
        detector.on_key_up(30)  # Short press
        detector.on_key_down(30)  # Second press
        detector.on_key_up(30)  # Long hold, but state is PRESSED_SECOND

    fire_event.assert_called_once_with(30, ClickEventType.DOUBLE_CLICK)


async def test_click_disabled_no_click_event(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test click event is suppressed when click is disabled."""
    detector = _create_detector(
        hass,
        fire_event,
        click_enabled=False,
        double_click_enabled=False,
        long_click_enabled=True,
    )

    # Short press that would normally be a click
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    fire_event.assert_not_called()


async def test_long_click_disabled_no_long_click_event(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test long_click event is suppressed when long_click is disabled."""
    detector = _create_detector(
        hass,
        fire_event,
        click_enabled=True,
        double_click_enabled=False,
        long_click_enabled=False,
    )

    # Long press that would normally be long_click
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 1.0)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    fire_event.assert_not_called()


async def test_double_click_disabled_no_double_click_event(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test double_click event is suppressed when double_click is disabled."""
    detector = _create_detector(
        hass,
        fire_event,
        click_enabled=True,
        double_click_enabled=False,
        long_click_enabled=True,
    )

    # Two quick presses - since double_click is disabled, each fires as click
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 0.1, 0.2, 0.3)):
        detector.on_key_down(30)
        detector.on_key_up(30)  # Click fires immediately
        detector.on_key_down(30)
        detector.on_key_up(30)  # Another click fires immediately

    assert fire_event.call_count == 2
    fire_event.assert_any_call(30, ClickEventType.CLICK)


async def test_key_up_in_idle_ignored(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test key_up without preceding key_down is ignored."""
    detector = _create_detector(hass, fire_event)

    detector.on_key_up(30)

    fire_event.assert_not_called()


async def test_long_click_at_max_boundary(
    hass: HomeAssistant, fire_event: MagicMock
) -> None:
    """Test press exactly at long_click_max boundary still fires."""
    detector = _create_detector(hass, fire_event, long_click_max=3.0)

    # Press for exactly 3.0s (at max boundary, should fire)
    with patch("time.monotonic", side_effect=_mock_monotonic(0.0, 3.0)):
        detector.on_key_down(30)
        detector.on_key_up(30)

    fire_event.assert_called_once_with(30, ClickEventType.LONG_CLICK)
