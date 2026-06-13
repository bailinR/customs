"""Headed probe - saves screenshot for selector discovery."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

URLS = [
    "http://stats.customs.gov.cn/",
    "http://stats.customs.gov.cn/index",
    "http://stats.customs.gov.cn/indexEn",
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="msedge",
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(
            ignore_https_errors=True,
            locale="zh-CN",
        )
        page = context.new_page()
        for i, url in enumerate(URLS):
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(3000)
                print(url, resp.status if resp else None, page.title(), len(page.content()))
                page.screenshot(path=str(OUT / f"gacc_probe_{i}.png"), full_page=True)
                if "查询" in page.content() or "进口" in page.content():
                    print("FOUND query page:", url)
                    break
            except Exception as exc:
                print("ERR", url, exc)
        browser.close()


if __name__ == "__main__":
    main()
