"""Find captcha DOM across pages/frames and collect diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Frame, Page, TimeoutError as PlaywrightTimeout

CAPTCHA_DIAG_JS = """
() => {
  const root = document.getElementById('captcha');
  if (!root) return { found: false };
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  };
  const mask = root.querySelector('.sliderMask')
    || root.querySelector('.slider > div')
    || root.querySelector(':scope > div:nth-child(2) > div');
  const handle = root.querySelector('.sliderHandler')
    || root.querySelector(':scope > div:nth-child(2) > div > div');
  const slider = root.querySelector('.slider') || root.querySelector(':scope > div:nth-child(2)');
  return {
    found: true,
    rootRect: rect(root),
    className: root.className,
    children: [...root.children].map((c) => ({
      tag: c.tagName,
      class: c.className,
      id: c.id,
      rect: rect(c),
    })),
    mask: mask ? { class: mask.className, left: mask.style.left, rect: rect(mask) } : null,
    handle: handle ? { class: handle.className, rect: rect(handle) } : null,
    slider: slider ? { class: slider.className, rect: rect(slider) } : null,
    canvases: [...root.querySelectorAll('canvas')].map((c, i) => ({
      i,
      width: c.width,
      height: c.height,
      rect: rect(c),
    })),
    globals: {
      sliderCaptcha: typeof sliderCaptcha !== 'undefined',
      jquerySlider: Boolean(window.jQuery && window.jQuery.fn && window.jQuery.fn.sliderCaptcha),
    },
    htmlSnippet: root.outerHTML.slice(0, 5000),
  };
}
"""


@dataclass(frozen=True)
class CaptchaScope:
    """Where #captcha lives and which page owns mouse events."""

    scope: Page | Frame
    page: Page
    in_frame: bool

    @property
    def label(self) -> str:
        if isinstance(self.scope, Page):
            return "main"
        return f"frame:{self.scope.name or self.scope.url}"


def iter_scopes(page: Page):
    yield page
    for frame in page.frames:
        if frame != page.main_frame:
            yield frame


def find_captcha_scope_in_page(page: Page) -> CaptchaScope | None:
    for scope in iter_scopes(page):
        try:
            loc = scope.locator("#captcha")
            if loc.count() > 0 and loc.first.is_visible(timeout=250):
                return CaptchaScope(
                    scope=scope,
                    page=page,
                    in_frame=isinstance(scope, Frame),
                )
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return None


def find_captcha_scope(context: BrowserContext) -> CaptchaScope | None:
    for page in context.pages:
        found = find_captcha_scope_in_page(page)
        if found is not None:
            return found
    return None


def resolve_captcha_scope(context: BrowserContext, hint_page: Page) -> CaptchaScope:
    found = find_captcha_scope(context)
    if found is not None:
        return found
    return CaptchaScope(scope=hint_page, page=hint_page, in_frame=False)


def collect_context_overview(context: BrowserContext) -> list[dict[str, Any]]:
    overview: list[dict[str, Any]] = []
    for i, page in enumerate(context.pages):
        entry: dict[str, Any] = {
            "page_index": i,
            "url": page.url,
            "title": "",
            "frames": [],
            "captcha": None,
        }
        try:
            entry["title"] = page.title()
        except PlaywrightError:
            pass
        for j, frame in enumerate(page.frames):
            frame_info: dict[str, Any] = {
                "frame_index": j,
                "name": frame.name,
                "url": frame.url,
                "captcha_count": 0,
            }
            try:
                frame_info["captcha_count"] = frame.locator("#captcha").count()
            except PlaywrightError:
                pass
            entry["frames"].append(frame_info)
        found = find_captcha_scope_in_page(page)
        if found is not None:
            entry["captcha"] = describe_captcha_scope(found)
        overview.append(entry)
    return overview


def describe_captcha_scope(cs: CaptchaScope) -> dict[str, Any]:
    info: dict[str, Any] = {
        "location": cs.label,
        "page_url": cs.page.url,
        "in_frame": cs.in_frame,
    }
    try:
        info["dom"] = cs.scope.evaluate(CAPTCHA_DIAG_JS)
    except PlaywrightError as exc:
        info["dom_error"] = str(exc)
    try:
        handle = cs.scope.locator("#captcha .slider").first
        info["handle_box"] = handle.bounding_box()
    except PlaywrightError:
        info["handle_box"] = None
    try:
        from gacc_slider_solver import read_slider_left

        info["slider_left_before"] = read_slider_left(cs.scope)
    except Exception as exc:
        info["slider_left_error"] = str(exc)
    return info


def format_diagnostics(context: BrowserContext, cs: CaptchaScope | None = None) -> str:
    parts: list[str] = []
    overview = collect_context_overview(context)
    parts.append(f"browser_pages={len(context.pages)}")
    for entry in overview:
        parts.append(
            f"p{entry['page_index']}:{entry['url'][:70]} "
            f"frames={len(entry['frames'])} captcha={'yes' if entry.get('captcha') else 'no'}"
        )
        if entry.get("captcha"):
            dom = entry["captcha"].get("dom") or {}
            mask = dom.get("mask") or {}
            parts.append(
                f"  loc={entry['captcha'].get('location')} "
                f"mask.left={mask.get('left')} "
                f"lib={dom.get('globals')}"
            )
    if cs is not None:
        detail = describe_captcha_scope(cs)
        parts.append(f"active={json.dumps(detail, ensure_ascii=False)[:1200]}")
    return " | ".join(parts)


def save_diagnostics(
    context: BrowserContext,
    cs: CaptchaScope | None,
    *,
    out_path: Path,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "overview": collect_context_overview(context),
        "active": describe_captcha_scope(cs) if cs else None,
        "extra": extra or {},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
