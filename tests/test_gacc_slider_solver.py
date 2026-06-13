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
    puzzle_block_width,
    refine_gap_x,
)


def _draw_pure_white_hole(
    background: np.ndarray,
    hole_x: int,
    *,
    hole_w: int = 62,
    y0: int = 30,
    y1: int = 125,
) -> None:
    cv2.rectangle(background, (hole_x, y0), (hole_x + hole_w, y1), (255, 255, 255), -1)


def test_white_hole_finds_pure_white_gap() -> None:
    background = np.full((155, 310, 3), 120, dtype=np.uint8)
    hole_x = 136
    _draw_pure_white_hole(background, hole_x)
    puzzle = np.zeros((155, 62, 4), dtype=np.uint8)
    puzzle[:, :, :3] = 80
    puzzle[:, :, 3] = 255
    puzzle[20:135, 5:57, 3] = 255
    detail = detect_gap_x_detailed(background, puzzle)
    assert detail.method == "white_hole"
    assert abs(detail.gap_x - hole_x) <= 10


def test_full_canvas_puzzle_crops_to_piece() -> None:
    background = np.full((155, 310, 3), 110, dtype=np.uint8)
    hole_x = 148
    _draw_pure_white_hole(background, hole_x)
    puzzle = np.zeros((155, 310, 4), dtype=np.uint8)
    puzzle[30:125, 0:62, :3] = 80
    puzzle[30:125, 0:62, 3] = 255
    assert puzzle_block_width(puzzle) == 62
    detail = detect_gap_x_detailed(background, puzzle)
    assert detail.method == "white_hole"
    assert abs(detail.gap_x - hole_x) <= 12


def test_white_hole_is_primary_method() -> None:
    background = np.full((155, 310, 3), 100, dtype=np.uint8)
    hole_x = 152
    _draw_pure_white_hole(background, hole_x)
    detail = detect_gap_x_detailed(background, None)
    assert detail.method == "white_hole"
    assert abs(detail.gap_x - hole_x) <= 10


def test_detect_gap_x_with_template() -> None:
    background = np.zeros((120, 320, 3), dtype=np.uint8)
    cv2.rectangle(background, (20, 30), (60, 90), (40, 120, 200), -1)
    cv2.rectangle(background, (150, 30), (190, 90), (255, 255, 255), -1)
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
    assert all(abs(t - 130.0) <= 22 for t in targets)
    assert 131 in [int(round(t)) for t in targets]
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
