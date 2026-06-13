"""Detect user closing the headed Playwright browser during GACC fetch."""

from __future__ import annotations

import threading
import time

from playwright.sync_api import Browser, BrowserContext, Error as PlaywrightError, Page


class BrowserClosedError(RuntimeError):
    """User closed the browser window; abort the collection job."""


def attach_browser_close_watch(
    browser: Browser,
    context: BrowserContext,
    page: Page,
) -> threading.Event:
    """Return an event set when the user closes the browser or main page."""
    closed = threading.Event()

    def _mark_closed(*_args) -> None:
        closed.set()

    browser.on("disconnected", _mark_closed)
    context.on("close", _mark_closed)
    page.on("close", _mark_closed)
    return closed


def ensure_browser_open(closed: threading.Event | None) -> None:
    if closed is not None and closed.is_set():
        raise BrowserClosedError("用户已关闭浏览器，采集任务已结束")


def abortable_sleep(seconds: float, closed: threading.Event | None) -> None:
    ensure_browser_open(closed)
    deadline = time.time() + seconds
    while time.time() < deadline:
        ensure_browser_open(closed)
        time.sleep(min(0.2, deadline - time.time()))


def guard_playwright(closed: threading.Event | None, exc: PlaywrightError) -> None:
    """Re-raise as BrowserClosedError when the failure is due to browser shutdown."""
    if closed is not None and closed.is_set():
        raise BrowserClosedError("用户已关闭浏览器，采集任务已结束") from exc
    msg = str(exc).lower()
    if "target closed" in msg or "browser has been closed" in msg or "context closed" in msg:
        raise BrowserClosedError("用户已关闭浏览器，采集任务已结束") from exc
    raise exc
