"""Probe entry via customs.gov.cn portal."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "output"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="msedge",
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(ignore_https_errors=True, locale="zh-CN")
        page = context.new_page()
        for url in [
            "http://www.customs.gov.cn/",
            "http://stats.customs.gov.cn/",
        ]:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                print("url", page.url, "title", page.title(), "len", len(page.content()))
                if "stats.customs" in page.url or "进口" in page.content():
                    page.screenshot(path=str(OUT / "gacc_portal.png"), full_page=True)
            except Exception as e:
                print(e)
        browser.close()


if __name__ == "__main__":
    main()
