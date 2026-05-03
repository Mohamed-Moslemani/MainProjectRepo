"""Document presentation-attack detection.

Catches the canonical "citizen took a photo of a document being shown
on a phone/laptop screen instead of the physical document" attack via
three independent signals — each looking at a different artifact a
display introduces but real paper/plastic doesn't:

  1. Moiré fringes — the camera's pixel grid beats against the
     display's pixel grid, producing characteristic peaks in the
     mid-frequency band of the image's 2D power spectrum.
  2. Horizontal banding — the camera's rolling shutter samples the
     display's refresh in horizontal slices. Real handheld captures
     have row-luminance jitter; screen captures show repeating
     bands at the refresh-vs-shutter beat frequency.
  3. Chromatic fringing on edges — RGB stripe sub-pixel layout
     bleeds color along high-contrast edges. CMYK-printed docs
     don't (or bleed differently).

Each detector returns a score in [0, 1] where higher = more screen-
like. We combine them via a max-weighted average, then map the
final score to a coarse decision (`clean | suspicious | likely_spoof`).

Important: NOTHING here hard-rejects. The orchestrator's risk
engine consumes `spoof_score` as one input among many and routes
borderline cases to manual review, the same way it does for OCR
confidence and reconciliation. False positives on textured paper
(some glossy stock, holograms) are real and we don't want to bounce
legitimate citizens. Manual review handles the long tail.

Cost: ~80ms per image on a typical 1500x1000 capture (mostly the
FFT). All work is local; no network calls. Fails open — any
exception logs and returns a clean verdict so a detector bug never
blocks the pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# Score thresholds. Tuned to be permissive on phone captures of real
# Lebanese ID cards (we'd rather miss attacks than false-positive
# legit citizens — manual review catches what we miss). Override via
# OCR_SPOOF_* env vars when calibration data shows otherwise.
SUSPICIOUS_THRESHOLD = 0.55
LIKELY_SPOOF_THRESHOLD = 0.75

# Per-detector weights into the combined score. Moiré is the strongest
# single signal in the literature, hence the heavier weight.
WEIGHTS = {
    "moire": 0.50,
    "banding": 0.30,
    "chromatic": 0.20,
}


def detect_spoof(image_path: str) -> dict[str, Any]:
    """Run every available spoof detector and return a combined verdict.

    Returns a dict shaped like:
        {
          "spoof_score": float in [0, 1],     # combined
          "decision": "clean"|"suspicious"|"likely_spoof",
          "components": {
              "moire": {"score": ..., "reason": "..."},
              "banding": {"score": ..., "reason": "..."},
              "chromatic": {"score": ..., "reason": "..."},
          },
          "errors": [...]   # any detector that failed; pipeline keeps going
        }
    """
    components: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    img = cv2.imread(image_path)
    if img is None:
        return {
            "spoof_score": 0.0,
            "decision": "clean",
            "components": {},
            "errors": ["could not read image"],
        }

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    for name, fn in (
        ("moire", _moire_score),
        ("banding", _banding_score),
        ("chromatic", _chromatic_score),
    ):
        try:
            score, reason = fn(img if name == "chromatic" else gray)
            components[name] = {"score": round(float(score), 4), "reason": reason}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            logger.warning("spoof detector %s failed: %s", name, exc)
            components[name] = {"score": 0.0, "reason": "detector_failed"}

    combined = 0.0
    weight_sum = 0.0
    for name, w in WEIGHTS.items():
        if name in components:
            combined += components[name]["score"] * w
            weight_sum += w
    if weight_sum > 0:
        combined /= weight_sum

    if combined >= LIKELY_SPOOF_THRESHOLD:
        decision = "likely_spoof"
    elif combined >= SUSPICIOUS_THRESHOLD:
        decision = "suspicious"
    else:
        decision = "clean"

    return {
        "spoof_score": round(float(combined), 4),
        "decision": decision,
        "components": components,
        "errors": errors,
    }


# ── Moiré: 2D FFT mid-band peak-to-mean ratio ──────────────────────
def _moire_score(gray: np.ndarray) -> tuple[float, str]:
    """Look for moiré beat fringes in the 2D power spectrum.

    Real photos have a smooth 1/f-like decay. Screen captures show
    sharp peaks where the camera's sampling grid beats with the
    display's pixel grid — these land in a normalized-frequency band
    roughly [0.10, 0.40]. We pull that band's max-to-mean ratio: a
    value > ~6 is hard to explain without a periodic interference
    pattern, i.e. a screen.
    """
    # Downsample so the FFT is fast on big captures and the moiré
    # peaks (which are below the sub-pixel scale) still survive.
    h, w = gray.shape
    scale = 512 / max(h, w)
    if scale < 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_AREA)

    # Hann window to suppress edge ringing in the spectrum.
    h2, w2 = gray.shape
    window = np.outer(np.hanning(h2), np.hanning(w2))
    f = np.fft.fft2(gray.astype(np.float64) * window)
    mag = np.abs(np.fft.fftshift(f))
    # Log so the 1/f decay doesn't dominate dynamic range
    spec = np.log1p(mag)

    # Build a radial mask for the mid-frequency annulus.
    cy, cx = h2 // 2, w2 // 2
    yy, xx = np.indices(spec.shape)
    r = np.hypot(yy - cy, xx - cx)
    r_max = min(cy, cx)
    inner = 0.10 * r_max
    outer = 0.40 * r_max
    band = (r >= inner) & (r <= outer)

    band_vals = spec[band]
    if band_vals.size == 0:
        return 0.0, "spectrum_too_small"

    peak_to_mean = float(band_vals.max() / (band_vals.mean() + 1e-9))
    # Empirical mapping: real captures sit around 3–5, clean screen
    # captures around 7–12. Squash to [0, 1] with a sigmoid-ish curve.
    score = max(0.0, min(1.0, (peak_to_mean - 4.0) / 6.0))
    return score, f"peak_to_mean={peak_to_mean:.2f}"


# ── Banding: row-luminance periodicity from rolling shutter × refresh
def _banding_score(gray: np.ndarray) -> tuple[float, str]:
    """Detect repeating horizontal luminance bands.

    Phone cameras read the sensor row-by-row (rolling shutter); a
    refreshing display lights pixels in horizontal sweeps at 60–120
    Hz. The two together imprint a repeating brightness modulation
    on the captured image. Hand-held real captures don't have any
    such periodic structure in their row-mean signal.
    """
    row_mean = gray.mean(axis=1).astype(np.float64)
    # Detrend with a long moving average so we measure short-period
    # ripple, not the doc's overall light gradient.
    win = max(11, len(row_mean) // 20 | 1)  # odd
    kernel = np.ones(win) / win
    trend = np.convolve(row_mean, kernel, mode="same")
    detrended = row_mean - trend

    if len(detrended) < 32:
        return 0.0, "too_short"

    # FFT of the detrended row signal. A clean banding pattern shows
    # a single dominant peak at the beat frequency; real handheld
    # noise spreads across the spectrum.
    spec = np.abs(np.fft.rfft(detrended * np.hanning(len(detrended))))
    # Ignore the DC bin and the first few low-frequency bins (those
    # represent slow light gradients we couldn't fully detrend).
    spec_meaningful = spec[3:]
    if spec_meaningful.size == 0:
        return 0.0, "no_meaningful_bins"

    peak = float(spec_meaningful.max())
    mean = float(spec_meaningful.mean() + 1e-9)
    ratio = peak / mean
    # Real handheld photos cluster around 4–8; screen captures land
    # at 12–30 in our small calibration set.
    score = max(0.0, min(1.0, (ratio - 8.0) / 16.0))
    return score, f"row_peak_to_mean={ratio:.2f}"


# ── Chromatic fringing on high-contrast edges ──────────────────────
def _chromatic_score(img: np.ndarray) -> tuple[float, str]:
    """Measure RGB channel mis-registration at edges.

    A screen's RGB stripe sub-pixel layout (or pentile, depending on
    the panel) means that when a camera resolves a high-contrast
    black-on-white edge, the red and blue channels land slightly
    offset from each other. Real CMYK prints don't — their colour
    is overlaid in the same physical spot per dot.

    We compute a Sobel edge map on the green channel (sharpest in
    Bayer cameras), then for each edge pixel look at the absolute
    difference between R and B channel gradients at that location.
    A high mean indicates lateral chromatic shift = screen capture.
    """
    if img.ndim != 3 or img.shape[2] != 3:
        return 0.0, "not_color"

    b, g, r = cv2.split(img.astype(np.float32))

    # Sobel on green to locate edges
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    gmag = np.hypot(gx, gy)
    if gmag.max() < 1e-6:
        return 0.0, "flat_image"
    edge_mask = gmag > (np.percentile(gmag, 95))  # top 5% strongest
    if edge_mask.sum() == 0:
        return 0.0, "no_edges"

    # Sobel on R and B and compare their direction sign
    rx = cv2.Sobel(r, cv2.CV_32F, 1, 0, ksize=3)
    bx = cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3)
    # Lateral mismatch: where R and B gradient signs disagree at
    # edge pixels, there's color fringing.
    sign_disagree = (np.sign(rx) != np.sign(bx)) & edge_mask
    fraction = float(sign_disagree.sum()) / float(edge_mask.sum())
    # Real prints land at 0.05–0.15. Screen captures at 0.25–0.50.
    score = max(0.0, min(1.0, (fraction - 0.15) / 0.30))
    return score, f"sign_disagree_frac={fraction:.3f}"
