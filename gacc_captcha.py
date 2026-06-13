"""Captcha providers for stats.customs.gov.cn automation."""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Frame, Page, TimeoutError as PlaywrightTimeout

from gacc_browser_watch import BrowserClosedError, abortable_sleep, ensure_browser_open

from config import (
    GACC_CAPTCHA_AUTO,
    GACC_CAPTCHA_AUTO_MAX_ATTEMPTS,
    GACC_CAPTCHA_FALLBACK_MANUAL,
    GACC_CAPTCHA_OFFSET_PX,
    GACC_CAPTCHA_TIMEOUT_SEC,
)
from gacc_captcha_scope import (
    CaptchaScope,
    find_captcha_scope,
    find_captcha_scope_in_page,
    format_diagnostics,
    resolve_captcha_scope,
    save_diagnostics,
)
from gacc_slider_solver import (
    MAX_TRIES_PER_CAPTCHA,
    block_left_to_slider,
    build_initial_targets,
    captcha_failed,
    drag_captcha_handle,
    expand_targets_from_landing,
    parse_layout,
    read_block_left,
    read_captcha_msg,
    read_slider_offset,
    reset_slider_position,
    solve_from_meta,
    track_travel_from_layout,
)


class CaptchaProvider(Protocol):
    def wait_until_passed(self, page: Page) -> None: ...


def _iter_scopes(page: Page):
    yield page
    for frame in page.frames:
        if frame != page.main_frame:
            yield frame


def _passive_state(scope: Page | Frame) -> str | None:
    """只读检测页面状态，不触发任何 click/focus。"""
    try:
        return scope.evaluate(
            """
            () => {
                const text = document.body?.innerText || '';
                if (text.includes('数据加载中')) return 'loading';
                const img = document.querySelector(
                    'img[src*="loadinge"], img[src*="loading"]'
                );
                if (img) {
                    const style = window.getComputedStyle(img);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && img.offsetParent !== null) {
                        return 'loading';
                    }
                }
                const dl = document.getElementById('downLoad');
                const onResults = dl && dl.offsetParent !== null && text.includes('商品编码');
                let hasData = false;
                const rows = document.querySelectorAll('table tbody tr');
                for (const row of rows) {
                    const t = (row.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (!t || t.includes('数据加载中')) continue;
                    const cells = row.querySelectorAll('td');
                    if (cells.length < 2) continue;
                    const c0 = (cells[0].innerText || '').trim();
                    if (c0 && c0 !== '商品编码' && !/^[\\-–—\\s]+$/.test(c0)) {
                        hasData = true;
                        break;
                    }
                }
                if (onResults && !hasData) return 'loading';
                const captchaRoot = document.getElementById('captcha');
                if (captchaRoot) {
                    const style = window.getComputedStyle(captchaRoot);
                    const r = captchaRoot.getBoundingClientRect();
                    const shown = (r.width > 0 && r.height > 0)
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                    if (shown) {
                        const msgEl = document.getElementById('msg');
                        const msgText = (msgEl && msgEl.innerText) ? msgEl.innerText.trim() : '';
                        if (msgText.includes('验证通过') || msgText.includes('成功')) {
                            return 'verify_passed';
                        }
                        return 'captcha';
                    }
                }
                if (
                    text.includes('验证码')
                    || text.includes('拼图验证')
                    || text.includes('向右滑动')
                    || text.includes('请进行拼图验证')
                ) {
                    return 'captcha';
                }
                const layers = [...document.querySelectorAll('.layui-layer')];
                for (const layer of layers) {
                    const r = layer.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    const lt = layer.innerText || '';
                    if (
                        lt.includes('是否继续')
                        || lt.includes('查询时间较长')
                        || lt.includes('非近期数据')
                    ) {
                        return 'query_confirm';
                    }
                }
                if (text.includes('验证通过')) return 'verify_passed';
                if (hasData) return 'results';
                return null;
            }
            """
        )
    except PlaywrightError:
        return None


def _read_page_state(page: Page) -> str:
    for scope in _iter_scopes(page):
        state = _passive_state(scope)
        if state:
            return state
    return "idle"


def _query_confirm_visible(page: Page) -> bool:
    for scope in _iter_scopes(page):
        try:
            for marker in ("是否继续", "查询时间较长", "非近期数据"):
                loc = scope.get_by_text(marker, exact=False)
                if loc.count() > 0 and loc.first.is_visible(timeout=150):
                    return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _captcha_verified(scope: Page | Frame) -> bool:
    msg = read_captcha_msg(scope)
    if "验证通过" in msg or "成功" in msg:
        return True
    try:
        return bool(
            scope.evaluate(
                "() => (document.body?.innerText || '').includes('验证通过')"
            )
        )
    except PlaywrightError:
        return False


def _scan_context(context: BrowserContext, main_page: Page) -> tuple[str, Page]:
    priority = ("verify_passed", "captcha", "query_confirm", "loading", "results")
    hits: dict[str, Page] = {}
    for page in context.pages:
        cs = find_captcha_scope_in_page(page)
        if cs is not None:
            if _captcha_verified(cs.scope):
                hits.setdefault("verify_passed", page)
            else:
                hits.setdefault("captcha", page)
        if _query_confirm_visible(page):
            hits.setdefault("query_confirm", page)
        for scope in _iter_scopes(page):
            state = _passive_state(scope)
            if state and state not in hits:
                hits[state] = page
    for state in priority:
        if state in hits:
            return state, hits[state]
    return "idle", main_page


CAPTCHA_META_JS = """
() => {
  const root = document.getElementById('captcha');
  if (!root) return null;

  const visible = (el) => !!(el && el.getBoundingClientRect().width > 0);
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  };
  const canvasToDataUrl = (canvas) => {
    try {
      return canvas.toDataURL('image/png');
    } catch (e) {
      return '';
    }
  };

  const bgCanvas = root.querySelector('canvas:not(.block)') || root.querySelector('canvas');
  const puzzleCanvas = root.querySelector('canvas.block');
  if (!bgCanvas || !visible(bgCanvas)) return null;

  const handle = root.querySelector('.slider')
    || root.querySelector(':scope > div.sliderContainer .slider');
  if (!handle || !visible(handle)) return null;

  const track = root.querySelector('.sliderContainer') || handle.parentElement;
  const bgDataUrl = canvasToDataUrl(bgCanvas);
  if (!bgDataUrl) return null;

  return {
    bgDataUrl,
    bgNaturalWidth: bgCanvas.width,
    bgNaturalHeight: bgCanvas.height,
    bgBox: rect(bgCanvas),
    handleBox: rect(handle),
    trackBox: track ? rect(track) : rect(handle),
    puzzleDataUrl: puzzleCanvas ? canvasToDataUrl(puzzleCanvas) : null,
    offsetPx: 0,
  };
}
"""

# Note: offsetPx filled in Python via GACC_CAPTCHA_OFFSET_PX for locator path.

CAPTCHA_HANDLE = "#captcha .slider"
CAPTCHA_HANDLE_XPATH = "#captcha .slider"
CAPTCHA_TRACK_XPATH = "#captcha .sliderContainer"
CAPTCHA_BG_CANVAS = "#captcha canvas:not(.block)"
CAPTCHA_PUZZLE_CANVAS = "#captcha canvas.block"


def _box_from_playwright(box: dict | None) -> dict | None:
    if not box:
        return None
    return {
        "x": box["x"],
        "y": box["y"],
        "width": box["width"],
        "height": box["height"],
    }


def _extract_captcha_meta_locators(scope: Page | Frame) -> dict | None:
    root = scope.locator("#captcha")
    if root.count() == 0:
        return None
    try:
        root.first.wait_for(state="visible", timeout=3000)
    except PlaywrightTimeout:
        return None

    bg = scope.locator(CAPTCHA_BG_CANVAS)
    handle = scope.locator(CAPTCHA_HANDLE_XPATH)
    if bg.count() == 0:
        bg = scope.locator("#captcha canvas").first
    if bg.count() == 0 or handle.count() == 0:
        return None
    if not bg.first.is_visible(timeout=1000) or not handle.first.is_visible(timeout=1000):
        return None

    bg_data = bg.first.evaluate("c => c.toDataURL('image/png')")
    if not bg_data or bg_data == "data:,":
        png_bytes = bg.first.screenshot(type="png")
        bg_data = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    canvas_size = bg.first.evaluate("c => ({ w: c.width, h: c.height })")
    if not canvas_size.get("w"):
        png_bytes = bg.first.screenshot(type="png")
        import cv2
        import numpy as np

        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is not None:
            canvas_size = {"w": decoded.shape[1], "h": decoded.shape[0]}

    puzzle_data = None
    block_width = 62
    puzzle = scope.locator(CAPTCHA_PUZZLE_CANVAS)
    if puzzle.count() > 0 and puzzle.first.is_visible(timeout=300):
        puzzle_data = puzzle.first.evaluate("c => c.toDataURL('image/png')")
        block_size = puzzle.first.evaluate("c => ({ w: c.width, h: c.height })")
        block_width = int(block_size.get("w") or 62)

    handle_box = _box_from_playwright(handle.first.bounding_box())
    bg_box = _box_from_playwright(bg.first.bounding_box())
    if not handle_box or not bg_box:
        return None

    track = scope.locator(CAPTCHA_TRACK_XPATH)
    track_box = _box_from_playwright(track.first.bounding_box()) if track.count() else handle_box

    return {
        "bgDataUrl": bg_data,
        "bgNaturalWidth": int(canvas_size.get("w") or 0),
        "bgNaturalHeight": int(canvas_size.get("h") or 0),
        "bgBox": bg_box,
        "handleBox": handle_box,
        "trackBox": track_box or handle_box,
        "puzzleDataUrl": puzzle_data,
        "blockWidth": block_width,
        "offsetPx": GACC_CAPTCHA_OFFSET_PX,
    }


def _extract_captcha_meta_from_scope(cs: CaptchaScope) -> dict | None:
    try:
        locator_meta = _extract_captcha_meta_locators(cs.scope)
        if locator_meta:
            return locator_meta
    except PlaywrightError:
        pass
    try:
        meta = cs.scope.evaluate(CAPTCHA_META_JS)
        if meta and meta.get("bgDataUrl") and meta.get("handleBox"):
            meta["offsetPx"] = GACC_CAPTCHA_OFFSET_PX
            return meta
    except PlaywrightError:
        return None
    return None


def _extract_captcha_meta(page: Page) -> dict | None:
    cs = resolve_captcha_scope(page.context, page)
    return _extract_captcha_meta_from_scope(cs)


def _find_captcha_page(context: BrowserContext) -> Page | None:
    cs = find_captcha_scope(context)
    return cs.page if cs else None


def _resolve_captcha_scope(context: BrowserContext, hint: Page) -> CaptchaScope:
    return resolve_captcha_scope(context, hint)


def _click_query_confirm(page: Page) -> bool:
    for scope in _iter_scopes(page):
        try:
            has_dialog = (
                scope.locator("text=是否继续").count() > 0
                or scope.locator("text=查询时间较长").count() > 0
                or scope.locator("text=非近期数据").count() > 0
            )
            if not has_dialog:
                continue
            layer = scope.locator(".layui-layer-dialog, .layui-layer").first
            if layer.count() > 0 and not layer.is_visible(timeout=300):
                continue
            btn = scope.locator("a.layui-layer-btn0").first
            if btn.count() > 0 and btn.is_visible(timeout=300):
                btn.click(force=True, timeout=3000)
                page.wait_for_timeout(600)
                return True
            confirm = scope.get_by_role("button", name="确定")
            if confirm.count() > 0 and confirm.first.is_visible(timeout=300):
                confirm.first.click(force=True, timeout=3000)
                page.wait_for_timeout(600)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _click_captcha_pass_confirm(page: Page, cs: CaptchaScope | None = None) -> bool:
    """Click「确定」after slider shows 验证通过 — iframe or layui parent."""
    verified_scopes: list[Page | Frame] = []
    if cs is not None and _captcha_verified(cs.scope):
        verified_scopes.append(cs.scope)
    for scope in _iter_scopes(page):
        if scope in verified_scopes:
            continue
        if _captcha_verified(scope) or _passive_state(scope) == "verify_passed":
            verified_scopes.append(scope)
    if not verified_scopes:
        return False

    click_scopes: list[Page | Frame] = list(verified_scopes)
    click_scopes.append(page)

    selectors = (
        "button:has-text('确定')",
        "a:has-text('确定')",
        "input[type='button'][value='确定']",
        "input[type='submit'][value='确定']",
        "#captcha button:has-text('确定')",
        "#captcha a:has-text('确定')",
        "a.layui-layer-btn0",
        ".layui-layer-btn0",
        ".layui-layer-btn a",
    )
    for scope in click_scopes:
        for selector in selectors:
            try:
                btn = scope.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=400):
                    text = (btn.inner_text(timeout=500) or "").strip()
                    if text and "确定" not in text and selector not in (
                        "a.layui-layer-btn0",
                        ".layui-layer-btn0",
                    ):
                        continue
                    btn.click(force=True, timeout=3000)
                    page.wait_for_timeout(600)
                    return True
            except (PlaywrightTimeout, PlaywrightError):
                continue
    return False


def _click_verify_passed_confirm(page: Page) -> bool:
    cs = find_captcha_scope(page.context)
    return _click_captcha_pass_confirm(page, cs)


def _wait_captcha_dismissed(
    context: BrowserContext,
    page: Page,
    *,
    timeout_sec: float = 12.0,
    cs: CaptchaScope | None = None,
) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        ensure_browser_open(None)
        active = find_captcha_scope(context)
        if active is None:
            return True
        if _captcha_verified(active.scope):
            _click_captcha_pass_confirm(page, active)
        time.sleep(0.25)
    return find_captcha_scope(context) is None


def _click_captcha_confirm(cs: CaptchaScope) -> bool:
    return _click_captcha_pass_confirm(cs.page, cs)


def _reset_captcha(cs: CaptchaScope) -> bool:
    scope = cs.scope
    page = cs.page
    if _captcha_verified(scope):
        return False
    try:
        state = scope.evaluate(
            """
            () => {
              const slider = document.querySelector('.slider');
              const left = parseFloat(String(slider?.style.left || '0').replace('px', ''));
              const fail = document.querySelector('.sliderContainer')?.classList.contains('sliderContainer_fail');
              return { left: Number.isFinite(left) ? left : 0, fail: !!fail };
            }
            """
        )
    except PlaywrightError:
        state = {"left": 0, "fail": False}

    if not state.get("fail") and float(state.get("left") or 0) < 3:
        return False

    for selector in ("#refreshIcon", "#captcha .refreshIcon", "#captcha [class*='refresh']"):
        try:
            btn = scope.locator(selector).first
            if btn.count() > 0 and btn.is_visible(timeout=300):
                btn.click(timeout=2000)
                page.wait_for_timeout(900)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _wait_captcha_ready(cs: CaptchaScope, *, timeout_ms: int = 4000, closed: threading.Event | None = None) -> None:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        ensure_browser_open(closed)
        if read_slider_offset(cs.scope) < 3 and not captcha_failed(cs.scope):
            return
        abortable_sleep(0.15, closed)


def _click_captcha_refresh(cs: CaptchaScope) -> bool:
    scope = cs.scope
    page = cs.page
    for selector in ("#refreshIcon", "#captcha .refreshIcon", "#captcha [class*='refresh']"):
        try:
            btn = scope.locator(selector).first if selector.startswith("#captcha") else page.locator(selector).first
            if btn.count() > 0 and btn.is_visible(timeout=300):
                btn.click(timeout=2000)
                page.wait_for_timeout(600)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _focus_page(page: Page) -> None:
    try:
        page.bring_to_front()
    except PlaywrightError:
        pass


class ManualCaptchaProvider:
    """Wait for user to complete sliding puzzle in headed browser."""

    def __init__(
        self,
        *,
        timeout_sec: int = 180,
        on_status: Callable[[str], None] | None = None,
        abort_event: threading.Event | None = None,
    ) -> None:
        self.timeout_sec = timeout_sec
        self.on_status = on_status or (lambda _msg: None)
        self._abort = abort_event

    def _notify(self, message: str) -> None:
        self.on_status(message)

    def _pause(self, seconds: float) -> None:
        abortable_sleep(seconds, self._abort)

    def wait_until_passed(self, page: Page) -> None:
        self._notify("等待验证码或查询结果页出现…")
        deadline = time.time() + self.timeout_sec
        captcha_seen = False
        verify_confirm_clicked = False
        last_status_at = 0.0
        context = page.context

        while time.time() < deadline:
            ensure_browser_open(self._abort)
            try:
                state, active_page = _scan_context(context, page)

                if state in ("results", "loading"):
                    if _query_confirm_visible(active_page):
                        if _click_query_confirm(active_page):
                            self._notify("已确认继续查询…")
                            self._pause(1.0)
                        continue
                    self._notify(
                        "查询已提交，数据加载中…"
                        if state == "loading"
                        else "已进入结果页，等待数据加载…"
                    )
                    return

                if state == "captcha":
                    if not captcha_seen:
                        captcha_seen = True
                        self._notify(
                            "验证码已弹出：脚本已暂停所有自动点击，请手动拖动滑块。"
                            "（若感觉鼠标被干扰，请只在 Edge 窗口内操作）"
                        )
                    now = time.time()
                    if now - last_status_at >= 20:
                        self._notify("等待您手动完成滑块验证…")
                        last_status_at = now
                    self._pause(2.0)
                    continue

                if state == "query_confirm":
                    if _click_query_confirm(active_page):
                        self._notify("已确认继续查询…")
                        self._pause(1.0)
                        continue

                if state == "verify_passed" and not verify_confirm_clicked:
                    _focus_page(active_page)
                    if _click_verify_passed_confirm(active_page):
                        verify_confirm_clicked = True
                        self._notify("已点击「验证通过」确认…")
                        self._pause(1.0)
                        continue

            except BrowserClosedError:
                raise
            except PlaywrightError:
                ensure_browser_open(self._abort)
                self._pause(1.0)
                continue

            self._pause(1.0)

        ensure_browser_open(self._abort)
        final, _ = _scan_context(context, page)
        if final in ("results", "loading", "captcha"):
            if final == "captcha":
                raise TimeoutError(
                    f"验证码等待超时（{self.timeout_sec} 秒），请重试并确保在 Edge 窗口内拖动滑块"
                )
            return
        raise TimeoutError(f"验证码等待超时（{self.timeout_sec} 秒）")


class AutoSliderCaptchaProvider:
    """Solve slider puzzle with OpenCV + simulated drag; optional manual fallback."""

    def __init__(
        self,
        *,
        timeout_sec: int = GACC_CAPTCHA_TIMEOUT_SEC,
        max_attempts: int = GACC_CAPTCHA_AUTO_MAX_ATTEMPTS,
        fallback_manual: bool = GACC_CAPTCHA_FALLBACK_MANUAL,
        on_status: Callable[[str], None] | None = None,
        abort_event: threading.Event | None = None,
    ) -> None:
        self.timeout_sec = timeout_sec
        self.max_attempts = max_attempts
        self.fallback_manual = fallback_manual
        self.on_status = on_status or (lambda _msg: None)
        self._attempts_for_current = 0
        self._abort = abort_event

    def _notify(self, message: str) -> None:
        self.on_status(message)

    def _pause(self, seconds: float) -> None:
        abortable_sleep(seconds, self._abort)

    def wait_until_passed(self, page: Page) -> None:
        self._notify("等待验证码或查询结果页出现…")
        deadline = time.time() + self.timeout_sec
        context = page.context
        verify_confirm_clicked = False
        last_status_at = 0.0

        while time.time() < deadline:
            ensure_browser_open(self._abort)
            state, active_page = _scan_context(context, page)

            if state in ("results", "loading"):
                if _query_confirm_visible(active_page):
                    if _click_query_confirm(active_page):
                        self._notify("已确认继续查询…")
                        self._pause(0.8)
                    continue
                self._notify(
                    "查询已提交，数据加载中…"
                    if state == "loading"
                    else "已进入结果页，等待数据加载…"
                )
                return

            if state == "query_confirm":
                if _click_query_confirm(active_page):
                    self._notify("已确认继续查询…")
                    self._pause(0.8)
                continue

            if state == "verify_passed":
                cs = find_captcha_scope(context)
                _focus_page(active_page)
                if _click_captcha_pass_confirm(active_page, cs):
                    verify_confirm_clicked = True
                    self._notify("已点击「验证通过」确认…")
                    _wait_captcha_dismissed(context, active_page, cs=cs)
                    self._pause(0.5)
                elif not verify_confirm_clicked:
                    self._pause(0.5)
                continue

            if state == "captcha":
                cs = _resolve_captcha_scope(context, active_page)
                if _captcha_verified(cs.scope):
                    _focus_page(cs.page)
                    self._confirm_captcha_passed(cs, cs.page)
                    self._attempts_for_current = 0
                    self._pause(0.5)
                    continue
                _focus_page(cs.page)
                solved = self._try_auto_solve(cs)
                if solved:
                    self._attempts_for_current = 0
                    self._pause(0.8)
                    continue
                self._attempts_for_current += 1
                if self._attempts_for_current >= self.max_attempts:
                    if self.fallback_manual:
                        self._notify("自动滑块多次失败，切换为手动验证…")
                        remaining = max(int(deadline - time.time()), 30)
                        manual = ManualCaptchaProvider(
                            timeout_sec=remaining,
                            on_status=self.on_status,
                            abort_event=self._abort,
                        )
                        manual.wait_until_passed(page)
                        return
                    raise RuntimeError(
                        f"自动滑块验证失败（已尝试 {self.max_attempts} 次）"
                    )
                self._notify(
                    f"自动滑块未通过，刷新后重试（{self._attempts_for_current}/{self.max_attempts}）…"
                )
                _click_captcha_refresh(_resolve_captcha_scope(context, active_page))
                _wait_captcha_ready(_resolve_captcha_scope(context, active_page), closed=self._abort)
                self._pause(1.5)
                continue

            now = time.time()
            if now - last_status_at >= 15:
                self._notify("等待验证码或数据加载…")
                last_status_at = now
            self._pause(0.8)

        ensure_browser_open(self._abort)
        final, _ = _scan_context(context, page)
        if final in ("results", "loading"):
            return
        raise TimeoutError(f"验证码等待超时（{self.timeout_sec} 秒）")

    def _confirm_captcha_passed(self, cs: CaptchaScope, page: Page) -> bool:
        if _click_captcha_pass_confirm(page, cs):
            self._notify("已点击「确定」，继续查询…")
        else:
            self._notify("验证已通过，正在查找「确定」按钮…")
            _click_captcha_pass_confirm(page, cs)
        return _wait_captcha_dismissed(page.context, page, cs=cs)

    def _captcha_outcome(self, scope: Page | Frame, page: Page) -> str:
        """Return 'pass', 'fail', or 'pending'."""
        if _captcha_verified(scope):
            return "pass"
        if captcha_failed(scope):
            return "fail"
        state = _passive_state(scope if isinstance(scope, Frame) else page)
        if state == "verify_passed":
            return "pass"
        return "pending"

    def _wait_captcha_outcome(self, scope: Page | Frame, page: Page, *, rounds: int = 20) -> str:
        page.wait_for_timeout(800)
        outcome = self._captcha_outcome(scope, page)
        if outcome != "pending":
            return outcome
        for _ in range(rounds):
            ensure_browser_open(self._abort)
            outcome = self._captcha_outcome(scope, page)
            if outcome == "pass":
                return "pass"
            if outcome == "fail":
                return "fail"
            self._pause(0.3)
        return "pending"

    def _drag_to_target(
        self,
        cs: CaptchaScope,
        handle_loc,
        target: float,
        *,
        reset_first: bool = False,
    ) -> float:
        page = cs.page
        scope = cs.scope
        if reset_first:
            reset_slider_position(page, handle_loc, scope=scope)
            self._pause(0.35)
        left_before = read_slider_offset(scope)
        final_left = drag_captcha_handle(page, handle_loc, target, [], scope=scope)
        moved = final_left - left_before
        self._notify(f"滑块 offset={int(final_left)}px（目标 {int(target)}，移动 {int(moved)}px）")
        return final_left

    def _try_auto_solve(self, cs: CaptchaScope) -> bool:
        page = cs.page
        scope = cs.scope

        try:
            scope.locator("#captcha").first.wait_for(state="visible", timeout=8000)
        except PlaywrightTimeout:
            self._notify("等待 #captcha 验证码弹窗…")
            return False

        if _reset_captcha(cs):
            self._notify("已刷新验证码，重置滑块…")
            _wait_captcha_ready(cs, closed=self._abort)

        meta = _extract_captcha_meta_from_scope(cs)
        if not meta:
            diag = format_diagnostics(page.context, cs)
            self._notify(f"未识别到滑块元素 | {diag[:500]}")
            save_diagnostics(page.context, cs, out_path=Path("data/gacc_captcha_last_fail.json"))
            return False
        try:
            distance, gap_x, confidence = solve_from_meta(meta)
        except Exception as exc:
            self._notify(f"缺口识别失败：{exc}")
            return False

        layout = parse_layout(meta)
        track_travel = track_travel_from_layout(layout)
        handle_loc = scope.locator(CAPTCHA_HANDLE).first

        if distance < 8:
            self._notify(f"识别距离过短（{int(distance)}px），刷新验证码…")
            _click_captcha_refresh(cs)
            return False

        conf_pct = int(confidence * 100)
        self._notify(
            f"缺口≈{gap_x}px → 滑块目标 {distance:.1f}px（置信 {conf_pct}%）"
        )

        seen_targets: set[int] = set()
        targets: list[float] = []
        for t in build_initial_targets(distance, track_travel):
            ti = int(round(t))
            if ti not in seen_targets:
                seen_targets.add(ti)
                targets.append(t)

        idx = 0
        while idx < len(targets) and idx < MAX_TRIES_PER_CAPTCHA:
            target = targets[idx]
            if idx > 0:
                self._notify(
                    f"同图微调 → {int(target)}px（{idx}/{min(len(targets), MAX_TRIES_PER_CAPTCHA) - 1}）"
                )
            try:
                final_left = self._drag_to_target(
                    cs, handle_loc, target, reset_first=idx > 0
                )
            except (PlaywrightError, RuntimeError, ValueError) as exc:
                if idx == 0:
                    diag = format_diagnostics(page.context, cs)
                    self._notify(f"拖动失败：{exc} | {diag[:400]}")
                    save_diagnostics(
                        page.context,
                        cs,
                        out_path=Path("data/gacc_captcha_last_fail.json"),
                        extra={"error": str(exc), "distance": distance, "gap_x": gap_x},
                    )
                idx += 1
                continue

            outcome = self._wait_captcha_outcome(scope, page)
            if outcome == "pass":
                self._notify("拼图验证通过")
                self._confirm_captcha_passed(cs, page)
                return True
            if outcome == "fail":
                block_left = read_block_left(scope)
                if block_left > 0:
                    landed = block_left_to_slider(
                        block_left,
                        bg_width=layout.bg_width or int(meta.get("bgNaturalWidth") or 310),
                        block_width=layout.block_width,
                        track_width=layout.track_width or layout.bg_box_width,
                        handle_width=layout.handle_width,
                    )
                    if landed > 0:
                        expand_targets_from_landing(
                            targets, seen_targets, landed, track_travel
                        )
                elif final_left > 0:
                    expand_targets_from_landing(
                        targets, seen_targets, final_left, track_travel
                    )
            idx += 1

        self._notify("拼图未对齐，将刷新换图重试…")
        return False


def create_captcha_provider(
    *,
    timeout_sec: int = GACC_CAPTCHA_TIMEOUT_SEC,
    on_status: Callable[[str], None] | None = None,
    abort_event: threading.Event | None = None,
) -> CaptchaProvider:
    if GACC_CAPTCHA_AUTO:
        return AutoSliderCaptchaProvider(
            timeout_sec=timeout_sec,
            on_status=on_status,
            abort_event=abort_event,
        )
    return ManualCaptchaProvider(
        timeout_sec=timeout_sec,
        on_status=on_status,
        abort_event=abort_event,
    )
