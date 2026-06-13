import threading

import pytest
from playwright.sync_api import Error as PlaywrightError

from gacc_browser_watch import (
    BrowserClosedError,
    abortable_sleep,
    ensure_browser_open,
    guard_playwright,
)


def test_ensure_browser_open_raises_when_closed() -> None:
    closed = threading.Event()
    closed.set()
    with pytest.raises(BrowserClosedError, match="用户已关闭浏览器"):
        ensure_browser_open(closed)


def test_abortable_sleep_interrupts_when_closed() -> None:
    closed = threading.Event()

    def _close_soon() -> None:
        closed.set()

    threading.Timer(0.05, _close_soon).start()
    with pytest.raises(BrowserClosedError):
        abortable_sleep(2.0, closed)


def test_guard_playwright_maps_target_closed() -> None:
    exc = PlaywrightError("Target page, context or browser has been closed")
    with pytest.raises(BrowserClosedError):
        guard_playwright(None, exc)
