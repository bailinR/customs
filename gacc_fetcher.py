"""Playwright fetcher for stats.customs.gov.cn."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import (
    Error as PlaywrightError,
    Frame,
    Page,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

from config import (
    GACC_BASE_URL,
    GACC_BROWSER_CHANNEL,
    GACC_BROWSER_HEADLESS,
    GACC_CAPTCHA_TIMEOUT_SEC,
    GACC_DOWNLOAD_DIR,
    GACC_LOAD_TIMEOUT_SEC,
)
from gacc_browser_watch import (
    BrowserClosedError,
    attach_browser_close_watch,
    ensure_browser_open,
    guard_playwright,
)
from gacc_captcha import CaptchaProvider, create_captcha_provider, _read_page_state
from gacc_models import (
    CURRENCY_LABELS,
    CURRENCY_RADIO_VALUES,
    DEFAULT_OUTPUT_FIELDS,
    FIELD_SELECT_IDS,
    FLOW_LABELS,
    FLOW_RADIO_VALUES,
    GaccQueryParams,
    OUTPUT_FIELD_OPTIONS,
)

StatusCallback = Callable[[str], None]

UPGRADE_MARKERS = ("系统升级", "升级中", "维护中", "网站维护")
NAV_LABELS = ("数据查询", "在线查询", "统计查询")

FIELD_LABEL_BY_VALUE = {opt["value"]: opt["label"] for opt in OUTPUT_FIELD_OPTIONS}

EXPORT_XPATH = "xpath=//*[@id='downLoad']/span"
EXPORT_SELECTOR = "#downLoad span"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
)


def _entry_url() -> str:
    return GACC_BASE_URL.rstrip("/") + "/"


def _launch_kwargs() -> dict:
    kwargs: dict = {
        "headless": GACC_BROWSER_HEADLESS,
        # slow_mo 会在 headed 模式下干扰用户手动拖滑块，必须关闭
        "args": ["--ignore-certificate-errors", "--disable-blink-features=AutomationControlled"],
    }
    if GACC_BROWSER_CHANNEL:
        kwargs["channel"] = GACC_BROWSER_CHANNEL
    return kwargs


def _find_form_frame(page: Page) -> Frame | None:
    for frame in page.frames:
        try:
            if frame.locator("#outerField1").count() > 0:
                return frame
        except PlaywrightError:
            continue
    return None


def _wait_form_frame(page: Page, on_status: StatusCallback, *, timeout_sec: int = 90) -> Frame:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        frame = _find_form_frame(page)
        if frame is not None:
            try:
                frame.locator("#outerField1").wait_for(state="visible", timeout=3000)
                frame.wait_for_function(
                    """
                    () => {
                        const el = document.getElementById('outerField1');
                        const currency = document.querySelector('input[name="currencyType"]');
                        return Boolean(el && currency && typeof selectField === 'function');
                    }
                    """,
                    timeout=15_000,
                )
                page.wait_for_timeout(800)
                return frame
            except (PlaywrightTimeout, PlaywrightError):
                pass
        elapsed = int(timeout_sec - (deadline - time.time()))
        if elapsed > 0 and elapsed % 10 == 0:
            on_status(f"等待查询表单加载…（{elapsed}s）")
        page.wait_for_timeout(1000)
    raise RuntimeError("未找到查询表单（outerField1），页面可能仍在升级跳转中")


def _safe_visible(page: Page, text: str) -> bool:
    try:
        return page.get_by_text(text, exact=False).first.is_visible(timeout=1200)
    except (PlaywrightTimeout, PlaywrightError):
        return False


def _upgrade_message(page: Page) -> str | None:
    for marker in UPGRADE_MARKERS:
        if _safe_visible(page, marker):
            return marker
    return None


def _iter_scopes(page: Page):
    yield page
    for frame in page.frames:
        if frame != page.main_frame:
            yield frame


def _scope_visible(scope: Page | Frame, selector: str, *, timeout_ms: int = 500) -> bool:
    try:
        loc = scope.locator(selector)
        return loc.count() > 0 and loc.first.is_visible(timeout=timeout_ms)
    except (PlaywrightTimeout, PlaywrightError):
        return False


def _find_frame_with(page: Page, selector: str) -> Page | Frame | None:
    for scope in _iter_scopes(page):
        try:
            if scope.locator(selector).count() > 0:
                return scope
        except PlaywrightError:
            continue
    return None


def _find_results_context(page: Page) -> Page | Frame:
    ctx = _find_frame_with(page, "#downLoad")
    if ctx is not None:
        return ctx
    ctx = _find_form_frame(page)
    if ctx is not None:
        return ctx
    return page


_LOADING_JS = """
() => {
    const text = document.body?.innerText || '';
    if (text.includes('数据加载中')) return true;
    const img = document.querySelector(
        'img[src*="loadinge"], img[src*="loading"]'
    );
    if (img) {
        const style = window.getComputedStyle(img);
        if (style.display !== 'none' && style.visibility !== 'hidden' && img.offsetParent !== null) {
            return true;
        }
    }
    return false;
}
"""

_RESULTS_PENDING_JS = """
() => {
    const dl = document.getElementById('downLoad');
    if (!dl || dl.offsetParent === null) return false;
    const text = document.body?.innerText || '';
    if (!text.includes('商品编码')) return false;
    const rows = document.querySelectorAll('table tbody tr');
    for (const row of rows) {
        const t = (row.innerText || '').replace(/\\s+/g, ' ').trim();
        if (!t || t.includes('数据加载中')) continue;
        const cells = row.querySelectorAll('td');
        if (cells.length < 2) continue;
        const c0 = (cells[0].innerText || '').trim();
        if (c0 && c0 !== '商品编码' && !/^[\\-–—\\s]+$/.test(c0)) return false;
    }
    return true;
}
"""

_DATA_ROWS_JS = """
() => {
    const rows = document.querySelectorAll('table tbody tr');
    for (const row of rows) {
        const t = (row.innerText || '').replace(/\\s+/g, ' ').trim();
        if (!t || t.includes('数据加载中') || t.includes('请稍等')) continue;
        const cells = row.querySelectorAll('td');
        if (cells.length < 2) continue;
        const c0 = (cells[0].innerText || '').trim();
        if (c0 && c0 !== '商品编码' && !/^[\\-–—\\s]+$/.test(c0)) return true;
    }
    return false;
}
"""


def _scope_eval_bool(scope: Page | Frame, script: str) -> bool:
    try:
        return bool(scope.evaluate(script))
    except PlaywrightError:
        return False


def _loading_visible(page: Page) -> bool:
    for scope in _iter_scopes(page):
        if _scope_eval_bool(scope, _LOADING_JS):
            return True
    return False


def _results_pending(page: Page) -> bool:
    """结果页已出表头/导出按钮，但 tbody 仍无数据（加载文案可能已消失）。"""
    for scope in _iter_scopes(page):
        if _scope_eval_bool(scope, _RESULTS_PENDING_JS):
            return True
    return False


def _still_waiting_for_data(page: Page) -> bool:
    return _loading_visible(page) or _results_pending(page)


def _wait_phase_label(page: Page) -> str:
    if _loading_visible(page):
        return "检测到「数据加载中」，请稍候…"
    if _results_pending(page):
        return "结果页已打开，表格数据渲染中（请勿手动点导出）…"
    return "等待查询结果…"


def _has_data_rows(page: Page) -> bool:
    for scope in _iter_scopes(page):
        if _scope_eval_bool(scope, _DATA_ROWS_JS):
            return True
    return False


def _timeout_error_visible(page: Page) -> bool:
    return _safe_visible(page, "访问超时") or _safe_visible(page, "数据无法导出")


def _dismiss_timeout_modal(page: Page, on_status: StatusCallback) -> None:
    if not _timeout_error_visible(page):
        return
    on_status("检测到「访问超时，数据无法导出」，关闭提示并继续等待…")
    _click_layer_confirm(page, on_status)


def _captcha_visible(page: Page) -> bool:
    try:
        if page.locator("#captcha").count() > 0 and page.locator("#captcha").first.is_visible(timeout=200):
            return True
    except (PlaywrightTimeout, PlaywrightError):
        pass
    for scope in _iter_scopes(page):
        for marker in ("验证码", "滑动验证", "拖动"):
            try:
                loc = scope.get_by_text(marker, exact=False)
                if loc.count() > 0 and loc.first.is_visible(timeout=200):
                    return True
            except (PlaywrightTimeout, PlaywrightError):
                continue
        try:
            if scope.locator('[id*="layui-layer-iframe"]').count() > 0:
                return True
        except PlaywrightError:
            continue
    return False


def _export_ready(page: Page) -> bool:
    if _still_waiting_for_data(page):
        return False
    if _timeout_error_visible(page):
        return False
    if not _has_data_rows(page):
        return False
    ctx = _find_results_context(page)
    try:
        export = ctx.locator("#downLoad")
        if export.count() == 0:
            export = ctx.locator(EXPORT_SELECTOR)
        if export.count() == 0:
            export = ctx.locator(EXPORT_XPATH)
        return export.count() > 0 and export.first.is_visible(timeout=500)
    except (PlaywrightTimeout, PlaywrightError):
        return False


def _click_export_confirm(page: Page, on_status: StatusCallback) -> bool:
    """点击「确认导出?」对话框的确定。"""
    for scope in _iter_scopes(page):
        try:
            if scope.get_by_text("确认导出", exact=False).count() == 0:
                continue
            on_status("点击「确认导出」…")
            btn = scope.locator("a.layui-layer-btn0").first
            if btn.count() > 0 and btn.is_visible(timeout=1000):
                btn.click(timeout=5000)
                on_status("已确认导出")
                page.wait_for_timeout(600)
                return True
            confirm = scope.get_by_role("button", name="确定")
            if confirm.count() > 0 and confirm.first.is_visible(timeout=1000):
                confirm.first.click(timeout=5000)
                on_status("已确认导出")
                page.wait_for_timeout(600)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _click_layer_confirm(page: Page, on_status: StatusCallback) -> bool:
    """点击 layui 弹窗「确定」（查询耗时确认、导出确认等）。"""
    for scope in (page, *page.frames):
        try:
            has_dialog = (
                scope.locator("text=是否继续").count() > 0
                or scope.locator("text=查询时间较长").count() > 0
                or scope.locator("text=非近期数据").count() > 0
                or scope.locator("text=验证通过").count() > 0
                or scope.locator("text=确认导出").count() > 0
                or scope.locator("text=访问超时").count() > 0
                or scope.locator("text=数据无法导出").count() > 0
            )
            if not has_dialog:
                continue
            btn = scope.locator("a.layui-layer-btn0").first
            if btn.count() > 0 and btn.is_visible(timeout=500):
                btn.click(force=True)
                on_status("已点击确认框「确定」")
                page.wait_for_timeout(800)
                return True
            confirm = scope.get_by_role("button", name="确定")
            if confirm.count() > 0 and confirm.first.is_visible(timeout=500):
                confirm.first.click(force=True)
                on_status("已点击确认框「确定」")
                page.wait_for_timeout(800)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _dismiss_query_confirm(page: Page, on_status: StatusCallback, *, timeout_sec: int = 30) -> None:
    if _read_page_state(page) == "captcha":
        return
    on_status("等待查询确认框…")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _click_layer_confirm(page, on_status):
            return
        if _captcha_visible(page) or _loading_visible(page) or _export_ready(page):
            return
        page.wait_for_timeout(400)


def _open_entry_page(page: Page, on_status: StatusCallback) -> Frame:
    url = _entry_url()
    on_status(f"正在打开 {url} …")

    try:
        page.goto(url, wait_until="load", timeout=90_000)
    except PlaywrightError as exc:
        raise RuntimeError(f"无法打开 {url}：{exc}") from exc

    frame = _find_form_frame(page)
    if frame is not None:
        return frame

    upgrade = _upgrade_message(page)
    if upgrade:
        on_status(f"检测到「{upgrade}」，等待自动跳转到查询页…")

    try:
        return _wait_form_frame(page, on_status, timeout_sec=90)
    except RuntimeError:
        pass

    for label in NAV_LABELS:
        link = page.get_by_role("link", name=label)
        if link.count() == 0:
            continue
        try:
            on_status(f"尝试进入「{label}」…")
            link.first.click(timeout=5000)
            page.wait_for_load_state("load", timeout=45_000)
            return _wait_form_frame(page, on_status, timeout_sec=60)
        except (PlaywrightTimeout, PlaywrightError, RuntimeError):
            continue

    upgrade_note = f"页面提示「{upgrade}」。" if upgrade else ""
    raise RuntimeError(
        "未进入查询表单页（未找到 outerField1）。"
        f"{upgrade_note}请手动打开 http://stats.customs.gov.cn/ 确认。"
    )


def _click_named_radio(frame: Frame, *, name: str, values: tuple[str, ...]) -> bool:
    for value in values:
        radio = frame.locator(f'input[type="radio"][name="{name}"][value="{value}"]')
        if radio.count() > 0:
            radio.first.check(force=True)
            return True
    return False


def _set_flow_type(frame: Frame, flow_type: str) -> None:
    value = FLOW_RADIO_VALUES[flow_type]
    if _click_named_radio(frame, name="iEType", values=(value,)):
        frame.wait_for_timeout(200)
        return

    label = FLOW_LABELS[flow_type]
    clicked = frame.evaluate(
        """
        (label) => {
            const radios = document.querySelectorAll('input[type=radio][name="iEType"]');
            for (const radio of radios) {
                const cell = radio.closest('label, td, span') || radio.parentElement;
                if ((cell?.innerText || '').includes(label)) {
                    radio.click();
                    radio.checked = true;
                    return true;
                }
            }
            return false;
        }
        """,
        label,
    )
    if not clicked:
        frame.get_by_text(label, exact=True).first.click(force=True)
    frame.wait_for_timeout(200)


def _set_currency(frame: Frame, currency: str) -> None:
    values = CURRENCY_RADIO_VALUES[currency]
    if _click_named_radio(frame, name="currencyType", values=values):
        frame.wait_for_timeout(200)
        return

    label = CURRENCY_LABELS[currency]
    clicked = frame.evaluate(
        """
        (label) => {
            const radios = document.querySelectorAll('input[type=radio][name="currencyType"]');
            for (const radio of radios) {
                const cell = radio.closest('label, td, span') || radio.parentElement;
                if ((cell?.innerText || '').includes(label)) {
                    radio.click();
                    radio.checked = true;
                    return true;
                }
            }
            return false;
        }
        """,
        label,
    )
    if not clicked:
        frame.get_by_text(label, exact=True).first.click(force=True)
    frame.wait_for_timeout(200)


def _set_outer_field(frame: Frame, field_id: str, value: str) -> None:
    """在 iframe 内设置 outerField 并触发 selectField()。"""
    locator = frame.locator(f"#{field_id}")
    locator.wait_for(state="visible", timeout=30_000)

    label = FIELD_LABEL_BY_VALUE.get(value, value)
    result = frame.evaluate(
        """
        ([id, val]) => {
            const el = document.getElementById(id);
            if (!el) return { ok: false, reason: 'missing element' };
            el.value = val;
            const fn = window.selectField;
            if (typeof fn === 'function') {
                fn(el, val, id);
            } else {
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return { ok: true, value: el.value };
        }
        """,
        [field_id, value],
    )

    actual = locator.input_value()
    if actual != value:
        try:
            locator.select_option(value=value, force=True)
        except PlaywrightError:
            locator.select_option(label=label, force=True)
        frame.evaluate(
            """
            ([id, val]) => {
                const el = document.getElementById(id);
                if (!el) return;
                el.value = val;
                const fn = window.selectField;
                if (typeof fn === 'function') fn(el, val, id);
            }
            """,
            [field_id, value],
        )

    actual = locator.input_value()
    if actual != value:
        raise RuntimeError(
            f"输出字段 {field_id} 未能选中 {value}（当前 {actual or '空'}）"
        )
    frame.wait_for_timeout(500)


def _resolve_time_selectors(frame: Frame) -> tuple[str, str, str] | None:
    for year_id, start_id, end_id in (
        ("year", "startMonth", "endMonth"),
        ("yearSelect", "startMonthSelect", "endMonthSelect"),
    ):
        year = frame.locator(f"#{year_id}")
        start = frame.locator(f"#{start_id}")
        end = frame.locator(f"#{end_id}")
        if year.count() > 0 and start.count() > 0 and end.count() > 0:
            return year_id, start_id, end_id
    return None


def _read_time_range(frame: Frame) -> dict[str, str]:
    ids = _resolve_time_selectors(frame)
    if ids is None:
        return {}
    year_id, start_id, end_id = ids
    return frame.evaluate(
        """
        ([yearId, startId, endId]) => {
            const year = document.getElementById(yearId);
            const start = document.getElementById(startId);
            const end = document.getElementById(endId);
            return {
                year: year?.value || '',
                start: start?.value || '',
                end: end?.value || '',
            };
        }
        """,
        [year_id, start_id, end_id],
    )


def _set_select_value(frame: Frame, select_id: str, target: str | int) -> str:
    """设置 select 并触发 change；返回选中 value。"""
    want = str(target)
    result = frame.evaluate(
        """
        ([id, want]) => {
            const el = document.getElementById(id);
            if (!el) return { ok: false, value: '' };
            const pick = String(want);
            const candidates = [pick, pick.padStart(2, '0')];
            let matched = null;
            for (const opt of el.options) {
                const v = String(opt.value ?? '').trim();
                const t = String(opt.text ?? '').trim();
                if (candidates.includes(v) || v === pick || t === pick || t === `${pick}月`) {
                    matched = v;
                    break;
                }
            }
            if (matched == null) return { ok: false, value: el.value || '' };
            el.value = matched;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof el.onchange === 'function') el.onchange();
            return { ok: true, value: el.value || '' };
        }
        """,
        [select_id, want],
    )
    actual = str(result.get("value") or "")
    if not result.get("ok") or actual not in {want, want.zfill(2)}:
        locator = frame.locator(f"#{select_id}")
        for candidate in (want, want.zfill(2), f"{want}月"):
            try:
                locator.select_option(value=candidate, timeout=1500)
            except PlaywrightError:
                try:
                    locator.select_option(label=candidate, timeout=1500)
                except PlaywrightError:
                    continue
            actual = locator.input_value()
            if actual in {want, want.zfill(2)}:
                break
    frame.wait_for_timeout(150)
    return actual


def _fill_time_range(frame: Frame, params: GaccQueryParams) -> None:
    ids = _resolve_time_selectors(frame)
    if ids is None:
        time_selects = frame.locator("select:not([id^='outerField'])")
        if time_selects.count() >= 3:
            year_text = str(params.year)
            start_text = str(params.month_start)
            end_text = str(params.month_end)
            time_selects.nth(0).select_option(label=year_text)
            frame.wait_for_timeout(400)
            time_selects.nth(1).select_option(label=start_text)
            time_selects.nth(2).select_option(label=end_text)
            frame.wait_for_timeout(200)
            return
        raise RuntimeError("未找到进出口起止时间的下拉框")

    year_id, start_id, end_id = ids
    _set_select_value(frame, year_id, params.year)
    frame.wait_for_timeout(500)
    _set_select_value(frame, start_id, params.month_start)
    _set_select_value(frame, end_id, params.month_end)
    frame.wait_for_timeout(200)


def _time_range_matches(frame: Frame, params: GaccQueryParams) -> bool:
    current = _read_time_range(frame)
    if not current:
        return False

    def norm(value: str) -> int:
        text = str(value or "").strip().rstrip("月")
        if not text or not text.isdigit():
            return 0
        return int(text)

    year_ok = norm(current.get("year", "")) == params.year
    start_ok = norm(current.get("start", "")) == params.month_start
    end_ok = norm(current.get("end", "")) == params.month_end
    return year_ok and start_ok and end_ok


def _ensure_time_range(
    frame: Frame, params: GaccQueryParams, on_status: StatusCallback, *, attempts: int = 3
) -> None:
    for attempt in range(1, attempts + 1):
        if _time_range_matches(frame, params):
            return
        if attempt == 1:
            on_status("设置进出口起止时间…")
        else:
            on_status(f"月份被页面重置，第 {attempt} 次重新设置…")
        _fill_time_range(frame, params)
    current = _read_time_range(frame)
    raise RuntimeError(
        "进出口起止时间未能保持为 "
        f"{params.year}年{params.month_start}-{params.month_end}月"
        f"（当前 {current.get('year', '?')}年"
        f"{current.get('start', '?')}-{current.get('end', '?')}月）"
    )


def _fill_output_fields(
    frame: Frame, values: list[str], on_status: StatusCallback
) -> None:
    fields = (values + ["", "", "", ""])[:4]
    for idx, (field_id, value) in enumerate(zip(FIELD_SELECT_IDS, fields, strict=False), start=1):
        if not value:
            continue
        on_status(f"设置输出字段第 {idx} 组：{FIELD_LABEL_BY_VALUE.get(value, value)}")
        _set_outer_field(frame, field_id, value)


def _verify_form(frame: Frame, params: GaccQueryParams) -> None:
    currency_values = CURRENCY_RADIO_VALUES[params.currency]
    checked = frame.evaluate(
        """
        (values) => {
            const radios = document.querySelectorAll('input[name="currencyType"]');
            for (const radio of radios) {
                if (radio.checked) return radio.value;
            }
            return '';
        }
        """,
        list(currency_values),
    )
    if checked and checked not in currency_values:
        raise RuntimeError(
            f"币制未选中（期望 {params.currency}，当前 radio value={checked or '空'}）"
        )

    for field_id, value in zip(FIELD_SELECT_IDS, params.output_fields, strict=False):
        if not value:
            continue
        actual = frame.locator(f"#{field_id}").input_value()
        if actual != value:
            raise RuntimeError(
                f"输出字段 {field_id} 未选中（期望 {value}，实际 {actual or '空'}）"
            )


def _fill_query_form(
    page: Page, frame: Frame, params: GaccQueryParams, on_status: StatusCallback
) -> None:
    on_status("设置进出口类型与币制…")
    _set_flow_type(frame, params.flow_type)
    _set_currency(frame, params.currency)

    if params.split_by_month:
        month_flag = frame.locator('input[name="monthFlag"][value="1"]')
        if month_flag.count() > 0:
            month_flag.first.check(force=True)
        else:
            checkbox = frame.get_by_label("分月展示")
            if checkbox.count() > 0:
                checkbox.first.check()
            else:
                frame.locator("text=分月展示").first.click(force=True)

    fields = params.output_fields or list(DEFAULT_OUTPUT_FIELDS)
    _fill_output_fields(frame, fields, on_status)

    # selectField() 会重置月份为 1，必须在输出字段之后再设起止时间
    _ensure_time_range(frame, params, on_status)

    _verify_form(frame, params)
    on_status("表单已填写完成，准备提交查询…")


def _wait_results_loaded(
    page: Page,
    on_status: StatusCallback,
    *,
    timeout_sec: int | None = None,
    abort_event=None,
) -> None:
    timeout = timeout_sec or GACC_LOAD_TIMEOUT_SEC
    on_status("等待查询结果加载完成，请勿关闭浏览器…")

    deadline = time.time() + timeout
    last_notice = 0
    stable_ready = 0

    while time.time() < deadline:
        ensure_browser_open(abort_event)
        _dismiss_timeout_modal(page, on_status)

        if _still_waiting_for_data(page):
            stable_ready = 0
        elif _export_ready(page):
            stable_ready += 1
            if stable_ready >= 3:
                on_status("数据已加载完成，准备导出…")
                try:
                    page.wait_for_timeout(500)
                except PlaywrightError as exc:
                    guard_playwright(abort_event, exc)
                return
        else:
            stable_ready = 0

        elapsed = int(time.time() - (deadline - timeout))
        if elapsed - last_notice >= 10:
            on_status(f"{_wait_phase_label(page)}（已等待 {elapsed}s）")
            last_notice = elapsed
        try:
            page.wait_for_timeout(1000)
        except PlaywrightError as exc:
            guard_playwright(abort_event, exc)

    ensure_browser_open(abort_event)

    if _export_ready(page):
        return

    if _timeout_error_visible(page):
        raise RuntimeError(
            "海关站返回「访问超时，数据无法导出」。"
            "请缩小查询范围（如缩短月份）后重试。"
        )

    raise RuntimeError(f"等待结果超时（{timeout}s），数据可能仍在加载")


def _submit_query(frame: Frame, params: GaccQueryParams, on_status: StatusCallback) -> None:
    _ensure_time_range(frame, params, on_status, attempts=2)
    search = frame.locator("#doSearch")
    if search.count() > 0:
        search.first.click(force=True)
        return
    button = frame.get_by_role("button", name="查询")
    if button.count() == 0:
        button = frame.get_by_text("查询", exact=True)
    button.first.click(force=True)


def _wait_post_submit(page: Page, on_status: StatusCallback, provider: CaptchaProvider) -> None:
    """提交查询后：确认框 → 验证码（可选，期间完全放手）→ 加载。"""
    on_status("已提交查询，等待验证码或数据加载…")
    _dismiss_query_confirm(page, on_status, timeout_sec=30)
    try:
        provider.wait_until_passed(page)
    except TimeoutError as exc:
        state = _read_page_state(page)
        if state in ("loading", "results"):
            on_status("验证码等待结束，继续等待数据…")
        else:
            raise RuntimeError(str(exc)) from exc
    _dismiss_query_confirm(page, on_status, timeout_sec=10)


def _download_export(
    page: Page,
    target: Path,
    on_status: StatusCallback,
    *,
    abort_event=None,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, 4):
        ensure_browser_open(abort_event)
        if not _export_ready(page):
            on_status(f"导出前检查：数据尚未就绪（第 {attempt} 次等待）…")
            _wait_results_loaded(page, on_status, abort_event=abort_event)

        if _still_waiting_for_data(page) or not _has_data_rows(page):
            raise RuntimeError(
                "表格尚无数据，已阻止导出。"
                "请勿手动点击「导出数据」，等待脚本自动处理。"
            )

        on_status("正在导出 CSV…")
        ctx = _find_results_context(page)
        export_btn = ctx.locator(EXPORT_SELECTOR)
        if export_btn.count() == 0:
            export_btn = ctx.locator(EXPORT_XPATH)
        if export_btn.count() == 0:
            export_btn = ctx.locator("#downLoad")
        if export_btn.count() == 0:
            export_btn = ctx.get_by_text("导出数据", exact=True)
        if export_btn.count() == 0:
            raise RuntimeError("结果页未找到「导出数据」按钮（#downLoad）")

        try:
            with page.expect_download(timeout=120_000) as download_info:
                export_btn.first.click(timeout=5000)
                deadline = time.time() + 15
                while time.time() < deadline:
                    ensure_browser_open(abort_event)
                    if _timeout_error_visible(page):
                        break
                    if _click_export_confirm(page, on_status):
                        break
                    try:
                        page.wait_for_timeout(400)
                    except PlaywrightError as exc:
                        guard_playwright(abort_event, exc)
                if _timeout_error_visible(page):
                    _dismiss_timeout_modal(page, on_status)
                    on_status("导出被拒绝（数据未加载完），继续等待后重试…")
                    _wait_results_loaded(page, on_status, abort_event=abort_event)
                    continue
            download = download_info.value
            saved = target.resolve()
            download.save_as(str(target))
            on_status(f"CSV 已保存至 {saved}")
            return target
        except PlaywrightTimeout:
            if _timeout_error_visible(page):
                _dismiss_timeout_modal(page, on_status)
                on_status("导出超时，数据可能仍在渲染，继续等待…")
                _wait_results_loaded(page, on_status, abort_event=abort_event)
                continue
            break

    on_status("未触发下载，尝试调用 downLoad() 或解析表格…")
    ctx = _find_results_context(page)
    if not _export_ready(page):
        raise RuntimeError("无法导出：表格数据未加载完成")

    try:
        with page.expect_download(timeout=60_000) as download_info:
            ctx.evaluate(
                """
                () => {
                    if (typeof downLoad === 'function') {
                        downLoad();
                        return true;
                    }
                    const el = document.getElementById('downLoad');
                    if (el) { el.click(); return true; }
                    return false;
                }
                """
            )
            deadline = time.time() + 15
            while time.time() < deadline:
                if _click_export_confirm(page, on_status):
                    break
                if _timeout_error_visible(page):
                    break
                page.wait_for_timeout(400)
            if _timeout_error_visible(page):
                _dismiss_timeout_modal(page, on_status)
                raise RuntimeError("海关站返回「访问超时，数据无法导出」")
        download = download_info.value
        saved = target.resolve()
        download.save_as(str(target))
        on_status(f"CSV 已保存至 {saved}")
        return target
    except PlaywrightTimeout:
        return _save_html_table(page, target)


def _save_html_table(page: Page, target: Path) -> Path:
    import pandas as pd

    tables = page.locator("table")
    if tables.count() == 0:
        raise RuntimeError("无法导出或解析结果表格")
    html = tables.first.evaluate("el => el.outerHTML")
    df = pd.read_html(html)[0]
    csv_path = target.with_suffix(".csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def fetch_gacc_csv(
    params: GaccQueryParams,
    *,
    job_id: str,
    on_status: StatusCallback | None = None,
    captcha_provider: CaptchaProvider | None = None,
) -> Path:
    notify = on_status or (lambda _msg: None)
    download_dir = Path(GACC_DOWNLOAD_DIR)
    download_dir.mkdir(parents=True, exist_ok=True)
    target = download_dir / f"gacc_{job_id}.csv"

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(**_launch_kwargs())
    context = browser.new_context(
        ignore_https_errors=True,
        locale="zh-CN",
        user_agent=USER_AGENT,
        accept_downloads=True,
    )
    page = context.new_page()
    closed = attach_browser_close_watch(browser, context, page)

    provider = captcha_provider or create_captcha_provider(
        timeout_sec=GACC_CAPTCHA_TIMEOUT_SEC,
        on_status=notify,
        abort_event=closed,
    )

    try:
        form_frame = _open_entry_page(page, notify)
        _fill_query_form(page, form_frame, params, notify)
        _submit_query(form_frame, params, notify)
        _wait_post_submit(page, notify, provider)
        _wait_results_loaded(page, notify, abort_event=closed)
        return _download_export(page, target, notify, abort_event=closed)
    except BrowserClosedError:
        notify("用户已关闭浏览器，采集已中止")
        raise
    except PlaywrightError as exc:
        guard_playwright(closed, exc)
        raise
    finally:
        try:
            if browser.is_connected():
                context.close()
        except PlaywrightError:
            pass
        try:
            if browser.is_connected():
                browser.close()
        except PlaywrightError:
            pass
        playwright.stop()
