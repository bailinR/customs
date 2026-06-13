"""OpenCV helpers for GACC slider puzzle captcha."""

from __future__ import annotations

import base64
from dataclasses import dataclass

import cv2
import numpy as np

# stats.customs.gov.cn toCaptchaView iframe captcha (not SliderCaptcha library).
READ_SLIDER_OFFSET_JS = """
() => {
  const root = document.getElementById('captcha');
  if (!root) return 0;
  const slider = root.querySelector('.slider');
  const container = root.querySelector('.sliderContainer');
  if (slider && container) {
    const left = parseFloat(String(slider.style.left || '0').replace('px', ''));
    if (Number.isFinite(left) && left > 0) return left;
    return slider.getBoundingClientRect().left - container.getBoundingClientRect().left;
  }
  const block = root.querySelector('canvas.block');
  if (block) {
    const bl = parseFloat(String(block.style.left || '0').replace('px', ''));
    if (Number.isFinite(bl) && bl > 0) {
      const track = root.querySelector('.sliderContainer');
      const tw = track ? track.clientWidth : 310;
      const bw = block.width || 62;
      const imageTravel = Math.max((root.querySelector('canvas:not(.block)')?.width || 310) - bw, 1);
      const trackTravel = Math.max(tw - 40, 1);
      return bl * trackTravel / imageTravel;
    }
  }
  return 0;
}
"""

READ_CAPTCHA_MSG_JS = """
() => {
  const el = document.getElementById('msg');
  return (el && el.innerText) ? el.innerText.trim() : '';
}
"""

CAPTCHA_FAIL_JS = """
() => {
  const c = document.querySelector('.sliderContainer');
  return !!(c && c.classList.contains('sliderContainer_fail'));
}
"""

CAPTCHA_RESET_JS = """
() => {
  const slider = document.querySelector('.slider');
  const left = parseFloat(String(slider?.style.left || '0').replace('px', ''));
  const fail = document.querySelector('.sliderContainer')?.classList.contains('sliderContainer_fail');
  return { left: Number.isFinite(left) ? left : 0, fail: !!fail };
}
"""

READ_BLOCK_LEFT_JS = """
() => {
  const block = document.querySelector('canvas.block');
  if (!block) return 0;
  const left = parseFloat(String(block.style.left || '0').replace('px', ''));
  if (Number.isFinite(left) && left > 0) return left;
  const root = document.getElementById('captcha');
  const bg = root?.querySelector('canvas:not(.block)');
  if (bg) {
    const bl = block.getBoundingClientRect().left - bg.getBoundingClientRect().left;
    if (Number.isFinite(bl) && bl > 0) return bl;
  }
  return 0;
}
"""

# Fine-tune on the same captcha: coarse steps first, then fine (slider track px).
FINE_TUNE_SLIDER_STEPS = (
    15, -15, 20, -20, 10, -10, 25, -25,
    6, -6, 12, -12, 18, -18, 3, -3, 2, -2, 4, -4,
)
# After a failed drag, search ±N px around the slider position that landed.
ADAPTIVE_FAIL_STEPS = (2, -2, 4, -4, 6, -6, 8, -8, 10, -10, 12, -12)
MAX_TRIES_PER_CAPTCHA = 22


@dataclass
class CaptchaLayout:
    bg_width: int
    bg_height: int
    bg_box_width: float
    track_width: float
    handle_width: float
    block_width: int
    handle_x: float
    handle_y: float
    handle_height: float
    offset_px: float = 0.0


@dataclass
class GapDetectionResult:
    gap_x: int
    gap_x_float: float
    confidence: float
    method: str
    candidates: dict[str, int]


def decode_data_url(data_url: str, *, keep_alpha: bool = False) -> np.ndarray:
    if not data_url:
        raise ValueError("empty captcha image")
    if data_url.startswith("data:"):
        _, encoded = data_url.split(",", 1)
    else:
        encoded = data_url
    raw = base64.b64decode(encoded)
    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED) if keep_alpha else cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("unable to decode captcha image")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif not keep_alpha and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _prepare_puzzle(
    puzzle: np.ndarray,
) -> tuple[np.ndarray, np.ndarray | None, int]:
    if puzzle.ndim == 3 and puzzle.shape[2] == 4:
        puzzle_bgr = cv2.cvtColor(puzzle, cv2.COLOR_BGRA2BGR)
        alpha = puzzle[:, :, 3]
        puzzle_gray = cv2.cvtColor(puzzle_bgr, cv2.COLOR_BGR2GRAY)
        mask = (alpha > 128).astype(np.uint8) * 255
    else:
        puzzle_gray = cv2.cvtColor(puzzle, cv2.COLOR_BGR2GRAY)
        mask = None
    return puzzle_gray, mask, int(puzzle_gray.shape[1])


def _search_margin(block_w: int, width: int) -> int:
    return min(block_w + 16, max(width // 5, block_w + 8))


def _notch_score_at_x(bg_gray: np.ndarray, block_w: int, x: int) -> float:
    """Score how likely x is the puzzle hole (higher = better)."""
    h, w = bg_gray.shape[:2]
    margin = _search_margin(block_w, w)
    if x < margin or x > w - block_w - 4:
        return -1.0

    y0, y1 = max(1, h // 8), min(h - 1, 7 * h // 8)
    band = bg_gray[y0:y1, :]
    inner = band[:, x + 4 : x + block_w - 4]
    if inner.size == 0:
        return -1.0

    blurred = cv2.GaussianBlur(bg_gray, (3, 3), 0)
    sobelx = np.abs(cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)[y0:y1, :])

    inner_mean = float(inner.mean())
    left_ref = band[:, max(0, x - block_w) : x]
    ref_mean = float(left_ref.mean()) if left_ref.size else inner_mean
    darkness = max(0.0, ref_mean - inner_mean)

    left_edge = float(sobelx[:, max(0, x - 1) : x + 2].sum())
    right_edge = float(sobelx[:, x + block_w - 2 : x + block_w + 1].sum())
    return left_edge + right_edge + darkness * 14.0


def _edge_pair_score_at_x(bg_gray: np.ndarray, block_w: int, x: int) -> float:
    h, w = bg_gray.shape[:2]
    margin = _search_margin(block_w, w)
    if x < margin or x > w - block_w - 4:
        return -1.0
    y0, y1 = max(1, h // 6), min(h - 1, 5 * h // 6)
    edges = cv2.Canny(cv2.GaussianBlur(bg_gray, (3, 3), 0), 60, 160)
    edge_band = edges[y0:y1, :]
    left_col = float(edge_band[:, x : x + 2].sum())
    right_col = float(edge_band[:, x + block_w - 2 : x + block_w].sum())
    inner = float(edge_band[:, x + 6 : x + block_w - 6].sum())
    return left_col * right_col - inner * 0.35


def _variance_score_at_x(bg_gray: np.ndarray, block_w: int, x: int) -> float:
    h, w = bg_gray.shape[:2]
    margin = _search_margin(block_w, w)
    if x < margin or x > w - block_w - 4:
        return -1.0
    y0, y1 = max(1, h // 8), min(h - 1, 7 * h // 8)
    band = bg_gray[y0:y1, :].astype(np.float32)
    inner = band[:, x + 5 : x + block_w - 5]
    if inner.size == 0:
        return -1.0
    outer = band[:, max(0, x - block_w) : max(0, x - 4)]
    if outer.size == 0:
        return float(inner.var())
    return float(max(0.0, outer.var() - inner.var()))


def _combined_score_at_x(bg_gray: np.ndarray, block_w: int, x: int) -> float:
    notch = _notch_score_at_x(bg_gray, block_w, x)
    edge = _edge_pair_score_at_x(bg_gray, block_w, x)
    var = _variance_score_at_x(bg_gray, block_w, x)
    if notch < 0:
        return -1.0
    return notch * 0.48 + edge * 0.32 + var * 0.20


def refine_gap_subpixel(
    bg_gray: np.ndarray,
    block_w: int,
    rough_x: int,
    *,
    window: int = 28,
) -> float:
    """Local scan with parabolic sub-pixel peak fit."""
    margin = _search_margin(block_w, bg_gray.shape[1])
    w = bg_gray.shape[1]
    lo = max(margin, rough_x - window)
    hi = min(w - block_w - 4, rough_x + window)
    if lo > hi:
        return float(rough_x)

    scores: list[tuple[int, float]] = []
    best_x = rough_x
    best_score = -1.0
    for x in range(lo, hi + 1):
        score = _combined_score_at_x(bg_gray, block_w, x)
        scores.append((x, score))
        if score > best_score:
            best_score = score
            best_x = x

    if len(scores) < 3:
        return float(best_x)

    best_i = next(i for i, (x, _) in enumerate(scores) if x == best_x)
    if 0 < best_i < len(scores) - 1:
        x0, y0 = scores[best_i - 1]
        x1, y1 = scores[best_i]
        x2, y2 = scores[best_i + 1]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > 1e-3:
            delta = 0.5 * (y0 - y2) / denom
            delta = max(-0.8, min(0.8, delta))
            return float(x1) + delta
    return float(best_x)


def refine_gap_x(bg_gray: np.ndarray, block_w: int, rough_x: int, *, window: int = 28) -> int:
    return int(round(refine_gap_subpixel(bg_gray, block_w, rough_x, window=window)))


def _detect_hole_by_notch(bg_gray: np.ndarray, block_w: int) -> int:
    """Find puzzle hole: darker fill + strong vertical borders."""
    w = bg_gray.shape[:2][1]
    margin = _search_margin(block_w, w)
    search_len = w - block_w - margin - 4
    if search_len <= 0:
        return margin

    best_score = -1.0
    best_x = margin
    for i in range(search_len):
        x = margin + i
        score = _combined_score_at_x(bg_gray, block_w, x)
        if score > best_score:
            best_score = score
            best_x = x
    return int(best_x)


def _detect_by_puzzle_edge_align(
    bg_gray: np.ndarray,
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
    block_w: int,
    skip: int,
) -> int | None:
    """Align puzzle piece vertical edges with hole edges on background."""
    puzzle_edges = cv2.Canny(puzzle_gray, 45, 130)
    if mask is not None:
        puzzle_edges = cv2.bitwise_and(puzzle_edges, puzzle_edges, mask=mask)
    if int(puzzle_edges.sum()) < 40:
        return None

    bg_edges = cv2.Canny(cv2.GaussianBlur(bg_gray, (3, 3), 0), 45, 130)
    h = bg_edges.shape[0]
    y0, y1 = max(1, h // 8), min(h - 1, 7 * h // 8)
    pe = puzzle_edges[y0:y1, :].sum(axis=0).astype(np.float32)
    if pe.max() <= 0:
        return None
    pe /= pe.max()

    be = bg_edges[y0:y1, :]
    w = bg_gray.shape[1]
    best_x: int | None = None
    best_score = -1.0
    for x in range(skip, w - block_w - 2):
        left_prof = be[:, x : x + 3].sum(axis=0).astype(np.float32)
        if left_prof.max() > 0:
            left_prof /= left_prof.max()
        right_prof = be[:, x + block_w - 3 : x + block_w].sum(axis=0).astype(np.float32)
        if right_prof.max() > 0:
            right_prof /= right_prof.max()
        left_match = float(np.dot(left_prof, pe[: left_prof.size]))
        right_match = float(np.dot(right_prof, pe[-right_prof.size :]))
        score = left_match + right_match
        if score > best_score:
            best_score = score
            best_x = x
    if best_score < 0.35:
        return None
    return best_x


def _detect_hole_by_edge_pair(bg_gray: np.ndarray, block_w: int) -> int:
    h, w = bg_gray.shape[:2]
    margin = _search_margin(block_w, w)
    y0, y1 = max(1, h // 6), min(h - 1, 5 * h // 6)

    edges = cv2.Canny(cv2.GaussianBlur(bg_gray, (3, 3), 0), 60, 160)
    edge_band = edges[y0:y1, :]

    best_score = -1.0
    best_x = margin
    for x in range(margin, w - block_w - 4):
        left_col = float(edge_band[:, x : x + 2].sum())
        right_col = float(edge_band[:, x + block_w - 2 : x + block_w].sum())
        inner = float(edge_band[:, x + 6 : x + block_w - 6].sum())
        score = left_col * right_col - inner * 0.35
        if score > best_score:
            best_score = score
            best_x = x
    return int(best_x)


def _template_peaks(
    bg_gray: np.ndarray,
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
    skip: int,
    *,
    top_k: int = 3,
) -> list[tuple[int, float]]:
    if mask is not None and mask.any():
        result = cv2.matchTemplate(bg_gray, puzzle_gray, cv2.TM_CCORR_NORMED, mask=mask)
    else:
        result = cv2.matchTemplate(bg_gray, puzzle_gray, cv2.TM_CCOEFF_NORMED)
    if skip < result.shape[1]:
        result[:, :skip] = -1.0

    pw = puzzle_gray.shape[1]
    peaks: list[tuple[int, float]] = []
    work = result.copy()
    for _ in range(top_k):
        _min, max_val, _min_loc, max_loc = cv2.minMaxLoc(work)
        if max_val < 0.22:
            break
        peaks.append((int(max_loc[0]), float(max_val)))
        x0 = max(0, max_loc[0] - pw)
        x1 = min(work.shape[1], max_loc[0] + pw)
        work[:, x0:x1] = -1.0
    return peaks


def _detect_by_edge_template(
    bg_gray: np.ndarray,
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
    skip: int,
) -> int | None:
    puzzle_edges = cv2.Canny(puzzle_gray, 40, 120)
    if mask is not None:
        puzzle_edges = cv2.bitwise_and(puzzle_edges, puzzle_edges, mask=mask)
    bg_edges = cv2.Canny(bg_gray, 40, 120)
    if puzzle_edges.sum() < 50:
        return None

    result = cv2.matchTemplate(bg_edges, puzzle_edges, cv2.TM_CCOEFF_NORMED)
    if skip < result.shape[1]:
        result[:, :skip] = -1.0
    _min, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    if max_val > 0.18:
        return int(max_loc[0])
    return None


def _vote_gap(candidates: list[tuple[int, float]]) -> int:
    """Cluster nearby x values and pick highest total weight."""
    if not candidates:
        return 0
    clusters: list[list[tuple[int, float]]] = []
    for x, weight in sorted(candidates, key=lambda t: t[0]):
        placed = False
        for cluster in clusters:
            if abs(cluster[0][0] - x) <= 14:
                cluster.append((x, weight))
                placed = True
                break
        if not placed:
            clusters.append([(x, weight)])
    best_cluster = max(clusters, key=lambda c: sum(w for _, w in c))
    total_w = sum(w for _, w in best_cluster)
    if total_w <= 0:
        return int(best_cluster[0][0])
    avg = sum(x * w for x, w in best_cluster) / total_w
    return int(round(avg))


def detect_gap_x_detailed(
    background: np.ndarray,
    puzzle: np.ndarray | None = None,
) -> GapDetectionResult:
    """
    Return gap x (canvas.block.style.left target) using multi-method ensemble.
    """
    bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
    block_w = 62
    puzzle_gray: np.ndarray | None = None
    mask: np.ndarray | None = None

    if puzzle is not None and puzzle.size > 0:
        puzzle_gray, mask, block_w = _prepare_puzzle(puzzle)
        ph, pw = puzzle_gray.shape[:2]
        bh, bw = bg_gray.shape[:2]
        if ph > bh or pw > bw:
            scale = min(bw / max(pw, 1), bh / max(ph, 1), 1.0)
            puzzle_gray = cv2.resize(
                puzzle_gray,
                (max(int(pw * scale), 8), max(int(ph * scale), 8)),
            )
            if mask is not None:
                mask = cv2.resize(mask, (puzzle_gray.shape[1], puzzle_gray.shape[0]))
            block_w = puzzle_gray.shape[1]

    skip = _search_margin(block_w, bg_gray.shape[1])
    method_scores: dict[str, int] = {}
    votes: list[tuple[int, float]] = []

    notch_x = _detect_hole_by_notch(bg_gray, block_w)
    method_scores["notch"] = notch_x
    votes.append((notch_x, 3.2))

    edge_x = _detect_hole_by_edge_pair(bg_gray, block_w)
    method_scores["edge_pair"] = edge_x
    votes.append((edge_x, 2.8))

    if abs(notch_x - edge_x) <= 12:
        anchor = int(round((notch_x + edge_x) / 2))
        method_scores["notch_edge_anchor"] = anchor
        votes.append((anchor, 5.0))

    template_peaks: list[tuple[int, float]] = []
    use_texture_template = abs(notch_x - edge_x) > 18
    if puzzle_gray is not None:
        align_x = _detect_by_puzzle_edge_align(bg_gray, puzzle_gray, mask, block_w, skip)
        if align_x is not None:
            method_scores["puzzle_edge_align"] = align_x
            w = 3.4 if abs(align_x - notch_x) <= 20 else 2.2
            votes.append((align_x, w))

        edge_tpl = _detect_by_edge_template(bg_gray, puzzle_gray, mask, skip)
        if edge_tpl is not None:
            method_scores["edge_template"] = edge_tpl
            tpl_w = 2.4
            if abs(edge_tpl - notch_x) > 28:
                tpl_w *= 0.35
            votes.append((edge_tpl, tpl_w))

        if use_texture_template:
            template_peaks = _template_peaks(bg_gray, puzzle_gray, mask, skip)
            for rank, (x, conf) in enumerate(template_peaks):
                method_scores[f"template_{rank}"] = x
                weight = 1.2 + conf * 1.5 * (0.85**rank)
                if rank == 0 and abs(x - notch_x) > 28:
                    weight *= 0.25
                votes.append((x, weight))

    if abs(notch_x - edge_x) <= 12:
        rough_x = int(round((notch_x + edge_x) / 2))
    else:
        gap_x = _vote_gap(votes)
        rough_x = max(skip, min(gap_x, bg_gray.shape[1] - block_w - 2))
    gap_x_float = refine_gap_subpixel(bg_gray, block_w, rough_x)
    gap_x = int(round(gap_x_float))
    method_scores["refined"] = gap_x
    method_scores["refined_sub"] = int(round(gap_x_float * 10))

    # Confidence: agreement between notch/edge vs final pick
    agree = sum(1 for x in (notch_x, edge_x) if abs(x - gap_x) <= 12)
    confidence = 0.35 + agree * 0.25
    if puzzle_gray is not None:
        tpl0 = method_scores.get("template_0")
        if tpl0 is not None and abs(tpl0 - gap_x) <= 12:
            confidence += 0.15
        elif template_peaks and abs(template_peaks[0][0] - notch_x) > 28:
            confidence += 0.1

    return GapDetectionResult(
        gap_x=gap_x,
        gap_x_float=gap_x_float,
        confidence=min(confidence, 1.0),
        method="ensemble",
        candidates=method_scores,
    )


def detect_gap_x(background: np.ndarray, puzzle: np.ndarray | None = None) -> int:
    return detect_gap_x_detailed(background, puzzle).gap_x


def compute_drag_distance(
    gap_x: float,
    *,
    bg_width: int,
    block_width: int,
    track_width: float,
    handle_width: float,
    offset_px: float = 0.0,
) -> float:
    """
    Map canvas.block left (image px) → slider.style.left (track px).
    Verified: block.left / slider.left ≈ (bg_width - block_width) / (track_width - handle_width)
    """
    if bg_width <= 0 or track_width <= 0:
        return 0.0
    image_travel = max(bg_width - block_width, 1)
    track_travel = max(track_width - handle_width, 1.0)
    travel = max(float(gap_x), 0.0)
    distance = travel * track_travel / image_travel + offset_px
    return max(0.0, min(distance, track_travel))


def build_drag_track(delta: float) -> list[int]:
    target = max(int(round(delta)), 0)
    return [target] if target else [0]


def read_slider_offset(page_or_scope) -> float:
    try:
        return float(page_or_scope.evaluate(READ_SLIDER_OFFSET_JS))
    except Exception:
        return 0.0


def read_slider_left(page_or_scope) -> float:
    return read_slider_offset(page_or_scope)


def read_captcha_msg(page_or_scope) -> str:
    try:
        return str(page_or_scope.evaluate(READ_CAPTCHA_MSG_JS) or "")
    except Exception:
        return ""


def captcha_failed(page_or_scope) -> bool:
    try:
        return bool(page_or_scope.evaluate(CAPTCHA_FAIL_JS))
    except Exception:
        return False


def _drag_with_real_mouse(
    page,
    *,
    start_x: float,
    start_y: float,
    delta: float,
) -> None:
    """Drag with ease-out curve and slight vertical wobble (more human-like)."""
    move = max(float(delta), 0.0)
    page.mouse.move(start_x, start_y)
    page.wait_for_timeout(100)
    page.mouse.down()
    page.wait_for_timeout(80)

    steps = max(28, min(65, int(move / 2.5) or 28))
    for i in range(1, steps + 1):
        t = i / steps
        ease = 1.0 - (1.0 - t) ** 2.5
        cx = start_x + move * ease
        wobble = 1.2 * np.sin(t * np.pi * 2.5)
        page.mouse.move(cx, start_y + wobble)
        page.wait_for_timeout(max(6, int(14 - 8 * t)))

    page.wait_for_timeout(60)
    page.mouse.up()
    page.wait_for_timeout(180)


def drag_captcha_handle(
    page,
    handle_locator,
    target_offset: float,
    track: list[int],
    *,
    scope=None,
) -> float:
    """
    Drag slider to absolute target offset (px from container left).
    """
    eval_scope = scope or page
    page.bring_to_front()

    slider = handle_locator
    slider.wait_for(state="visible", timeout=5000)

    box = slider.bounding_box()
    if not box:
        raise ValueError("slider has no bounding box")

    target = float(target_offset)
    before = read_slider_offset(eval_scope)
    delta = target - before

    if abs(delta) < 2:
        return before

    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    _drag_with_real_mouse(page, start_x=start_x, start_y=start_y, delta=delta)
    after = read_slider_offset(eval_scope)

    if after <= before + 2:
        track_loc = eval_scope.locator("#captcha .sliderContainer").first
        if track_loc.count() > 0:
            try:
                tx = int(min(max(target + box["width"] / 2, box["width"] / 2), 9999))
                ty = int(box["height"] / 2)
                slider.drag_to(
                    track_loc,
                    target_position={"x": tx, "y": ty},
                    force=True,
                    timeout=8000,
                )
                page.wait_for_timeout(250)
                after = read_slider_offset(eval_scope)
            except Exception:
                pass

    if after <= before + 2:
        raise RuntimeError(
            f"滑块未移动（offset {before:.0f}→{after:.0f}px，目标 {target:.0f}px）"
        )

    remaining = target - after
    if abs(remaining) > 1.5:
        box2 = slider.bounding_box()
        if box2:
            cx = box2["x"] + box2["width"] / 2
            cy = box2["y"] + box2["height"] / 2
            page.mouse.move(cx, cy)
            page.wait_for_timeout(50)
            page.mouse.down()
            page.wait_for_timeout(50)
            page.mouse.move(cx + remaining, cy, steps=max(6, int(abs(remaining) / 2)))
            page.wait_for_timeout(50)
            page.mouse.up()
            page.wait_for_timeout(120)
            after = read_slider_offset(eval_scope)

    return read_slider_offset(eval_scope)


def reset_slider_position(page, handle_locator, scope=None) -> float:
    """Drag slider back to the start (for retry on the same captcha image)."""
    eval_scope = scope or page
    current = read_slider_offset(eval_scope)
    if current < 3:
        return current
    return drag_captcha_handle(page, handle_locator, 1.0, [], scope=eval_scope)


def read_block_left(page_or_scope) -> float:
    try:
        return float(page_or_scope.evaluate(READ_BLOCK_LEFT_JS))
    except Exception:
        return 0.0


def block_left_to_slider(
    block_left: float,
    *,
    bg_width: int,
    block_width: int,
    track_width: float,
    handle_width: float,
) -> float:
    if block_left <= 0:
        return 0.0
    image_travel = max(bg_width - block_width, 1)
    track_travel = max(track_width - handle_width, 1.0)
    return block_left * track_travel / image_travel


def _add_target(targets: list[float], seen: set[int], value: float, track_travel: float) -> None:
    ti = int(round(value))
    if ti in seen or ti < 8 or ti > track_travel:
        return
    seen.add(ti)
    targets.append(float(ti))


def build_initial_targets(base_distance: float, track_travel: float) -> list[float]:
    seen: set[int] = set()
    targets: list[float] = []
    _add_target(targets, seen, base_distance, track_travel)
    for step in FINE_TUNE_SLIDER_STEPS:
        _add_target(targets, seen, base_distance + step, track_travel)
    return targets


def expand_targets_from_landing(
    targets: list[float],
    seen: set[int],
    landed_slider: float,
    track_travel: float,
) -> None:
    """After a near-miss, queue small adjustments around where the slider stopped."""
    for step in ADAPTIVE_FAIL_STEPS:
        _add_target(targets, seen, landed_slider + step, track_travel)


def iter_fine_tune_targets(base_distance: float, track_travel: float) -> list[float]:
    """Backward-compatible wrapper."""
    return build_initial_targets(base_distance, track_travel)[1:]


def parse_layout(meta: dict) -> CaptchaLayout:
    bg_box = meta.get("bgBox") or {}
    handle_box = meta.get("handleBox") or {}
    track_box = meta.get("trackBox") or handle_box
    bg_width = int(meta.get("bgNaturalWidth") or bg_box.get("width") or 0)
    bg_height = int(meta.get("bgNaturalHeight") or bg_box.get("height") or 0)
    block_width = int(meta.get("blockWidth") or 62)
    track_width = float(track_box.get("width") or bg_box.get("width") or 0)
    handle_width = float(handle_box.get("width") or 40)
    return CaptchaLayout(
        bg_width=bg_width,
        bg_height=bg_height,
        bg_box_width=float(bg_box.get("width") or 0),
        track_width=track_width,
        handle_width=handle_width,
        block_width=block_width,
        handle_x=float(handle_box.get("x") or 0),
        handle_y=float(handle_box.get("y") or 0),
        handle_height=float(handle_box.get("height") or 40),
        offset_px=float(meta.get("offsetPx") or 0.0),
    )


def solve_from_meta(meta: dict, *, attempt: int = 0) -> tuple[float, int, float]:
    layout = parse_layout(meta)
    background = decode_data_url(meta["bgDataUrl"])
    puzzle = None
    puzzle_url = meta.get("puzzleDataUrl")
    if puzzle_url and not puzzle_url.startswith("data:,"):
        try:
            puzzle = decode_data_url(puzzle_url, keep_alpha=True)
        except ValueError:
            puzzle = None
    detail = detect_gap_x_detailed(background, puzzle)
    gap_x = max(0, detail.gap_x)
    distance = compute_drag_distance(
        detail.gap_x_float,
        bg_width=layout.bg_width or background.shape[1],
        block_width=layout.block_width,
        track_width=layout.track_width or layout.bg_box_width,
        handle_width=layout.handle_width,
        offset_px=layout.offset_px,
    )
    return distance, gap_x, detail.confidence


def track_travel_from_layout(layout: CaptchaLayout) -> float:
    return max(layout.track_width - layout.handle_width, 1.0)
