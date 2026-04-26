/**
 * Lebanese phone number validation + light normalisation.
 *
 * Lebanese mobile lines use the +961 country code followed by:
 *   - mobile prefix:  3, 7X (70-71-76-78-79-81), or 81
 *   - landline:       1 (Beirut), 4, 5, 6, 7 (south), 8, 9
 *
 * Real-world inputs come in many shapes: "70 123 456",
 * "+961 70 123 456", "0070 123 456" (international 00),
 * "00961-70123456", etc. We strip all non-digits, lop a leading 00,
 * and accept the result if it's the canonical 8-digit local form
 * (70123456) OR the +961 form (961 + 8 digits).
 *
 * Returns null when the input doesn't look like a Lebanese number,
 * otherwise the E.164-shaped string "+961XXXXXXXX".
 */

const LB_LOCAL_PREFIXES = [
  // Mobile
  '3', '70', '71', '76', '78', '79', '81',
  // Landline regions
  '1', '4', '5', '6', '7', '8', '9',
];

export function normalizeLebanesePhone(input) {
  if (!input) return null;
  let digits = String(input).replace(/\D/g, '');

  // International 00 prefix → drop
  if (digits.startsWith('00')) digits = digits.slice(2);

  // +961 / 961 country code
  if (digits.startsWith('961')) {
    const local = digits.slice(3);
    return validLocalLength(local) && hasPrefix(local) ? `+961${local}` : null;
  }

  // Local form sometimes prefixed with 0 (e.g. dialing within Lebanon)
  if (digits.startsWith('0') && digits.length === 9) digits = digits.slice(1);

  if (validLocalLength(digits) && hasPrefix(digits)) {
    return `+961${digits}`;
  }
  return null;
}

function validLocalLength(local) {
  // LB local numbers are 7 or 8 digits depending on prefix:
  //   1-digit prefix (3, 1, 4, 5, 6, 7, 8, 9)  → 7 digits total
  //   2-digit prefix (70, 71, 76, 78, 79, 81)  → 8 digits total
  return local.length === 7 || local.length === 8;
}

function hasPrefix(local) {
  return LB_LOCAL_PREFIXES.some((p) => local.startsWith(p));
}

export function isLebanesePhone(input) {
  return normalizeLebanesePhone(input) !== null;
}
