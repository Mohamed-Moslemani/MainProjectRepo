"""Unit tests for the MRZ (Machine Readable Zone) parser — ICAO 9303 TD3."""

import pytest

from app.services.mrz_parser import check_digit, parse_mrz


# ICAO 9303 Part 4 specimen passport — known-valid TD3 MRZ with all check digits correct.
VALID_MRZ = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
)


class TestCheckDigit:
    """ICAO 9303 check digit algorithm — weights [7, 3, 1] repeating."""

    def test_known_passport_number(self):
        """L898902C3 → check digit 6."""
        assert check_digit("L898902C3") == 6

    def test_known_date_of_birth(self):
        """740812 → check digit 2."""
        assert check_digit("740812") == 2

    def test_known_expiry(self):
        """120415 → check digit 9."""
        assert check_digit("120415") == 9

    def test_filler_character_is_zero(self):
        """'<' is treated as value 0."""
        assert check_digit("<<<<") == 0

    def test_empty_string(self):
        assert check_digit("") == 0

    def test_letter_values(self):
        """Letters map to A=10, B=11, ..., Z=35."""
        # "A" alone: 10 * 7 = 70; 70 % 10 = 0
        assert check_digit("A") == 0
        # "Z" alone: 35 * 7 = 245; 245 % 10 = 5
        assert check_digit("Z") == 5


class TestParseMRZHappyPath:
    def test_valid_mrz_returns_dict(self):
        result = parse_mrz(VALID_MRZ)
        assert result is not None
        assert isinstance(result, dict)

    def test_extracts_surname(self):
        result = parse_mrz(VALID_MRZ)
        assert result["surname"] == "ERIKSSON"

    def test_extracts_given_names(self):
        result = parse_mrz(VALID_MRZ)
        assert result["given_names"] == "ANNA MARIA"

    def test_extracts_passport_number(self):
        result = parse_mrz(VALID_MRZ)
        assert result["passport_number"] == "L898902C3"

    def test_extracts_nationality(self):
        result = parse_mrz(VALID_MRZ)
        assert result["nationality"] == "UTO"

    def test_extracts_sex(self):
        result = parse_mrz(VALID_MRZ)
        assert result["sex"] == "F"

    def test_formats_date_of_birth_as_1974(self):
        """YY=74, first digit '7' > '3' → 19xx century."""
        result = parse_mrz(VALID_MRZ)
        assert result["date_of_birth"] == "1974-08-12"

    def test_formats_expiry_as_2012(self):
        """YY=12 (century always 20 for expiry)."""
        result = parse_mrz(VALID_MRZ)
        assert result["expiry_date"] == "2012-04-15"

    def test_all_check_digits_pass(self):
        result = parse_mrz(VALID_MRZ)
        assert result["all_checks_passed"] is True
        assert all(result["check_digits_valid"].values())

    def test_check_digits_breakdown(self):
        result = parse_mrz(VALID_MRZ)
        assert set(result["check_digits_valid"].keys()) == {
            "passport_number", "date_of_birth", "expiry_date", "composite"
        }


class TestParseMRZFailureCases:
    def test_empty_text_returns_none(self):
        assert parse_mrz("") is None

    def test_single_line_returns_none(self):
        """Need at least 2 MRZ lines."""
        assert parse_mrz("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<") is None

    def test_non_passport_first_line_returns_none(self):
        """TD3 line 1 must start with 'P'."""
        bad = (
            "I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
        )
        assert parse_mrz(bad) is None

    def test_lines_too_short_returns_none(self):
        """MRZ lines must be ≥42 chars after cleaning."""
        assert parse_mrz("P<UTO<<<<\nL898902C3") is None

    def test_invalid_check_digit_flagged(self):
        """Corrupt the passport check digit; parser should still return
        the fields but flag check_digits_valid['passport_number'] as False."""
        broken = (
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C30UTO7408122F1204159ZE184226B<<<<<10"  # check digit 0 not 6
        )
        result = parse_mrz(broken)
        assert result is not None
        assert result["check_digits_valid"]["passport_number"] is False
        assert result["all_checks_passed"] is False

    def test_invalid_dob_check_digit_flagged(self):
        broken = (
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C36UTO7408120F1204159ZE184226B<<<<<10"  # dob check 0 not 2
        )
        result = parse_mrz(broken)
        assert result is not None
        assert result["check_digits_valid"]["date_of_birth"] is False
        assert result["all_checks_passed"] is False


class TestParseMRZNoise:
    """Real OCR output often has extra lines before/around the MRZ."""

    def test_mrz_preceded_by_noise_still_parses(self):
        noisy = (
            "Republic of Utopia\n"
            "PASSPORT\n"
            "Surname: ERIKSSON\n"
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
        )
        result = parse_mrz(noisy)
        assert result is not None
        assert result["passport_number"] == "L898902C3"
        assert result["all_checks_passed"] is True

    def test_trailing_whitespace_tolerated(self):
        result = parse_mrz(VALID_MRZ + "\n  \n")
        assert result is not None
        assert result["passport_number"] == "L898902C3"


class TestParseMRZDOBCentury:
    """The century-guess heuristic: dob[0] > '3' → 19xx, else 20xx."""

    def test_dob_starting_with_7_is_1974(self):
        result = parse_mrz(VALID_MRZ)
        assert result["date_of_birth"].startswith("1974")
