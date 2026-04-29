/**
 * Client-side image quality pre-flight, mirroring the backend gate in
 * services/ocr/app/services/quality.py. Catching obvious problems
 * before the upload saves the citizen a 30s pipeline round-trip and
 * keeps blurry photos out of the system entirely.
 *
 * Returns:
 *   { ok: boolean, issues: Array<{ code, ar, en, hint? }>, info: {...} }
 *
 * `code` is a stable identifier ('blurry' | 'low_resolution' | ...) so
 * upstream UI can map it to translated copy. `info` carries the raw
 * measurements (width, height, blur score, size in MB) for display.
 *
 * Thresholds intentionally a touch *looser* than the server-side ones:
 * a phone photo that just-barely passes here will still be re-checked
 * server-side against the canonical limits and bounced if it's truly
 * unreadable. Better to fast-pass borderline cases and let the server
 * decide than to falsely reject valid uploads on the client.
 */

const MAX_SIZE_MB = 10;
const ACCEPTED_MIME = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'application/pdf',
]);

// Backend uses 640x480 minimum; we relax to 480x360 client-side because
// real phone photos of LB passports come in at ~600x420 and the server
// gate is the source of truth.
const MIN_WIDTH = 480;
const MIN_HEIGHT = 360;

// Laplacian variance threshold. Backend uses 100; client uses 80 to be
// a bit more permissive (different downscaling, different filter).
const BLUR_THRESHOLD = 80;

// Glare cap. Backend uses 5%; client uses 30% — only catch *severe*
// glare on the client. Mild glare often still parses fine and we don't
// want to reject good photos.
const GLARE_RATIO_THRESHOLD = 0.30;

const ISSUE = {
  invalid_mime: {
    ar: 'صيغة الملف غير مدعومة. استخدم JPG أو PNG أو WEBP أو PDF.',
    en: 'Unsupported file format. Use JPG, PNG, WEBP, or PDF.',
  },
  too_large: {
    ar: `حجم الملف كبير جداً. الحد الأقصى ${MAX_SIZE_MB} ميغابايت.`,
    en: `File too large. Maximum is ${MAX_SIZE_MB} MB.`,
  },
  low_resolution: {
    ar: 'دقة الصورة منخفضة. اقترب من المستند أو استخدم كاميرا أوضح.',
    en: 'Image resolution too low. Move closer to the document or use a sharper camera.',
  },
  blurry: {
    ar: 'الصورة غير واضحة. ثبّت الكاميرا وتأكد من التركيز قبل التصوير.',
    en: 'Image is blurry. Hold the camera steady and tap to focus before shooting.',
  },
  glare: {
    ar: 'يوجد انعكاس قوي على المستند. ابتعد عن الإضاءة المباشرة وأطفئ الفلاش.',
    en: 'Strong glare on the document. Move away from direct lights and turn off the flash.',
  },
  load_failed: {
    ar: 'تعذر قراءة الصورة. حاول مرة أخرى.',
    en: 'Could not read the image. Try again.',
  },
};

function makeIssue(code, hint) {
  return { code, ar: ISSUE[code].ar, en: ISSUE[code].en, hint };
}

function loadImageElement(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve({ img, url });
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('image load failed'));
    };
    img.src = url;
  });
}

function laplacianVariance(canvas) {
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  const { data } = ctx.getImageData(0, 0, width, height);

  // Convert to grayscale luminance
  const gray = new Float32Array(width * height);
  for (let i = 0; i < gray.length; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    gray[i] = 0.299 * r + 0.587 * g + 0.114 * b;
  }

  // 3x3 Laplacian kernel: [0,1,0; 1,-4,1; 0,1,0]
  // Compute variance of the response — same idea as cv2.Laplacian().var().
  const responses = [];
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const v =
        gray[i - width] +
        gray[i + width] +
        gray[i - 1] +
        gray[i + 1] -
        4 * gray[i];
      responses.push(v);
    }
  }
  if (responses.length === 0) return 0;

  let mean = 0;
  for (const v of responses) mean += v;
  mean /= responses.length;

  let varSum = 0;
  for (const v of responses) {
    const d = v - mean;
    varSum += d * d;
  }
  return varSum / responses.length;
}

function glareRatio(canvas) {
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  const { data } = ctx.getImageData(0, 0, width, height);
  let bright = 0;
  const total = width * height;
  for (let i = 0; i < total; i++) {
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    const lum = 0.299 * r + 0.587 * g + 0.114 * b;
    if (lum > 240) bright++;
  }
  return bright / total;
}

/**
 * Run all client-side quality checks on a File.
 * For PDFs we only do mime + size — content checks happen server-side.
 */
export async function checkImageQuality(file) {
  const issues = [];
  const info = {
    sizeMB: +(file.size / (1024 * 1024)).toFixed(2),
    mime: file.type,
  };

  if (!ACCEPTED_MIME.has(file.type)) {
    issues.push(makeIssue('invalid_mime'));
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    issues.push(makeIssue('too_large'));
  }

  // PDF: we don't decode images, so we stop here.
  if (file.type === 'application/pdf') {
    return { ok: issues.length === 0, issues, info, previewUrl: null };
  }

  // Bail early on hard mime/size problems — no point decoding if the
  // file is the wrong type.
  if (issues.length > 0) {
    return { ok: false, issues, info, previewUrl: null };
  }

  let img, url;
  try {
    ({ img, url } = await loadImageElement(file));
  } catch {
    return {
      ok: false,
      issues: [makeIssue('load_failed')],
      info,
      previewUrl: null,
    };
  }

  info.width = img.naturalWidth;
  info.height = img.naturalHeight;

  if (info.width < MIN_WIDTH || info.height < MIN_HEIGHT) {
    issues.push(
      makeIssue(
        'low_resolution',
        `${info.width}×${info.height}, min ${MIN_WIDTH}×${MIN_HEIGHT}`,
      ),
    );
  }

  // Downscale to a fixed working size for blur+glare so phone-mega-
  // pixel photos and small scans get scored on the same yardstick.
  const target = 600;
  const scale = Math.min(1, target / Math.max(info.width, info.height));
  const cw = Math.max(1, Math.round(info.width * scale));
  const ch = Math.max(1, Math.round(info.height * scale));

  const canvas = document.createElement('canvas');
  canvas.width = cw;
  canvas.height = ch;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, cw, ch);

  const blur = laplacianVariance(canvas);
  info.blurScore = +blur.toFixed(1);
  if (blur < BLUR_THRESHOLD) {
    issues.push(
      makeIssue('blurry', `score ${info.blurScore} / min ${BLUR_THRESHOLD}`),
    );
  }

  const glare = glareRatio(canvas);
  info.glareRatio = +(glare * 100).toFixed(1);
  if (glare > GLARE_RATIO_THRESHOLD) {
    issues.push(
      makeIssue(
        'glare',
        `${info.glareRatio}% overexposed / max ${GLARE_RATIO_THRESHOLD * 100}%`,
      ),
    );
  }

  return { ok: issues.length === 0, issues, info, previewUrl: url };
}

export const QUALITY_THRESHOLDS = {
  MAX_SIZE_MB,
  MIN_WIDTH,
  MIN_HEIGHT,
  BLUR_THRESHOLD,
  GLARE_RATIO_THRESHOLD,
};
