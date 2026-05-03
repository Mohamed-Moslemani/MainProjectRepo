// Document capture spec: maps each doc_type to a target shape so the
// camera overlay can draw a guide rectangle the user aligns the doc
// inside.
//
// `aspect` is width/height in landscape orientation. `orientation`
// tells the UI whether to render the guide tall (portrait) or wide
// (landscape) — most ID cards are captured landscape, civil registry
// extracts and birth certificates are paper sheets shot portrait.
//
// Supporting docs (police_report, court_ruling, marriage_certificate)
// are intentionally NOT in this map: they're varied paper sizes and
// stay on the file-picker upload path. Anything not in this map
// keeps the legacy upload UX.

export const CAPTURE_SPECS = {
  // ID-1 ratio: 85.6 × 54 mm → 1.586:1, landscape
  national_id_front: { aspect: 1.586, orientation: 'landscape', labelAr: 'البطاقة - الوجه', labelEn: 'ID Card – Front' },
  national_id_back:  { aspect: 1.586, orientation: 'landscape', labelAr: 'البطاقة - الخلف', labelEn: 'ID Card – Back' },
  old_id_front:      { aspect: 1.586, orientation: 'landscape', labelAr: 'البطاقة القديمة - الوجه', labelEn: 'Old ID – Front' },
  old_id_back:       { aspect: 1.586, orientation: 'landscape', labelAr: 'البطاقة القديمة - الخلف', labelEn: 'Old ID – Back' },

  // Passport biometric data page: ~88 × 125 mm → 1.42:1, portrait.
  // Captured as two separate photos so each half is shot at full
  // sensor resolution. Top = photo + visual fields. Bottom = MRZ
  // + signature/authority. Each half is roughly square, so we use
  // a 1.4 aspect (the visible page width) × half height ≈ 0.7 ratio.
  passport_data_page:     { aspect: 1.42, orientation: 'portrait', labelAr: 'صفحة جواز السفر', labelEn: 'Passport Data Page' },
  old_passport_data_page: { aspect: 1.42, orientation: 'portrait', labelAr: 'جواز السفر القديم', labelEn: 'Old Passport Data Page' },
  passport_data_page_top:        { aspect: 2.0, orientation: 'landscape', labelAr: 'الجواز - النصف العلوي (الصورة)', labelEn: 'Passport – Top Half (Photo)' },
  passport_data_page_bottom:     { aspect: 2.0, orientation: 'landscape', labelAr: 'الجواز - النصف السفلي (MRZ)', labelEn: 'Passport – Bottom Half (MRZ)' },
  old_passport_data_page_top:    { aspect: 2.0, orientation: 'landscape', labelAr: 'الجواز القديم - النصف العلوي', labelEn: 'Old Passport – Top Half' },
  old_passport_data_page_bottom: { aspect: 2.0, orientation: 'landscape', labelAr: 'الجواز القديم - النصف السفلي', labelEn: 'Old Passport – Bottom Half' },

  // A4 portrait sheets — Lebanese civil registry extract is typically
  // a folded A4. 1:1.414 → aspect 1.414 in landscape numerics.
  civil_registry_extract: { aspect: 1.414, orientation: 'portrait', labelAr: 'إخراج قيد', labelEn: 'Civil Registry Extract' },
  birth_certificate:      { aspect: 1.414, orientation: 'portrait', labelAr: 'شهادة الميلاد', labelEn: 'Birth Certificate' },
};

export function isCaptureRequired(docType) {
  return Object.prototype.hasOwnProperty.call(CAPTURE_SPECS, docType);
}
