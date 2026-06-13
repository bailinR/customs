"""Tests for GACC slider gap detection."""

from __future__ import annotations

import cv2
import numpy as np

from gacc_slider_solver import (
    build_drag_track,
    compute_drag_distance,
    detect_gap_x,
    detect_gap_x_detailed,
    iter_fine_tune_targets,
    refine_gap_x,
)


def test_detect_gap_x_with_template() -> None:
    background = np.zeros((120, 320, 3), dtype=np.uint8)
    cv2.rectangle(background, (20, 30), (60, 90), (40, 120, 200), -1)
    cv2.rectangle(background, (150, 30), (190, 90), (40, 120, 200), -1)
    cv2.rectangle(background, (150, 30), (190, 90), (255, 255, 255), 2)
    puzzle = background[30:90, 20:60].copy()
    gap = detect_gap_x(background, puzzle)
    assert gap > 40
    assert gap != 20


def test_detect_gap_x_with_edges() -> None:
    background = np.full((100, 300, 3), 200, dtype=np.uint8)
    cv2.rectangle(background, (120, 20), (170, 80), (30, 30, 30), 2)
    gap = detect_gap_x(background, None)
    assert 100 <= gap <= 190


def test_detect_hole_notch_finds_dark_slot() -> None:
    background = np.full((155, 310, 3), 180, dtype=np.uint8)
    # Simulate puzzle hole: darker interior + white borders
    hole_x = 128
    cv2.rectangle(background, (hole_x, 30), (hole_x + 62, 125), (90, 90, 90), -1)
    cv2.rectangle(background, (hole_x, 30), (hole_x + 62, 125), (255, 255, 255), 2)
    detail = detect_gap_x_detailed(background, None)
    assert abs(detail.gap_x - hole_x) <= 18


def test_refine_gap_x_local_peak() -> None:
    background = np.full((155, 310, 3), 180, dtype=np.uint8)
    hole_x = 142
    cv2.rectangle(background, (hole_x, 30), (hole_x + 62, 125), (85, 85, 85), -1)
    cv2.rectangle(background, (hole_x, 30), (hole_x + 62, 125), (255, 255, 255), 2)
    bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
    refined = refine_gap_x(bg_gray, 62, hole_x + 9)
    assert abs(refined - hole_x) <= 4


def test_iter_fine_tune_targets() -> None:
    targets = iter_fine_tune_targets(130.0, 270.0)
    assert targets
    assert all(abs(t - 130.0) <= 26 for t in targets)
    assert 133 in [int(round(t)) for t in targets]
    # gap at 124px on image → slider = 124 * 270/248 ≈ 135
    distance = compute_drag_distance(
        124,
        bg_width=310,
        block_width=62,
        track_width=310,
        handle_width=40,
    )
    assert 125 <= distance <= 145


def test_build_drag_track_reaches_target() -> None:
    track = build_drag_track(180)
    assert track[-1] == 180
    assert len(track) >= 1
