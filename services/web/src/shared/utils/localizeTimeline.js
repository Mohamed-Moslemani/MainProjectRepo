// Translates the English status-history messages and next-action
// strings the backend stores back to Arabic for the citizen UI.
//
// Why this lives client-side: the backend writes one canonical
// English string per event into status_history (it's also where
// the audit log + email subject lines come from, so changing it
// would require migrating historical rows). The citizen-facing
// timeline can swap to the active locale without touching the
// stored data.
//
// Patterns with dynamic content (e.g. "Risk score: 75.35") use a
// regex; static strings are an exact-match map.

// Document-type slugs the backend embeds inside messages
// ("Missing document: civil_registry_extract"). We replace the slug
// with the Arabic label so the rejection banner reads naturally.
// Keys MUST match the canonical DocumentType enum in
// shared/schemas.py — otherwise the slug falls through verbatim.
const DOC_TYPE_AR = {
  national_id_front: 'الهوية - الوجه الأمامي',
  national_id_back: 'الهوية - الوجه الخلفي',
  old_id_front: 'الهوية القديمة - أمامي',
  old_id_back: 'الهوية القديمة - خلفي',
  civil_registry_extract: 'بيان قيد إفرادي',
  selfie: 'صورة شخصية',
  liveness_capture: 'صورة التحقق من الحياة',
  passport_data_page: 'صفحة بيانات الجواز',
  old_passport_data_page: 'جواز السفر القديم',
  additional_identity_proof: 'إثبات إضافي للهوية',
  guardian_docs: 'وثائق الولي',
  police_report: 'محضر شرطة',
  damaged_passport: 'الجواز التالف',
  court_ruling: 'حكم محكمة',
};

const DOC_TYPE_EN = {
  national_id_front: 'National ID (Front)',
  national_id_back: 'National ID (Back)',
  old_id_front: 'Old ID (Front)',
  old_id_back: 'Old ID (Back)',
  civil_registry_extract: 'Civil Registry Extract',
  selfie: 'Selfie',
  liveness_capture: 'Liveness Capture',
  passport_data_page: 'Passport Data Page',
  old_passport_data_page: 'Old Passport Data Page',
  additional_identity_proof: 'Additional Identity Proof',
  guardian_docs: 'Guardian Documents',
  police_report: 'Police Report',
  damaged_passport: 'Damaged Passport',
  court_ruling: 'Court Ruling',
};

const docAr = (slug) => DOC_TYPE_AR[slug] || slug;
const docEn = (slug) => DOC_TYPE_EN[slug] || slug;

// Field-slug → Arabic / English. Backend retake messages embed the
// canonical OCR field name ("Could not extract fields: id_number") and
// the citizen sees that slug verbatim if we don't translate it. Keys
// MUST match the canonical field names emitted by the OCR + ai_extractor
// schemas — anything not in this map falls through to the slug (still
// readable, just not localised).
const FIELD_AR = {
  first_name_ar: 'الاسم الأول',
  surname_ar: 'الشهرة',
  full_name_ar: 'الاسم الكامل',
  full_name: 'الاسم الكامل',
  given_names: 'الاسم الأول (لاتيني)',
  surname: 'الشهرة (لاتيني)',
  father_name: 'اسم الأب',
  mother_name: 'اسم الأم',
  date_of_birth: 'تاريخ الولادة',
  place_of_birth: 'محل الولادة',
  gender: 'الجنس',
  sex: 'الجنس',
  id_number: 'رقم بطاقة الهوية',
  registry_number: 'رقم القيد',
  registry_place: 'محل القيد',
  register_place: 'محل القيد',
  register_number: 'رقم القيد',
  district: 'القضاء',
  religious_sect: 'المذهب',
  marital_status: 'الوضع العائلي',
  passport_number: 'رقم الجواز',
  nationality: 'الجنسية',
  date_of_issue: 'تاريخ الإصدار',
  issue_date: 'تاريخ الإصدار',
  date_of_expiry: 'تاريخ الانتهاء',
  expiry_date: 'تاريخ الانتهاء',
  mrz_passport_number: 'رقم الجواز (MRZ)',
  mrz_surname: 'الشهرة (MRZ)',
  mrz_given_names: 'الاسم الأول (MRZ)',
  mrz_date_of_birth: 'تاريخ الولادة (MRZ)',
  mrz_expiry_date: 'تاريخ الانتهاء (MRZ)',
  mrz_nationality: 'الجنسية (MRZ)',
  mrz_sex: 'الجنس (MRZ)',
};
const fieldsAr = (csv) =>
  String(csv || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((slug) => FIELD_AR[slug] || slug)
    .join('، ');

const STATIC = {
  // status_history.message
  "Application submitted for processing":  "تم تقديم الطلب وجارٍ المعالجة",
  "Case submitted for processing":         "تم استلام الطلب وجارٍ المعالجة",
  "OCR and face verification completed":   "اكتمل التحقق من المستندات والوجه",
  "Auto-rejected: high risk score":        "رفض آلي: درجة المخاطر مرتفعة",
  "Pipeline crashed":                      "تعطّل النظام أثناء المعالجة",
  "Processing pipeline timed out":         "انتهت مهلة المعالجة",
  "Please complete payment to proceed":    "يرجى إتمام الدفع للمتابعة",
  "Payment failed — citizen can retry from /case detail":
    "فشل الدفع — يمكنك إعادة المحاولة من صفحة الطلب",
  "Citizen retried payment after a previous failure":
    "أعاد المواطن محاولة الدفع",
  "Withdrawn by citizen":                  "سحب المواطن طلبه",
  // rejection_reasons / issues — static
  "No matching record in the civil registry":
    "لا يوجد سجل مطابق في السجل المدني",
  "Civil registry records citizen as deceased":
    "السجل المدني يُسجِّل المواطن كمتوفى",
  "Missing selfie or reference document for face verification":
    "صورة شخصية أو مستند مرجعي ناقص للتحقق من الوجه",
  // Cross-document identity coherence — emitted by orchestrator
  // when uploaded docs disagree on name / DOB / gender (the
  // canonical "uploaded mom's passport plus my registry extract"
  // fraud pattern). The accompanying retake banner is bilingual
  // already; this localises the case.rejection_reasons entry
  // surfaced on the case-detail and admin-review screens.
  "Cross-document identity check failed: uploaded documents do not describe the same person.":
    "فشل التحقق من تطابق هويّة المستندات: المستندات المرفوعة لا تخصّ نفس الشخص.",
  "Cross-document identity mismatch":
    "عدم تطابق الهوية بين المستندات",
  "Document quality gate failed — citizen must retake":
    "فشل فحص جودة المستندات — يجب إعادة التصوير وإعادة التقديم",
  "Lebanese eligibility rule failed":
    "فشل تطبيق قواعد الأهلية اللبنانية",
  "Face service unavailable":
    "خدمة التحقق من الوجه غير متوفرة",
  "High risk score":
    "درجة المخاطر مرتفعة",
  // OCR / MRZ retake reasons (services/ocr/app/routers/ocr.py)
  "Could not parse MRZ from passport":
    "تعذّر قراءة منطقة QR/MRZ من الجواز",
  "MRZ check digit validation failed":
    "فشل التحقق من خانات التحقق في منطقة MRZ",
  "Biometrics captured at GDGS centre — production started":
    "تم أخذ البصمات في مركز الأمن العام — بدأ الإنتاج",
  "Email verified successfully. You can now log in.":
    "تم التحقق من البريد الإلكتروني. يمكنك الآن تسجيل الدخول.",

  // next_action — NEXT_ACTIONS map in services/gateway/app/services/case_machine.py
  "Complete your application and upload required documents.":
    "أكمل بياناتك وارفع المستندات المطلوبة.",
  "Your application is being processed. Please wait.":
    "طلبك قيد المعالجة. يرجى الانتظار.",
  "Documents validated. Risk assessment in progress.":
    "تم التحقق من المستندات. تقييم المخاطر قيد المعالجة.",
  "Risk assessment complete. Pending decision.":
    "اكتمل تقييم المخاطر. بانتظار القرار.",
  "Additional information required. Check details and re-submit.":
    "مطلوب معلومات إضافية. راجع التفاصيل وأعد التقديم.",
  "Awaiting Mukhtar verification and digital stamp.":
    "بانتظار توقيع المختار الرقمي.",
  "Application approved. Please proceed to payment.":
    "تمت الموافقة على الطلب. يرجى إتمام الدفع.",
  "Payment required. Complete payment to proceed.":
    "مطلوب الدفع. أكمل الدفع للمتابعة.",
  "Payment failed. Please retry — your application is held until payment clears.":
    "فشل الدفع. يرجى إعادة المحاولة — الطلب موقوف حتى نجاح الدفع.",
  "Book and attend a GDGS centre appointment for fingerprint capture. Bring your national ID and the printed payment receipt.":
    "احجز موعداً في مركز الأمن العام لأخذ البصمات. احضر هويتك الوطنية وإيصال الدفع.",
  "Application rejected. See notes for reason.":
    "تم رفض الطلب. راجع الملاحظات لمعرفة السبب.",
  "Payment received. Your document is being manufactured.":
    "تم استلام الدفع. جارٍ تصنيع الوثيقة.",
  "Visit the assigned office to collect your document.":
    "توجّه إلى المركز المحدد لاستلام وثيقتك.",
  "Document collected. Case closed.":
    "تم استلام الوثيقة. تم إغلاق الطلب.",
};

// Dynamic patterns — captured numbers/identifiers preserved verbatim.
// Includes rejection_reasons / issues strings the orchestrator pushes
// onto the case (rendered in the "أسباب الرفض" banner) plus quality
// gate retake strings.
const PATTERNS = [
  [/^Risk score: ([\d.]+)$/,                    'درجة المخاطر: $1'],
  [/^Status updated by (\w+) \(([^)]+)\)$/,     'تم تحديث الحالة من قبل $1 ($2)'],
  [/^Case transferred to (.+)$/,                'تم تحويل الطلب إلى $1'],
  [/^Transferred from (.+)$/,                   'تم التحويل من $1'],

  // Image-quality retake reasons emitted by services/ocr/app/services/quality.py.
  // Numeric captures (resolution, blur score, glare %, skew angle) are preserved
  // verbatim — same shape used by the citizen retake banner.
  [/^Resolution too low \((\d+)x(\d+)\), minimum (\d+)x(\d+)$/,
    'الدقة منخفضة جداً ($1×$2)، الحد الأدنى $3×$4'],
  [/^Image is too blurry \(score: ([\d.]+), min: ([\d.]+)\)$/,
    'الصورة ضبابية جداً (النتيجة: $1، الحد الأدنى: $2)'],
  [/^Glare detected \(([\d.]+)% overexposed\)$/,
    'انعكاس ضوء قوي ($1٪ مفرط الإضاءة)'],
  [/^Document appears skewed \(angle: ([\d.]+) degrees\)$/,
    'المستند مائل (الزاوية: $1 درجة)'],

  // Note: "Missing document: ...", "OCR failed for ...", "Could not
  // extract fields: ...", "Low confidence on fields: ...", and the
  // classifier-rejection patterns are handled by DOC_AWARE / FIELD_AWARE
  // inside `localizeTimelineMessage` so the captured slug gets translated,
  // not just the surrounding wrapper.

  // The model returns its own Arabic reasons (see doc_classifier.py
  // system prompt). The orchestrator surfaces them as
  // "Classifier note: <arabic text>" — so the prefix is bilingual but
  // the body stays Arabic verbatim. In RTL (Arabic) UI we drop the
  // English word entirely; in LTR (English) UI we keep "Classifier note:".
  [/^Classifier note: (.+)$/,                   'ملاحظة: $1'],
];

export function localizeTimelineMessage(en) {
  if (!en) return { ar: '', en: '' };
  if (STATIC[en]) return { ar: STATIC[en], en };

  // Doc-type-aware patterns. The slug captured in $1 is rewritten
  // with the proper Arabic OR English label on each side, so
  // "Missing document: national_id_front" becomes "مستند ناقص:
  // الهوية - الوجه الأمامي" / "Missing document: National ID (Front)".
  const DOC_AWARE = [
    { re: /^Missing document: (.+)$/,
      ar: (slug) => `مستند ناقص: ${docAr(slug)}`,
      en: (slug) => `Missing document: ${docEn(slug)}` },
    { re: /^OCR failed for (.+)$/,
      ar: (slug) => `فشل قراءة المستند: ${docAr(slug)}`,
      en: (slug) => `OCR failed for ${docEn(slug)}` },
    { re: /^Uploaded document does not appear to be a (\S+) \(detected: (.+)\)$/,
      ar: (expected, detected) =>
        `المستند المرفوع لا يبدو أنه ${docAr(expected)} (تم التعرّف عليه كـ: ${docAr(detected)})`,
      en: (expected, detected) =>
        `Uploaded document does not appear to be a ${docEn(expected)} (detected: ${docEn(detected)})` },
    { re: /^Uploaded (\S+) does not look authentic — please re-photograph the original document$/,
      ar: (slug) => `المستند المرفوع (${docAr(slug)}) لا يبدو أصلياً — يرجى إعادة تصوير المستند الأصلي`,
      en: (slug) => `Uploaded ${docEn(slug)} does not look authentic — please re-photograph the original document` },
  ];
  for (const p of DOC_AWARE) {
    const m = en.match(p.re);
    if (m) {
      const args = m.slice(1);
      return { ar: p.ar(...args), en: p.en(...args) };
    }
  }

  // Field-slug-aware patterns. The CSV captured in $1 is split, each
  // slug rewritten through FIELD_AR, then re-joined with the Arabic
  // list separator (،) so "Could not extract fields: id_number, surname_ar"
  // becomes "تعذّر استخراج الحقول: رقم بطاقة الهوية، الشهرة".
  const FIELD_AWARE = [
    { re: /^Could not extract fields: (.+)$/,
      ar: (csv) => `تعذّر استخراج الحقول: ${fieldsAr(csv)}` },
    { re: /^Low confidence on fields: (.+)$/,
      ar: (csv) => `ثقة منخفضة في الحقول: ${fieldsAr(csv)}` },
  ];
  for (const p of FIELD_AWARE) {
    const m = en.match(p.re);
    if (m) return { ar: p.ar(m[1]), en };
  }

  for (const [re, replacement] of PATTERNS) {
    if (re.test(en)) return { ar: en.replace(re, replacement), en };
  }
  // Fallback: show the English string in both — at least it's readable
  // rather than empty. Add a translation entry to STATIC if you see
  // this in a real demo.
  return { ar: en, en };
}

// Always render timestamps in Beirut time, regardless of the
// browser's local zone. The wire format is a UTC ISO string;
// formatting to the citizen's local tz on a server in another
// region produced wrong-looking times in the timeline.
export function formatBeirutDateTime(iso, locale = 'ar-LB') {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString(locale, {
    timeZone: 'Asia/Beirut',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
