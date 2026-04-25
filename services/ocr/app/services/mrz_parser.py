"""MRZ (Machine Readable Zone) parser.

Supports all three ICAO 9303 formats:
  - TD1: ID cards / residence permits (3 lines x 30 chars)
  - TD2: Older travel docs / some visas (2 lines x 36 chars)
  - TD3: Modern passports (2 lines x 44 chars)

Validates check digits per ICAO 9303 standard and returns a unified
result dict regardless of input format (keys kept as `passport_number`,
`expiry_date`, etc. for backwards compatibility with downstream callers
that already handle passports).
"""

import re
import logging

logger = logging.getLogger(__name__)

MRZ_WEIGHTS = [7, 3, 1]


def check_digit(data: str) -> int:
    """Compute ICAO 9303 check digit."""
    total = 0
    for i, char in enumerate(data):
        if char == '<':
            val = 0
        elif char.isdigit():
            val = int(char)
        elif char.isalpha():
            val = ord(char.upper()) - 55
        else:
            val = 0
        total += val * MRZ_WEIGHTS[i % 3]
    return total % 10


def _format_yymmdd(yymmdd: str, future_hint: bool = False) -> str:
    """YYMMDD → YYYY-MM-DD. If future_hint=True (expiry dates), the
    century is assumed 2000s. Otherwise (DOB), 2000s only if year digit
    starts 0–3, else 1900s."""
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return yymmdd
    century = "20" if (future_hint or yymmdd[0] <= '3') else "19"
    return f"{century}{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"


def _collect_mrz_lines(text: str) -> list[str]:
    """Pull lines that look like MRZ (mostly A-Z0-9<) from OCR text."""
    out = []
    for line in text.strip().split('\n'):
        cleaned = re.sub(r'[^A-Z0-9<]', '', line.upper())
        # accept anything plausibly MRZ-width (28+ chars)
        if len(cleaned) >= 28:
            out.append(cleaned)
    return out


def _parse_td3(lines: list[str]) -> dict | None:
    """TD3: 2 lines x 44 chars (passports)."""
    td3 = [l[:44].ljust(44, '<') for l in lines if len(l) >= 42]
    if len(td3) < 2:
        return None
    line1, line2 = td3[-2], td3[-1]
    if not line1.startswith('P'):
        return None
    try:
        doc_type = line1[0:2].replace('<', '')
        issuing_country = line1[2:5].replace('<', '')
        names_part = line1[5:44]
        name_parts = names_part.split('<<')
        surname = name_parts[0].replace('<', ' ').strip() if name_parts else ''
        given_names = name_parts[1].replace('<', ' ').strip() if len(name_parts) > 1 else ''

        passport_number = line2[0:9].replace('<', '')
        passport_check = int(line2[9]) if line2[9].isdigit() else -1
        nationality = line2[10:13].replace('<', '')
        dob = line2[13:19]
        dob_check = int(line2[19]) if line2[19].isdigit() else -1
        sex = line2[20]
        expiry = line2[21:27]
        expiry_check = int(line2[27]) if line2[27].isdigit() else -1
        personal_number = line2[28:42].replace('<', '')

        validations = {
            "passport_number": check_digit(line2[0:9]) == passport_check,
            "date_of_birth": check_digit(line2[13:19]) == dob_check,
            "expiry_date": check_digit(line2[21:27]) == expiry_check,
        }
        composite_data = line2[0:10] + line2[13:20] + line2[21:43]
        composite_check_val = int(line2[43]) if line2[43].isdigit() else -1
        validations["composite"] = check_digit(composite_data) == composite_check_val

        return {
            "format": "TD3",
            "raw_lines": [line1, line2],
            "raw_line1": line1,
            "raw_line2": line2,
            "document_type": doc_type,
            "issuing_country": issuing_country,
            "surname": surname,
            "given_names": given_names,
            "passport_number": passport_number,
            "nationality": nationality,
            "date_of_birth": _format_yymmdd(dob),
            "sex": sex,
            "expiry_date": _format_yymmdd(expiry, future_hint=True),
            "personal_number": personal_number,
            "check_digits_valid": validations,
            "all_checks_passed": all(validations.values()),
        }
    except (IndexError, ValueError) as e:
        logger.error(f"TD3 parsing error: {e}")
        return None


def _parse_td2(lines: list[str]) -> dict | None:
    """TD2: 2 lines x 36 chars (legacy travel docs, some visas)."""
    td2 = [l[:36].ljust(36, '<') for l in lines if 34 <= len(l) <= 41]
    if len(td2) < 2:
        return None
    line1, line2 = td2[-2], td2[-1]
    # Line 1 starts with doc code (I, A, C for IDs; P for older passports).
    # TD2 passports exist but TD3 is mandatory post-2015 so we accept any
    # single-letter doc code + issuing country.
    if not re.match(r'^[A-Z]', line1):
        return None
    try:
        doc_type = line1[0:2].replace('<', '')
        issuing_country = line1[2:5].replace('<', '')
        names_part = line1[5:36]
        name_parts = names_part.split('<<')
        surname = name_parts[0].replace('<', ' ').strip() if name_parts else ''
        given_names = name_parts[1].replace('<', ' ').strip() if len(name_parts) > 1 else ''

        doc_number = line2[0:9].replace('<', '')
        doc_check = int(line2[9]) if line2[9].isdigit() else -1
        nationality = line2[10:13].replace('<', '')
        dob = line2[13:19]
        dob_check = int(line2[19]) if line2[19].isdigit() else -1
        sex = line2[20]
        expiry = line2[21:27]
        expiry_check = int(line2[27]) if line2[27].isdigit() else -1
        optional = line2[28:35].replace('<', '')

        validations = {
            "passport_number": check_digit(line2[0:9]) == doc_check,
            "date_of_birth": check_digit(line2[13:19]) == dob_check,
            "expiry_date": check_digit(line2[21:27]) == expiry_check,
        }
        composite_data = line2[0:10] + line2[13:20] + line2[21:35]
        composite_check_val = int(line2[35]) if line2[35].isdigit() else -1
        validations["composite"] = check_digit(composite_data) == composite_check_val

        return {
            "format": "TD2",
            "raw_lines": [line1, line2],
            "raw_line1": line1,
            "raw_line2": line2,
            "document_type": doc_type,
            "issuing_country": issuing_country,
            "surname": surname,
            "given_names": given_names,
            "passport_number": doc_number,
            "nationality": nationality,
            "date_of_birth": _format_yymmdd(dob),
            "sex": sex,
            "expiry_date": _format_yymmdd(expiry, future_hint=True),
            "personal_number": optional,
            "check_digits_valid": validations,
            "all_checks_passed": all(validations.values()),
        }
    except (IndexError, ValueError) as e:
        logger.error(f"TD2 parsing error: {e}")
        return None


def _parse_td1(lines: list[str]) -> dict | None:
    """TD1: 3 lines x 30 chars (ID cards, residence permits).

    Field layout:
      line1: doc_code(2) + issuing_country(3) + doc_number(9) + check(1) + optional1(15)
      line2: DOB(6) + check(1) + sex(1) + expiry(6) + check(1) + nationality(3) + optional2(11) + composite_check(1)
      line3: surname<<given_names  (30 chars)
    """
    td1 = [l[:30].ljust(30, '<') for l in lines if 28 <= len(l) <= 33]
    if len(td1) < 3:
        return None
    line1, line2, line3 = td1[-3], td1[-2], td1[-1]
    # Line 1 doc code: I / A / C / ID / IL / IP etc.
    if not re.match(r'^[IACV]', line1):
        return None
    try:
        doc_type = line1[0:2].replace('<', '')
        issuing_country = line1[2:5].replace('<', '')
        doc_number = line1[5:14].replace('<', '')
        doc_check = int(line1[14]) if line1[14].isdigit() else -1
        optional1 = line1[15:30].replace('<', '')

        dob = line2[0:6]
        dob_check = int(line2[6]) if line2[6].isdigit() else -1
        sex = line2[7]
        expiry = line2[8:14]
        expiry_check = int(line2[14]) if line2[14].isdigit() else -1
        nationality = line2[15:18].replace('<', '')
        optional2 = line2[18:29].replace('<', '')
        composite_check_val = int(line2[29]) if line2[29].isdigit() else -1

        names_part = line3[0:30]
        name_parts = names_part.split('<<')
        surname = name_parts[0].replace('<', ' ').strip() if name_parts else ''
        given_names = name_parts[1].replace('<', ' ').strip() if len(name_parts) > 1 else ''

        validations = {
            "passport_number": check_digit(line1[5:14]) == doc_check,
            "date_of_birth": check_digit(line2[0:6]) == dob_check,
            "expiry_date": check_digit(line2[8:14]) == expiry_check,
        }
        composite_data = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
        validations["composite"] = check_digit(composite_data) == composite_check_val

        return {
            "format": "TD1",
            "raw_lines": [line1, line2, line3],
            "raw_line1": line1,
            "raw_line2": line2,
            "raw_line3": line3,
            "document_type": doc_type,
            "issuing_country": issuing_country,
            "surname": surname,
            "given_names": given_names,
            "passport_number": doc_number,  # reused key for downstream compat
            "nationality": nationality,
            "date_of_birth": _format_yymmdd(dob),
            "sex": sex,
            "expiry_date": _format_yymmdd(expiry, future_hint=True),
            "personal_number": (optional1 + optional2).strip(),
            "check_digits_valid": validations,
            "all_checks_passed": all(validations.values()),
        }
    except (IndexError, ValueError) as e:
        logger.error(f"TD1 parsing error: {e}")
        return None


def parse_mrz(text: str) -> dict | None:
    """Extract and parse MRZ from OCR text.

    Tries TD3 (passport) → TD2 → TD1 in that order. Returns the first
    successful parse. All three formats return the same shape so callers
    don't need to branch on `format`.
    """
    lines = _collect_mrz_lines(text)
    if not lines:
        return None

    for parser in (_parse_td3, _parse_td2, _parse_td1):
        result = parser(lines)
        if result is not None:
            return result
    return None
