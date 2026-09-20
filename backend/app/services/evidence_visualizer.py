from __future__ import annotations

import base64
import io

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..domain.schemas import RansacResult, SiftResult


def _data_url(image: Image.Image) -> str:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _fit(image: Image.Image, max_height: int = 620) -> tuple[Image.Image, float]:
    scale = min(1.0, max_height / max(1, image.height))
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS), scale


def render_aligned_pair(first: Image.Image, second: Image.Image) -> str:
    """Render the exact pair orientation used by downstream verification."""
    left, _ = _fit(first.convert("RGB"))
    right, _ = _fit(second.convert("RGB"))
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width, height), "#111827")
    canvas.paste(left, (0, (height - left.height) // 2))
    canvas.paste(right, (left.width, (height - right.height) // 2))
    return _data_url(canvas)


def render_verified_matches(
    first: Image.Image,
    second: Image.Image,
    matches: SiftResult,
    ransac: RansacResult,
    max_lines: int = 40,
) -> str | None:
    indexes = [index for index, accepted in enumerate(ransac.inlier_mask) if accepted]
    if not indexes:
        return None
    if len(indexes) > max_lines:
        positions = np.linspace(0, len(indexes) - 1, max_lines, dtype=int)
        indexes = [indexes[index] for index in positions]
    left, _ = _fit(first.convert("RGB"))
    right, _ = _fit(second.convert("RGB"))
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width, height), "#111827")
    canvas.paste(left, (0, (height - left.height) // 2))
    canvas.paste(right, (left.width, (height - right.height) // 2))
    draw = ImageDraw.Draw(canvas, "RGBA")
    source_w, source_h = matches.image_size_a
    target_w, target_h = matches.image_size_b
    left_y = (height - left.height) // 2
    right_y = (height - right.height) // 2
    for index in indexes:
        ax, ay = matches.points_a[index]
        bx, by = matches.points_b[index]
        point_a = (float(ax) / source_w * left.width, float(ay) / source_h * left.height + left_y)
        point_b = (float(bx) / target_w * right.width + left.width, float(by) / target_h * right.height + right_y)
        draw.line((point_a, point_b), fill=(34, 197, 94, 150), width=2)
        for x, y in (point_a, point_b):
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(22, 163, 74, 230), outline=(255, 255, 255, 220))
    return _data_url(canvas)


def _mask_overlay(image: Image.Image, masks: dict[str, np.ndarray]) -> Image.Image:
    fitted, _ = _fit(image.convert("RGB"))
    fitted_array = np.asarray(fitted).copy()
    colors = {
        "head": (239, 68, 68), "neck": (249, 115, 22), "torso": (37, 99, 235),
        "uarm": (168, 85, 247), "larm": (217, 70, 239), "hand": (236, 72, 153),
        "uleg": (20, 184, 166), "lleg": (34, 197, 94), "foot": (132, 204, 22),
    }
    for label, raw_mask in masks.items():
        mask = Image.fromarray(raw_mask.astype(np.uint8) * 255).resize(fitted.size, Image.Resampling.NEAREST)
        selected = np.asarray(mask) > 0
        color = np.asarray(colors.get(label, (14, 165, 233)), dtype=np.float32)
        fitted_array[selected] = (fitted_array[selected] * 0.55 + color * 0.45).astype(np.uint8)
    return Image.fromarray(fitted_array)


def render_body_masks(
    first: Image.Image,
    second: Image.Image,
    masks_a: dict[str, np.ndarray],
    masks_b: dict[str, np.ndarray],
) -> str | None:
    if not masks_a and not masks_b:
        return None
    left, right = _mask_overlay(first, masks_a), _mask_overlay(second, masks_b)
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + right.width, height), "#111827")
    canvas.paste(left, (0, (height - left.height) // 2))
    canvas.paste(right, (left.width, (height - right.height) // 2))
    return _data_url(canvas)


def render_change_heatmap(
    first: Image.Image,
    second: Image.Image,
    matches: SiftResult,
    alignment: RansacResult,
    foreground_mask_a: np.ndarray,
    foreground_mask_b: np.ndarray,
    include_image: bool = True,
) -> tuple[str | None, float | None, float | None]:
    """Measure aligned pixel changes and optionally render the diagnostic image."""
    if alignment.transform_matrix is None or not alignment.homography_found:
        return None, None, None
    width_a, height_a = matches.image_size_a
    width_b, height_b = matches.image_size_b
    if min(width_a, height_a, width_b, height_b) <= 0:
        return None, None, None
    image_a = np.asarray(first.resize((width_a, height_a), Image.Resampling.LANCZOS).convert("RGB"))
    image_b = np.asarray(second.resize((width_b, height_b), Image.Resampling.LANCZOS).convert("RGB"))
    try:
        inverse = np.linalg.inv(np.asarray(alignment.transform_matrix, dtype=np.float64))
    except np.linalg.LinAlgError:
        return None, None, None
    def aligned_change(
        reference: np.ndarray,
        target: np.ndarray,
        target_to_reference: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        height, width = reference.shape[:2]
        aligned = cv2.warpPerspective(target, target_to_reference, (width, height), flags=cv2.INTER_LINEAR)
        valid_area = cv2.warpPerspective(
            np.full(target.shape[:2], 255, dtype=np.uint8),
            target_to_reference,
            (width, height),
            flags=cv2.INTER_NEAREST,
        )
        gray_reference = cv2.equalizeHist(
            cv2.GaussianBlur(cv2.cvtColor(reference, cv2.COLOR_RGB2GRAY), (5, 5), 0)
        )
        gray_aligned = cv2.equalizeHist(
            cv2.GaussianBlur(cv2.cvtColor(aligned, cv2.COLOR_RGB2GRAY), (5, 5), 0)
        )
        difference = cv2.absdiff(gray_reference, gray_aligned)
        changed_area = np.where((difference >= 32) & (valid_area > 0), 255, 0).astype(np.uint8)
        changed_area = cv2.morphologyEx(changed_area, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
        changed_area = cv2.morphologyEx(changed_area, cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8))
        return changed_area, valid_area

    matrix = np.asarray(alignment.transform_matrix, dtype=np.float64)
    changed, valid = aligned_change(image_a, image_b, inverse)
    changed_reverse, valid_reverse = aligned_change(image_b, image_a, matrix)
    foreground_a = cv2.resize(
        foreground_mask_a.astype(np.uint8), (width_a, height_a), interpolation=cv2.INTER_NEAREST
    ) > 0
    foreground_b = cv2.resize(
        foreground_mask_b.astype(np.uint8), (width_b, height_b), interpolation=cv2.INTER_NEAREST
    ) > 0

    def fraction(changed_area: np.ndarray, valid_area: np.ndarray, region: np.ndarray) -> float | None:
        active = region & (valid_area > 0)
        count = int(active.sum())
        return None if count == 0 else float(((changed_area > 0) & active).sum() / count)

    def average(first_value: float | None, second_value: float | None) -> float | None:
        values = [value for value in (first_value, second_value) if value is not None]
        return None if not values else sum(values) / len(values)

    foreground_change = average(
        fraction(changed, valid, foreground_a),
        fraction(changed_reverse, valid_reverse, foreground_b),
    )
    background_change = average(
        fraction(changed, valid, ~foreground_a),
        fraction(changed_reverse, valid_reverse, ~foreground_b),
    )
    if not include_image:
        return None, foreground_change, background_change
    heat_bgr = cv2.applyColorMap(changed, cv2.COLORMAP_JET)
    heat_rgb = cv2.cvtColor(heat_bgr, cv2.COLOR_BGR2RGB)
    overlay = image_a.copy()
    selected = changed > 0
    overlay[selected] = (overlay[selected] * 0.5 + heat_rgb[selected] * 0.5).astype(np.uint8)
    overlay[valid == 0] = (overlay[valid == 0] * 0.25).astype(np.uint8)
    return _data_url(Image.fromarray(overlay)), foreground_change, background_change
