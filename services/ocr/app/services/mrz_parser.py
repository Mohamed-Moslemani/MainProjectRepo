"""MRZ (Machine Readable Zone) parser for passports.

Parses TD3 format (2 lines x 44 chars for passports).
Validates check digits per ICAO 9303 standard.
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


def parse_mrz(text: str) -> dict | None:
    """Extract and parse MRZ from OCR text.

    Looks for TD3 passport format (2 lines of 44 characters).
    Returns parsed fields with validation status.
    """
    # Clean up text and find MRZ lines
    lines = text.strip().split('\n')
    mrz_lines = []

    for line in lines:
        # MRZ lines contain mostly uppercase letters, digits, and '<'
        cleaned = re.sub(r'[^A-Z0-9<]', '', line.upper())
        if len(cleaned) >= 42:  # allow some OCR error margin
            mrz_lines.append(cleaned[:44].ljust(44, '<'))

    if len(mrz_lines) < 2:
        return None

    line1 = mrz_lines[-2]  # second to last (in case of extra lines)
    line2 = mrz_lines[-1]

    # Validate format
    if not line1.startswith('P'):
        return None

    try:
        # Line 1: P<ISSUING_STATE<SURNAME<<GIVEN_NAMES<<<...
        doc_type = line1[0:2].replace('<', '')
        issuing_country = line1[2:5].replace('<', '')
        names_part = line1[5:44]
        name_parts = names_part.split('<<')
        surname = name_parts[0].replace('<', ' ').strip() if name_parts else ''
        given_names = name_parts[1].replace('<', ' ').strip() if len(name_parts) > 1 else ''

        # Line 2: passport_number + check + nationality + DOB + check + sex + expiry + check + personal_no + check + composite_check
        passport_number = line2[0:9].replace('<', '')
        passport_check = int(line2[9]) if line2[9].isdigit() else -1
        nationality = line2[10:13].replace('<', '')
        dob = line2[13:19]
        dob_check = int(line2[19]) if line2[19].isdigit() else -1
        sex = line2[20]
        expiry = line2[21:27]
        expiry_check = int(line2[27]) if line2[27].isdigit() else -1
        personal_number = line2[28:42].replace('<', '')
        personal_check = int(line2[42]) if line2[42].isdigit() else -1

        # Validate check digits
        validations = {
            "passport_number": check_digit(line2[0:9]) == passport_check,
            "date_of_birth": check_digit(line2[13:19]) == dob_check,
            "expiry_date": check_digit(line2[21:27]) == expiry_check,
        }

        # Composite check digit (line2[0:10] + line2[13:20] + line2[21:43])
        composite_data = line2[0:10] + line2[13:20] + line2[21:43]
        composite_check_val = int(line2[43]) if line2[43].isdigit() else -1
        validations["composite"] = check_digit(composite_data) == composite_check_val

        # Format DOB
        dob_formatted = f"19{dob[0:2]}-{dob[2:4]}-{dob[4:6]}" if dob[0] > '3' else f"20{dob[0:2]}-{dob[2:4]}-{dob[4:6]}"
        expiry_formatted = f"20{expiry[0:2]}-{expiry[2:4]}-{expiry[4:6]}"

        all_valid = all(validations.values())

        return {
            "raw_line1": line1,
            "raw_line2": line2,
            "document_type": doc_type,
            "issuing_country": issuing_country,
            "surname": surname,
            "given_names": given_names,
            "passport_number": passport_number,
            "nationality": nationality,
            "date_of_birth": dob_formatted,
            "sex": sex,
            "expiry_date": expiry_formatted,
            "personal_number": personal_number,
            "check_digits_valid": validations,
            "all_checks_passed": all_valid,
        }

    except (IndexError, ValueError) as e:
        logger.error(f"MRZ parsing error: {e}")
        return None
