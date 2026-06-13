"""
验证码诊断脚本 — 请在验证码弹出后运行。

用法:
  python scripts/gacc_captcha_debug.py

步骤:
  1. 脚本会打开 Edge 并进入海关查询页
  2. 请手动点「查询」直到验证码弹出
  3. 回到终端按 Enter，脚本会保存诊断 JSON 并尝试拖动滑块
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from config import GACC_BASE_URL, GACC_BROWSER_CHANNEL, GACC_BROWSER_HEADLESS
from gacc_captcha_scope import (
    collect_context_overview,
    find_captcha_scope,
    format_diagnostics,
    resolve_captcha_scope,
    save_diagnostics,
)
from gacc_slider_solver import (
    build_drag_track,
    detect_gap_x_detailed,
    drag_captcha_handle,
    read_slider_left,
    solve_from_meta,
)

OUT = ROOT / "data" / "gacc_captcha_debug.json"


def _launch_kwargs() -> dict:
    kwargs: dict = {
        "headless": GACC_BROWSER_HEADLESS,
        "args": ["--ignore-certificate-errors", "--disable-blink-features=AutomationControlled"],
    }
    if GACC_BROWSER_CHANNEL:
        kwargs["channel"] = GACC_BROWSER_CHANNEL
    return kwargs


def _extract_meta(cs):
    from gacc_captcha import _extract_captcha_meta_from_scope

    return _extract_captcha_meta_from_scope(cs)


def main() -> None:
    print("=" * 60)
    print("海关验证码诊断")
    print("1) 浏览器打开后，请手动提交查询直到验证码出现")
    print("2) 验证码可见时，回到此终端按 Enter")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_kwargs())
        context = browser.new_context(
            ignore_https_errors=True,
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        )
        page = context.new_page()
        page.goto(GACC_BASE_URL, wait_until="load", timeout=90_000)
        input("\n>>> 验证码已弹出？按 Enter 继续诊断…\n")

        cs = find_captcha_scope(context) or resolve_captcha_scope(context, page)
        cs.page.bring_to_front()

        before = read_slider_left(cs.scope)
        overview = collect_context_overview(context)
        print("\n--- 页面/iframe 概览 ---")
        print(json.dumps(overview, ensure_ascii=False, indent=2))

        meta = _extract_meta(cs)
        drag_result: dict = {"before_left": before, "after_left": before, "distance": None, "error": None}
        if meta:
            try:
                from gacc_slider_solver import decode_data_url

                bg = decode_data_url(meta["bgDataUrl"])
                puzzle = None
                if meta.get("puzzleDataUrl") and not meta["puzzleDataUrl"].startswith("data:,"):
                    puzzle = decode_data_url(meta["puzzleDataUrl"], keep_alpha=True)
                detail = detect_gap_x_detailed(bg, puzzle)
                drag_result["detection"] = {
                    "gap_x": detail.gap_x,
                    "confidence": round(detail.confidence, 2),
                    "candidates": detail.candidates,
                }
                print("\n--- 缺口识别 ---")
                print(json.dumps(drag_result["detection"], ensure_ascii=False, indent=2))

                img_dir = ROOT / "data" / "captcha_debug_images"
                img_dir.mkdir(parents=True, exist_ok=True)
                import cv2

                cv2.imwrite(str(img_dir / "bg.png"), bg)
                if puzzle is not None:
                    cv2.imwrite(str(img_dir / "puzzle.png"), puzzle)
                print(f"验证码截图: {img_dir}")

                distance, gap_x, confidence = solve_from_meta(meta, attempt=0)
                drag_result["confidence"] = confidence
                drag_result["distance"] = distance
                drag_result["gap_x"] = gap_x
                print(f"\n识别缺口≈{gap_x}px → 滑块目标 {distance:.1f}px")
                handle = cs.scope.locator("#captcha .slider").first
                after = drag_captcha_handle(cs.page, handle, distance, [], scope=cs.scope)
                drag_result["after_left"] = after
                print(f"拖动后 slider.left = {after}")
            except Exception as exc:
                drag_result["error"] = str(exc)
                drag_result["after_left"] = read_slider_left(cs.scope)
                print(f"\n拖动失败: {exc}")
        else:
            drag_result["error"] = "无法提取验证码 meta"
            print("\n无法提取验证码 meta（#captcha 可能不在当前 frame）")

        diag_text = format_diagnostics(context, cs)
        print("\n--- 诊断摘要 ---")
        print(diag_text)

        save_diagnostics(
            context,
            cs,
            out_path=OUT,
            extra={"drag_result": drag_result, "summary": diag_text},
        )
        print(f"\n完整诊断已保存: {OUT}")
        print("请把此文件发给开发者，或在对话中粘贴其内容。")

        time.sleep(2)
        browser.close()


if __name__ == "__main__":
    main()
