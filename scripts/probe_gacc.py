"""Probe stats.customs.gov.cn with various launch options."""

from playwright.sync_api import sync_playwright

URLS = [
    "http://stats.customs.gov.cn/",
    "https://stats.customs.gov.cn/",
    "http://stats.customs.gov.cn/index",
    "https://stats.customs.gov.cn/index",
]


def try_url(p, url: str, *, headed: bool) -> None:
    browser = p.chromium.launch(
        headless=not headed,
        channel="msedge",
        args=["--ignore-certificate-errors"],
    )
    context = browser.new_context(
        ignore_https_errors=True,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        ),
        locale="zh-CN",
    )
    page = context.new_page()
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=45000)
        print("---", url, "headed=", headed)
        print("status:", resp.status if resp else None)
        print("final:", page.url)
        print("title:", page.title())
        html = page.content()
        print("len:", len(html))
        if len(html) > 100:
            print(html[:1500])
    except Exception as exc:
        print("ERR", url, exc)
    browser.close()


def main() -> None:
    with sync_playwright() as p:
        for url in URLS:
            try_url(p, url, headed=False)


if __name__ == "__main__":
    main()
