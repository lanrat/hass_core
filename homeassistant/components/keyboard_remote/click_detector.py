"""Click, double-click, and long-click detection for keyboard remote."""

from __future__ import annotations

import asyncio
from enum import StrEnum
import time
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

if TYPE_CHECKING:
    from collections.abc import Callable


class ClickEventType(StrEnum):
    """Calculated click event types."""

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    LONG_CLICK = "long_click"


class _KeyState(StrEnum):
    """Internal state machine states for a single key."""

    IDLE = "idle"
    PRESSED = "pressed"
    WAIT_DOUBLE_CLICK = "wait_double_click"
    PRESSED_SECOND = "pressed_second"


class _PerKeyTracker:
    """State machine for click detection on a single key code."""

    __slots__ = (
        "_click_threshold",
        "_double_click_enabled",
        "_double_click_timeout",
        "_fire_event",
        "_key_code",
        "_long_click_max",
        "_long_click_min",
        "_loop",
        "_press_time",
        "_state",
        "_timer_handle",
    )

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        key_code: int,
        fire_event: Callable[[int, ClickEventType], None],
        *,
        click_threshold: float,
        double_click_timeout: float,
        double_click_enabled: bool,
        long_click_min: float,
        long_click_max: float,
    ) -> None:
        """Initialize per-key tracker."""
        self._loop = loop
        self._key_code = key_code
        self._fire_event = fire_event
        self._click_threshold = click_threshold
        self._double_click_timeout = double_click_timeout
        self._double_click_enabled = double_click_enabled
        self._long_click_min = long_click_min
        self._long_click_max = long_click_max
        self._state = _KeyState.IDLE
        self._press_time: float = 0.0
        self._timer_handle: asyncio.TimerHandle | None = None

    @callback
    def on_key_down(self) -> None:
        """Handle key_down event."""
        match self._state:
            case _KeyState.IDLE:
                self._press_time = time.monotonic()
                self._state = _KeyState.PRESSED
            case _KeyState.WAIT_DOUBLE_CLICK:
                self._cancel_timer()
                self._press_time = time.monotonic()
                self._state = _KeyState.PRESSED_SECOND
            case _:
                # Unexpected key_down in PRESSED or PRESSED_SECOND
                # (e.g., autorepeat without key_up). Reset to PRESSED.
                self._cancel_timer()
                self._press_time = time.monotonic()
                self._state = _KeyState.PRESSED

    @callback
    def on_key_up(self) -> None:
        """Handle key_up event."""
        match self._state:
            case _KeyState.PRESSED:
                duration = time.monotonic() - self._press_time
                if duration < self._click_threshold:
                    if self._double_click_enabled:
                        # Wait for possible second press
                        self._state = _KeyState.WAIT_DOUBLE_CLICK
                        self._timer_handle = self._loop.call_later(
                            self._double_click_timeout,
                            self._on_double_click_timeout,
                        )
                    else:
                        # Fire click immediately
                        self._fire_event(self._key_code, ClickEventType.CLICK)
                        self._state = _KeyState.IDLE
                elif self._long_click_min <= duration <= self._long_click_max:
                    self._fire_event(self._key_code, ClickEventType.LONG_CLICK)
                    self._state = _KeyState.IDLE
                else:
                    # Too long, no event
                    self._state = _KeyState.IDLE
            case _KeyState.PRESSED_SECOND:
                self._fire_event(self._key_code, ClickEventType.DOUBLE_CLICK)
                self._state = _KeyState.IDLE
            case _:
                # Unexpected key_up in IDLE or WAIT_DOUBLE_CLICK
                self._state = _KeyState.IDLE

    @callback
    def _on_double_click_timeout(self) -> None:
        """Handle double-click timeout expiry -- fire single click."""
        self._timer_handle = None
        if self._state == _KeyState.WAIT_DOUBLE_CLICK:
            self._fire_event(self._key_code, ClickEventType.CLICK)
            self._state = _KeyState.IDLE

    def _cancel_timer(self) -> None:
        """Cancel any pending timer."""
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None

    def cancel(self) -> None:
        """Cancel all pending operations (for cleanup)."""
        self._cancel_timer()
        self._state = _KeyState.IDLE


class KeyClickDetector:
    """Detect click, double-click, and long-click from raw key events.

    One instance per DeviceHandler. Manages _PerKeyTracker instances
    per key code on demand.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        fire_event: Callable[[int, ClickEventType], None],
        *,
        click_enabled: bool,
        double_click_enabled: bool,
        long_click_enabled: bool,
        click_threshold: float,
        double_click_timeout: float,
        long_click_min: float,
        long_click_max: float,
    ) -> None:
        """Initialize the click detector."""
        self._hass = hass
        self._fire_event = fire_event
        self._click_enabled = click_enabled
        self._double_click_enabled = double_click_enabled
        self._long_click_enabled = long_click_enabled
        self._click_threshold = click_threshold
        self._double_click_timeout = double_click_timeout
        self._long_click_min = long_click_min
        self._long_click_max = long_click_max
        self._trackers: dict[int, _PerKeyTracker] = {}

    def _filter_event(self, key_code: int, click_type: ClickEventType) -> None:
        """Filter events based on which calculated types are enabled."""
        match click_type:
            case ClickEventType.CLICK if self._click_enabled:
                self._fire_event(key_code, click_type)
            case ClickEventType.DOUBLE_CLICK if self._double_click_enabled:
                self._fire_event(key_code, click_type)
            case ClickEventType.LONG_CLICK if self._long_click_enabled:
                self._fire_event(key_code, click_type)

    def _get_tracker(self, key_code: int) -> _PerKeyTracker:
        """Get or create a per-key tracker."""
        if key_code not in self._trackers:
            self._trackers[key_code] = _PerKeyTracker(
                loop=self._hass.loop,
                key_code=key_code,
                fire_event=self._filter_event,
                click_threshold=self._click_threshold,
                double_click_timeout=self._double_click_timeout,
                double_click_enabled=self._double_click_enabled,
                long_click_min=self._long_click_min,
                long_click_max=self._long_click_max,
            )
        return self._trackers[key_code]

    @callback
    def on_key_down(self, key_code: int) -> None:
        """Process a key_down event."""
        self._get_tracker(key_code).on_key_down()

    @callback
    def on_key_up(self, key_code: int) -> None:
        """Process a key_up event."""
        self._get_tracker(key_code).on_key_up()

    def cancel_all(self) -> None:
        """Cancel all pending timers (for cleanup on disconnect/unload)."""
        for tracker in self._trackers.values():
            tracker.cancel()
        self._trackers.clear()
