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
    8, -8, 12, -12, 16, -16, 20, -20,
    4, -4, 6, -6, 10, -10, 14, -14,
    2, -2, 3, -3, 1, -1, 5, -5,
)
# After a failed drag, nudge in image px then convert to slider targets.
ADAPTIVE_GAP_STEPS = (
    1, -1, 2, -2, 3, -3, 4, -4, 5, -5,
    6, -6, 8, -8, 10, -10, 12, -12, 14, -14,
)
# Slider-track px fallback when block.left is unavailable.
ADAPTIVE_FAIL_STEPS = (1, -1, 2, -2, 3, -3, 4, -4, 6, -6, 8, -8, 10, -10)
MAX_TRIES_PER_CAPTCHA = 32


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
    alternates: tuple[float, ...] = ()


def puzzle_block_width(puzzle: np.ndarray | None, fallback: int = 62) -> int:
    if puzzle is None or puzzle.size == 0:
        return fallback
    _, _, width = _prepare_puzzle(puzzle)
    return max(int(width), 8)


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


def _crop_to_alpha_bbox(
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Crop full-size block canvas down to the visible puzzle piece."""
    if mask is None or not mask.any():
        return puzzle_gray, mask
    coords = cv2.findNonZero(mask)
    if coords is None:
        return puzzle_gray, mask
    x, y, w, h = cv2.boundingRect(coords)
    if w <= 0 or h <= 0:
        return puzzle_gray, mask
    cropped_gray = puzzle_gray[y : y + h, x : x + w]
    cropped_mask = mask[y : y + h, x : x + w]
    return cropped_gray, cropped_mask


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
    puzzle_gray, mask = _crop_to_alpha_bbox(puzzle_gray, mask)
    return puzzle_gray, mask, int(puzzle_gray.shape[1])


def _enhance_gray(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


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


def _puzzle_band(bg_gray: np.ndarray, puzzle_gray: np.ndarray) -> tuple[int, int]:
    ph, pw = puzzle_gray.shape[:2]
    bh = bg_gray.shape[0]
    y0 = max(0, (bh - ph) // 2)
    y1 = min(bh, y0 + ph)
    return y0, y1


def _hole_fill_scores(
    bg_gray: np.ndarray,
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
    skip: int,
) -> list[tuple[int, float]]:
    """Masked mean absolute diff at each x — peak marks the hole."""
    ph, pw = puzzle_gray.shape[:2]
    y0, y1 = _puzzle_band(bg_gray, puzzle_gray)
    puzzle_band = puzzle_gray[: y1 - y0, :]
    bg_band = bg_gray[y0:y1, :]
    if mask is not None:
        m = mask[: y1 - y0, :] > 128
    else:
        m = np.ones(puzzle_band.shape, dtype=bool)

    if not m.any():
        return []

    w = bg_gray.shape[1]
    scores: list[tuple[int, float]] = []
    puzzle_f = puzzle_band.astype(np.float32)
    for x in range(skip, w - pw + 1):
        patch = bg_band[:, x : x + pw].astype(np.float32)
        diff = np.abs(patch - puzzle_f)
        score = float(diff[m].mean())
        scores.append((x, score))
    return scores


def _subpixel_peak_from_scores(scores: list[tuple[int, float]]) -> tuple[float, float]:
    """Return (subpixel_x, peak_score) from a score curve (higher = better)."""
    if not scores:
        return 0.0, 0.0
    best_i = max(range(len(scores)), key=lambda i: scores[i][1])
    best_x, best_score = scores[best_i]
    if best_score <= 0 or len(scores) < 3:
        return float(best_x), best_score
    if 0 < best_i < len(scores) - 1:
        x0, y0 = scores[best_i - 1]
        x1, y1 = scores[best_i]
        x2, y2 = scores[best_i + 1]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > 1e-3:
            delta = 0.5 * (y0 - y2) / denom
            delta = max(-0.9, min(0.9, delta))
            return float(x1) + delta, y1
    return float(best_x), best_score


def _top_peaks_from_scores(
    scores: list[tuple[int, float]],
    *,
    top_k: int = 3,
    min_sep: int = 18,
    min_ratio: float = 0.82,
) -> list[tuple[float, float]]:
    if not scores:
        return []
    peak_x, peak_score = _subpixel_peak_from_scores(scores)
    peaks: list[tuple[float, float]] = [(peak_x, peak_score)]
    if peak_score <= 0:
        return peaks

    work = scores.copy()
    pw = min_sep
    for _ in range(top_k - 1):
        best_i = max(range(len(work)), key=lambda i: work[i][1])
        bx, bs = work[best_i]
        if bs < peak_score * min_ratio:
            break
        if not any(abs(bx - px) >= min_sep for px, _ in peaks):
            break
        peaks.append((float(bx), bs))
        x0 = max(0, best_i - pw)
        x1 = min(len(work), best_i + pw + 1)
        for i in range(x0, x1):
            work[i] = (work[i][0], -1.0)
    return peaks


def _detect_gap_by_hole_fill_diff(
    bg_gray: np.ndarray,
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
    block_w: int,
    skip: int,
) -> tuple[int, float, list[tuple[int, float]]]:
    """
    Hole is filled with flat gray — masked diff between puzzle piece and bg is maximal there.
    """
    scores = _hole_fill_scores(bg_gray, puzzle_gray, mask, skip)
    if not scores:
        return skip, 0.0, scores
    gap_x_float, best_score = _subpixel_peak_from_scores(scores)
    return int(round(gap_x_float)), best_score, scores


def _pure_white_mask(bg_bgr: np.ndarray) -> np.ndarray:
    """Pure white hole fill (#FFF) — GACC gap is solid white, not light gray."""
    b, g, r = cv2.split(bg_bgr)
    pure = (r >= 248) & (g >= 248) & (b >= 248)
    return pure.astype(np.uint8) * 255


def _white_mask(bg_bgr: np.ndarray) -> np.ndarray:
    """Slightly relaxed white for legacy rim helper."""
    return _pure_white_mask(bg_bgr)


def _hole_search_skip(block_w: int, width: int) -> int:
    """Target hole is always right of the puzzle piece parked at x=0."""
    return max(_search_margin(block_w, width), block_w + 10)


def _white_hole_scores(
    bg_bgr: np.ndarray,
    block_w: int,
    skip: int,
    *,
    puzzle_gray: np.ndarray | None = None,
    mask: np.ndarray | None = None,
) -> list[tuple[int, float]]:
    """
    Slide a window over the bg; peak x = where the puzzle slot is filled with pure white.
    """
    h, w = bg_bgr.shape[:2]
    bright = _pure_white_mask(bg_bgr)
    if puzzle_gray is not None and puzzle_gray.size > 0:
        ph, pw = puzzle_gray.shape[:2]
        y0, y1 = _puzzle_band(bg_bgr, puzzle_gray)
        band = bright[y0:y1, :]
        if mask is not None:
            m = mask[: y1 - y0, :] > 128
        else:
            m = np.ones((y1 - y0, pw), dtype=bool)
    else:
        ph, pw = h, block_w
        y0, y1 = max(1, h // 10), min(h - 1, 9 * h // 10)
        band = bright[y0:y1, :]
        m = None

    if band.size == 0:
        return []

    scores: list[tuple[int, float]] = []
    win_w = pw if puzzle_gray is not None else block_w
    for x in range(skip, w - win_w - 1):
        patch = band[:, x : x + win_w]
        if m is not None and m.shape == patch.shape:
            if not m.any():
                continue
            ratio = float((patch[m] > 0).mean())
        else:
            core = patch[4:-4, 8 : win_w - 8] if patch.shape[1] > 20 else patch
            if core.size == 0:
                continue
            ratio = float((core > 0).mean())
        if ratio < 0.42:
            continue
        scores.append((x, ratio * 10000.0))
    return scores


def _detect_gap_by_white_hole(
    bg_bgr: np.ndarray,
    block_w: int,
    skip: int,
    *,
    puzzle_gray: np.ndarray | None = None,
    mask: np.ndarray | None = None,
) -> tuple[int | None, float, list[tuple[int, float]]]:
    scores = _white_hole_scores(
        bg_bgr, block_w, skip, puzzle_gray=puzzle_gray, mask=mask
    )
    if not scores:
        return None, 0.0, scores
    gap_x_float, best_score = _subpixel_peak_from_scores(scores)
    if best_score < 4200.0:
        return None, best_score, scores
    return int(round(gap_x_float)), best_score, scores


def _detect_gap_by_white_blob(
    bg_bgr: np.ndarray,
    block_w: int,
    skip: int,
) -> int | None:
    """Find pure-white blob roughly puzzle-sized on the right side."""
    mask = _pure_white_mask(bg_bgr)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    target_area = block_w * max(bg_bgr.shape[0] // 2, 40)
    best_x: int | None = None
    best_score = -1.0
    for cnt in contours:
        x, _y, bw, bh = cv2.boundingRect(cnt)
        if x < skip:
            continue
        area = float(cv2.contourArea(cnt))
        if area < target_area * 0.15:
            continue
        if bw < block_w * 0.45 or bw > block_w * 2.2:
            continue
        size_fit = 1.0 - min(abs(bw - block_w) / max(block_w, 1), 1.0)
        score = area * (0.5 + size_fit * 0.5)
        if score > best_score:
            best_score = score
            best_x = x
    return best_x


def _white_rim_scores(
    bg_bgr: np.ndarray,
    block_w: int,
    skip: int,
) -> list[tuple[int, float]]:
    """
    Score each x by paired vertical white edges (left + right of puzzle slot).
    The GACC hole is outlined in white — this is the most reliable cue.
    """
    h, w = bg_bgr.shape[:2]
    bright = _white_mask(bg_bgr)
    y0, y1 = max(1, h // 10), min(h - 1, 9 * h // 10)
    band = bright[y0:y1, :].astype(np.float32)
    if band.size == 0:
        return []

    scores: list[tuple[int, float]] = []
    for x in range(skip, w - block_w - 2):
        left_edge = float(band[:, x : x + 4].sum())
        right_edge = float(band[:, x + block_w - 4 : x + block_w].sum())
        inner_white = float(band[:, x + 10 : x + block_w - 10].sum())
        if left_edge < 800 or right_edge < 800:
            continue
        outer_ring = left_edge + right_edge
        paired = (left_edge * right_edge) ** 0.5
        score = paired + outer_ring * 0.12 - inner_white * 0.45
        scores.append((x, score))
    return scores


def _detect_gap_by_white_rim(
    bg_bgr: np.ndarray,
    block_w: int,
    skip: int,
) -> tuple[int | None, float, list[tuple[int, float]]]:
    """Detect puzzle hole via bright white outline ring on the background image."""
    scores = _white_rim_scores(bg_bgr, block_w, skip)
    if not scores:
        return None, 0.0, scores
    gap_x_float, best_score = _subpixel_peak_from_scores(scores)
    if best_score < 35.0:
        return None, best_score, scores
    return int(round(gap_x_float)), best_score, scores


def _detect_gap_global_scan(bg_gray: np.ndarray, block_w: int) -> int:
    w = bg_gray.shape[1]
    margin = _search_margin(block_w, w)
    best_x = margin
    best_score = -1.0
    for x in range(margin, w - block_w - 2):
        score = _combined_score_at_x(bg_gray, block_w, x)
        if score > best_score:
            best_score = score
            best_x = x
    return int(best_x)


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


def _detect_by_masked_template(
    bg_gray: np.ndarray,
    puzzle_gray: np.ndarray,
    mask: np.ndarray | None,
    skip: int,
) -> int | None:
    bg = _enhance_gray(bg_gray)
    tmpl = _enhance_gray(puzzle_gray)
    if mask is not None and mask.any():
        result = cv2.matchTemplate(bg, tmpl, cv2.TM_CCORR_NORMED, mask=mask)
    else:
        result = cv2.matchTemplate(bg, tmpl, cv2.TM_CCOEFF_NORMED)
    if skip < result.shape[1]:
        result[:, :skip] = -1.0
    _min, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    if max_val > 0.28:
        return int(max_loc[0])
    return None


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
    edge_x = _detect_hole_by_edge_pair(bg_gray, block_w)
    global_x = _detect_gap_global_scan(bg_gray, block_w)
    method_scores["notch"] = notch_x
    method_scores["edge_pair"] = edge_x
    method_scores["global"] = global_x
    votes.extend([(notch_x, 2.5), (edge_x, 2.2), (global_x, 2.0)])

    hole_diff_x: int | None = None
    hole_scores: list[tuple[int, float]] = []
    hole_diff_strength = 0.0
    alternates: list[float] = []
    if puzzle_gray is not None:
        hole_diff_x, hole_diff_strength, hole_scores = _detect_gap_by_hole_fill_diff(
            bg_gray, puzzle_gray, mask, block_w, skip
        )
        method_scores["hole_diff"] = hole_diff_x
        method_scores["hole_strength"] = int(hole_diff_strength)
        votes.append((hole_diff_x, 6.0 + min(hole_diff_strength / 35.0, 2.0)))

        for px, ps in _top_peaks_from_scores(hole_scores, top_k=3)[1:]:
            alternates.append(px)
            votes.append((int(round(px)), 2.5 + min(ps / hole_diff_strength, 1.0) * 1.5))

        tmpl_x = _detect_by_masked_template(bg_gray, puzzle_gray, mask, skip)
        if tmpl_x is not None:
            method_scores["masked_template"] = tmpl_x
            if abs(tmpl_x - hole_diff_x) <= 12:
                votes.append((tmpl_x, 4.5))
            elif hole_diff_strength < 25:
                votes.append((tmpl_x, 3.0))

        align_x = _detect_by_puzzle_edge_align(bg_gray, puzzle_gray, mask, block_w, skip)
        if align_x is not None:
            method_scores["puzzle_edge_align"] = align_x
            votes.append((align_x, 2.8))

    hole_skip = _hole_search_skip(block_w, bg_gray.shape[1])

    white_x: int | None = None
    white_scores: list[tuple[int, float]] = []
    white_strength = 0.0
    white_x_float = 0.0
    white_x, white_strength, white_scores = _detect_gap_by_white_hole(
        background,
        block_w,
        hole_skip,
        puzzle_gray=puzzle_gray,
        mask=mask,
    )
    if white_scores:
        white_x_float, _ = _subpixel_peak_from_scores(white_scores)
        if white_x is None and white_strength >= 4200.0:
            white_x = int(round(white_x_float))

    blob_x = _detect_gap_by_white_blob(background, block_w, hole_skip)
    if blob_x is not None:
        method_scores["white_blob"] = blob_x
        votes.append((blob_x, 7.5))
        if white_x is not None and abs(blob_x - white_x) <= 16:
            white_x_float = (white_x_float + blob_x) / 2.0
            white_x = int(round(white_x_float))
        elif white_x is None:
            white_x = blob_x
            white_x_float = float(blob_x)
            white_strength = 5000.0

    if white_x is not None:
        method_scores["white_hole"] = white_x
        method_scores["white_strength"] = int(white_strength)
        votes.append((white_x, 9.0 + min(white_strength / 5000.0, 2.0)))
        for px, ps in _top_peaks_from_scores(white_scores, top_k=3)[1:]:
            alternates.append(px)
            votes.append((int(round(px)), 3.0 + min(ps / max(white_strength, 1.0), 1.0) * 2.0))

    primary = [x for x in (white_x, hole_diff_x, notch_x, edge_x) if x is not None]
    if len(primary) >= 2:
        spread = max(primary) - min(primary)
    else:
        spread = 999

    strong_white = white_x is not None and white_strength >= 4200.0
    if strong_white:
        gap_x_float = white_x_float if white_scores else float(white_x)
        rough_x = int(round(gap_x_float))
        if blob_x is not None and abs(blob_x - rough_x) <= 12:
            gap_x_float = (gap_x_float + blob_x) / 2.0
            rough_x = int(round(gap_x_float))
        method_scores["primary"] = rough_x
        method = "white_hole"
    else:
        method = "ensemble"
        strong_hole = hole_diff_x is not None and hole_diff_strength >= 18.0
        if strong_hole:
            peers = [
                x
                for x in (white_x, notch_x, edge_x, method_scores.get("masked_template"))
                if x is not None
            ]
            if sum(1 for x in peers if abs(x - hole_diff_x) > 24) >= 2:
                strong_hole = False
        if strong_hole:
            rough_x = hole_diff_x
            if white_x is not None and abs(white_x - hole_diff_x) <= 14:
                rough_x = int(round((hole_diff_x + white_x) / 2))
            elif tmpl := method_scores.get("masked_template"):
                if abs(tmpl - hole_diff_x) <= 10:
                    rough_x = int(round((hole_diff_x + tmpl) / 2))
            method_scores["primary"] = rough_x
            if hole_scores:
                gap_x_float, _ = _subpixel_peak_from_scores(hole_scores)
            else:
                gap_x_float = refine_gap_subpixel(bg_gray, block_w, rough_x, window=24)
        elif white_x is not None:
            gap_x_float = white_x_float if white_scores else float(white_x)
            rough_x = int(round(gap_x_float))
            method_scores["primary"] = rough_x
            method = "white_hole"
        elif spread <= 18 and hole_diff_x is not None:
            rough_x = hole_diff_x
            if white_x is not None and abs(white_x - hole_diff_x) <= 14:
                rough_x = int(round((hole_diff_x + white_x) / 2))
            method_scores["primary"] = rough_x
            gap_x_float = refine_gap_subpixel(bg_gray, block_w, rough_x, window=28)
        elif spread <= 12:
            rough_x = int(round(sum(primary) / len(primary)))
            method_scores["primary"] = rough_x
            gap_x_float = refine_gap_subpixel(bg_gray, block_w, rough_x, window=28)
        else:
            rough_x = _vote_gap(votes)
            rough_x = max(skip, min(rough_x, bg_gray.shape[1] - block_w - 2))
            gap_x_float = refine_gap_subpixel(bg_gray, block_w, rough_x, window=32)

    gap_x = int(round(gap_x_float))
    method_scores["refined"] = gap_x

    agree = sum(1 for x in primary if abs(x - gap_x) <= 14)
    confidence = 0.2 + agree * 0.08
    if strong_white:
        confidence += 0.48
    elif white_x is not None and abs(white_x - gap_x) <= 6:
        confidence += 0.28
    if hole_diff_x is not None and abs(hole_diff_x - gap_x) <= 8:
        confidence += 0.08
    if spread <= 18:
        confidence += 0.08

    alt_tuple = tuple(
        sorted(
            {float(a) for a in alternates if abs(a - gap_x_float) >= 8.0},
            key=lambda v: abs(v - gap_x_float),
        )[:2]
    )

    return GapDetectionResult(
        gap_x=gap_x,
        gap_x_float=gap_x_float,
        confidence=min(confidence, 1.0),
        method=method,
        candidates=method_scores,
        alternates=alt_tuple,
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

    steps = max(32, min(72, int(move / 2.0) or 32))
    for i in range(1, steps + 1):
        t = i / steps
        # Slow ease-in-out: precise landing on last pixels
        ease = 3.0 * t * t - 2.0 * t * t * t
        cx = start_x + move * ease
        wobble = 0.8 * np.sin(t * np.pi * 2.0) * (1.0 - t)
        page.mouse.move(cx, start_y + wobble)
        delay = 18 - int(12 * ease)
        page.wait_for_timeout(max(5, delay))

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
    # Stale offset reads should not skip a real drag.
    if abs(delta) < 2 and target > 6:
        before = 0.0
        delta = target

    if abs(delta) < 1:
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
    if ti in seen or ti < 1 or ti > track_travel:
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


def expand_targets_from_gap_x(
    targets: list[float],
    seen: set[int],
    gap_x: float,
    *,
    bg_width: int,
    block_width: int,
    track_width: float,
    handle_width: float,
    offset_px: float,
    track_travel: float,
) -> None:
    """Nudge around a gap estimate in image px (original detection or block landing)."""
    for delta in ADAPTIVE_GAP_STEPS:
        dist = compute_drag_distance(
            max(0.0, gap_x + delta),
            bg_width=bg_width,
            block_width=block_width,
            track_width=track_width,
            handle_width=handle_width,
            offset_px=offset_px,
        )
        _add_target(targets, seen, dist, track_travel)


def expand_targets_from_block_landing(
    targets: list[float],
    seen: set[int],
    block_left: float,
    *,
    bg_width: int,
    block_width: int,
    track_width: float,
    handle_width: float,
    offset_px: float,
    track_travel: float,
) -> None:
    """After a near-miss, nudge in image px around where the puzzle piece landed."""
    expand_targets_from_gap_x(
        targets,
        seen,
        block_left,
        bg_width=bg_width,
        block_width=block_width,
        track_width=track_width,
        handle_width=handle_width,
        offset_px=offset_px,
        track_travel=track_travel,
    )


def build_detection_targets(
    detail: GapDetectionResult,
    layout: CaptchaLayout,
    *,
    track_travel: float,
) -> list[float]:
    """Slider targets from primary gap + alternate peaks."""
    bg_w = layout.bg_width
    tw = layout.track_width or layout.bg_box_width
    seen: set[int] = set()
    targets: list[float] = []
    gap_values = [detail.gap_x_float, *detail.alternates]
    for gap in gap_values:
        dist = compute_drag_distance(
            gap,
            bg_width=bg_w,
            block_width=layout.block_width,
            track_width=tw,
            handle_width=layout.handle_width,
            offset_px=layout.offset_px,
        )
        _add_target(targets, seen, dist, track_travel)
        for step in (12, -12, 8, -8, 5, -5, 3, -3):
            _add_target(targets, seen, dist + step, track_travel)
    return targets


def expand_targets_from_landing(
    targets: list[float],
    seen: set[int],
    landed_slider: float,
    track_travel: float,
) -> None:
    """Fallback when block.left is unavailable."""
    for step in ADAPTIVE_FAIL_STEPS:
        _add_target(targets, seen, landed_slider + step, track_travel)


def ensure_slider_block_reset(page, handle_locator, scope) -> bool:
    """Reset slider to start; return False if puzzle block did not return left."""
    reset_slider_position(page, handle_locator, scope=scope)
    page.wait_for_timeout(350)
    return read_block_left(scope) < 8


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
