"""Image quality assessment - blur, glare, resolution, angle checks."""

import cv2
import numpy as np

from ..config import get_settings


def assess_quality(image_path: str) -> dict:
    """Assess image quality and return structured quality report."""
    settings = get_settings()
    img = cv2.imread(image_path)
    if img is None:
        return {
            "is_readable": False,
            "blur_score": 0.0,
            "glare_detected": False,
            "angle_ok": False,
            "resolution_ok": False,
            "issues": ["Could not read image file"],
        }

    issues = []
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    is_blurry = bool(blur_score < settings.blur_threshold)
    if is_blurry:
        issues.append(f"Image is too blurry (score: {blur_score:.1f}, min: {settings.blur_threshold})")

    # Glare detection - check for overexposed regions
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
    glare_ratio = np.sum(thresh == 255) / thresh.size
    glare_detected = glare_ratio > 0.05
    if glare_detected:
        issues.append(f"Glare detected ({glare_ratio*100:.1f}% overexposed)")

    # Resolution check
    resolution_ok = w >= settings.min_resolution_width and h >= settings.min_resolution_height
    if not resolution_ok:
        issues.append(f"Resolution too low ({w}x{h}), minimum {settings.min_resolution_width}x{settings.min_resolution_height}")

    # Angle check - detect document edges via Hough transform
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)
    angle_ok = True
    if lines is not None:
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            angles.append(angle)
        if angles:
            median_angle = np.median(angles)
            # Check if document is roughly aligned (within 15 degrees of horizontal/vertical)
            angle_ok = (median_angle < 15) or (abs(median_angle - 90) < 15) or (abs(median_angle - 180) < 15)
            if not angle_ok:
                issues.append(f"Document appears skewed (angle: {median_angle:.1f} degrees)")

    is_readable = not is_blurry and not glare_detected and resolution_ok

    return {
        "is_readable": is_readable,
        "blur_score": round(blur_score, 2),
        "glare_detected": glare_detected,
        "angle_ok": angle_ok,
        "resolution_ok": resolution_ok,
        "issues": issues,
    }
