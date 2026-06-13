"""Dump outerField options from stats.customs.gov.cn (iframe-aware)."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
)


def find_form_frame(page):
    for frame in page.frames:
        try:
            if frame.locator("#outerField1").count() > 0:
                return frame
        except Exception:
            continue
    return None


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="msedge",
            slow_mo=100,
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(
            ignore_https_errors=True,
            locale="zh-CN",
            user_agent=USER_AGENT,
        )
        page = context.new_page()
        page.goto("http://stats.customs.gov.cn/", wait_until="load", timeout=90000)

        frame = None
        for i in range(90):
            frame = find_form_frame(page)
            if frame:
                print(f"form frame found at {i}s: {frame.url}")
                break
            if i % 10 == 9:
                print(f"waiting {i + 1}s frames={len(page.frames)} url={page.url}")
            page.wait_for_timeout(1000)

        if frame is None:
            page.screenshot(path=str(OUT / "gacc_probe_fail.png"), full_page=True)
            print("no form frame")
            browser.close()
            return

        info = frame.evaluate(
            """
            () => {
                const fields = ['outerField1','outerField2','outerField3','outerField4'];
                const selects = fields.map(id => {
                    const el = document.getElementById(id);
                    if (!el) return { id, missing: true };
                    return {
                        id,
                        value: el.value,
                        options: Array.from(el.options).map(o => ({
                            value: o.value,
                            text: o.text.trim(),
                        })),
                    };
                });
                const currency = Array.from(
                    document.querySelectorAll('input[name="currencyType"]')
                ).map(r => ({ value: r.value, checked: r.checked }));
                return { selects, currency, hasSelectField: typeof selectField === 'function' };
            }
            """
        )
        out_path = OUT / "gacc_form_dump.json"
        out_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print("saved", out_path)
        print(json.dumps(info, ensure_ascii=False, indent=2))

        frame.locator('input[name="currencyType"][value="usd"]').first.check(force=True)
        frame.evaluate(
            """
            () => {
                const el = document.getElementById('outerField1');
                const val = 'CODE_TS';
                el.value = val;
                selectField(el, val, 'outerField1');
                return { value: el.value, text: el.options[el.selectedIndex]?.text };
            }
            """
        )
        page.screenshot(path=str(OUT / "gacc_form_after_select.png"), full_page=True)
        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()
