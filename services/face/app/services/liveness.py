
"""Liveness detection / anti-spoofing.

Uses image-based heuristics as a baseline. For production, integrate
AWS Rekognition Face Liveness or a dedicated liveness SDK.
"""

import cv2
import numpy as np
import logging

from ..config import get_settings
from .mocks import mock_assess_liveness

logger = logging.getLogger(__name__)


def assess_liveness(image_path: str) -> dict:
    if get_settings().mock_mode:
        return mock_assess_liveness(image_path)

    return _assess_liveness_impl(image_path)


def _assess_liveness_impl(image_path: str) -> dict:
    """Heuristic-based liveness scoring.

    Checks:
    - Texture analysis (LBP variance) to detect printed photos
    - Color distribution analysis to detect screen displays
    - Reflection/specular highlight detection
    - Edge frequency analysis

    Returns:
        {
            "liveness_score": float (0-1),
            "checks": {check_name: passed_bool, ...},
            "reasons": [str, ...],
        }
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"liveness_score": 0.0, "checks": {}, "reasons": ["Could not read image"]}

    checks = {}
    reasons = []
    scores = []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 1. Texture analysis - LBP variance (flat texture = printed/screen)
    def lbp_variance(image):
        rows, cols = image.shape
        lbp = np.zeros_like(image, dtype=np.uint8)
        for i in range(1, rows - 1):
            for j in range(1, cols - 1):
                center = image[i, j]
                code = 0
                code |= (image[i-1, j-1] >= center) << 7
                code |= (image[i-1, j] >= center) << 6
                code |= (image[i-1, j+1] >= center) << 5
                code |= (image[i, j+1] >= center) << 4
                code |= (image[i+1, j+1] >= center) << 3
                code |= (image[i+1, j] >= center) << 2
                code |= (image[i+1, j-1] >= center) << 1
                code |= (image[i, j-1] >= center) << 0
                lbp[i, j] = code
        return np.var(lbp)

    # Use a downsampled version for speed
    small_gray = cv2.resize(gray, (128, 128))
    texture_var = lbp_variance(small_gray)
    texture_ok = texture_var > 500
    checks["texture_analysis"] = texture_ok
    scores.append(min(texture_var / 2000, 1.0))
    if not texture_ok:
        reasons.append("Low texture variance - possible printed photo")

    # 2. Color distribution - real faces have natural skin color spread
    h_channel = hsv[:, :, 0]
    skin_mask = cv2.inRange(hsv, np.array([0, 20, 70]), np.array([20, 255, 255]))
    skin_ratio = np.sum(skin_mask > 0) / skin_mask.size
    color_ok = 0.05 < skin_ratio < 0.8
    checks["color_distribution"] = color_ok
    scores.append(1.0 if color_ok else 0.3)
    if not color_ok:
        reasons.append("Unusual skin color distribution")

    # 3. Specular reflection detection (screen glare)
    _, bright_spots = cv2.threshold(gray, 250, 255, cv2.THRESH_BINARY)
    bright_ratio = np.sum(bright_spots == 255) / bright_spots.size
    reflection_ok = bright_ratio < 0.02
    checks["reflection_check"] = reflection_ok
    scores.append(1.0 if reflection_ok else 0.2)
    if not reflection_ok:
        reasons.append("Specular reflections detected - possible screen display")

    # 4. Frequency analysis - screens have regular pixel patterns
    f_transform = np.fft.fft2(gray)
    f_shift = np.fft.fftshift(f_transform)
    magnitude = np.log(np.abs(f_shift) + 1)
    freq_std = np.std(magnitude)
    frequency_ok = freq_std > 1.5
    checks["frequency_analysis"] = frequency_ok
    scores.append(min(freq_std / 3.0, 1.0))
    if not frequency_ok:
        reasons.append("Regular frequency pattern detected - possible screen")

    liveness_score = sum(scores) / len(scores) if scores else 0.0

    return {
        "liveness_score": round(liveness_score, 4),
        "checks": checks,
        "reasons": reasons,
    }
