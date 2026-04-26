"""The 18 officially-recognised Lebanese religious sects.

Lebanon's civil status records have always carried a sect (مذهب)
field. The 1932 census fixed the 18 recognised sects, and the 1989
Taif Accord retained the system. The biometric ID briefly omitted
the sect printed on the card (controversially), but the underlying
civil status registry still tracks it for personal-status laws
(marriage, inheritance, custody).

Storage convention: lowercase, ASCII, hyphen-separated. The UI maps
back to Arabic for display.
"""

from __future__ import annotations


SECTS: list[dict[str, str]] = [
    # ── Christian ───────────────────────────────────────────
    {"id": "maronite",          "ar": "ماروني",            "en": "Maronite",                   "family": "christian"},
    {"id": "greek-orthodox",    "ar": "روم أرثوذكس",       "en": "Greek Orthodox",              "family": "christian"},
    {"id": "greek-catholic",    "ar": "روم كاثوليك",       "en": "Greek Catholic (Melkite)",    "family": "christian"},
    {"id": "armenian-orthodox", "ar": "أرمن أرثوذكس",      "en": "Armenian Orthodox",           "family": "christian"},
    {"id": "armenian-catholic", "ar": "أرمن كاثوليك",      "en": "Armenian Catholic",           "family": "christian"},
    {"id": "syriac-orthodox",   "ar": "سريان أرثوذكس",     "en": "Syriac Orthodox",             "family": "christian"},
    {"id": "syriac-catholic",   "ar": "سريان كاثوليك",     "en": "Syriac Catholic",             "family": "christian"},
    {"id": "assyrian",          "ar": "آشوري",             "en": "Assyrian Church of the East", "family": "christian"},
    {"id": "chaldean",          "ar": "كلداني",            "en": "Chaldean Catholic",           "family": "christian"},
    {"id": "roman-catholic",    "ar": "روماني كاثوليك",    "en": "Roman Catholic (Latin)",      "family": "christian"},
    {"id": "coptic",            "ar": "قبطي",              "en": "Coptic",                      "family": "christian"},
    {"id": "protestant",        "ar": "إنجيلي",            "en": "Protestant (Evangelical)",    "family": "christian"},

    # ── Muslim ──────────────────────────────────────────────
    {"id": "sunni",             "ar": "سني",               "en": "Sunni",                       "family": "muslim"},
    {"id": "shia",              "ar": "شيعي",              "en": "Shia",                        "family": "muslim"},
    {"id": "alawite",           "ar": "علوي",              "en": "Alawite",                     "family": "muslim"},
    {"id": "ismaili",           "ar": "إسماعيلي",          "en": "Ismaili",                     "family": "muslim"},

    # ── Druze ───────────────────────────────────────────────
    {"id": "druze",             "ar": "درزي",              "en": "Druze",                       "family": "druze"},

    # ── Jewish ──────────────────────────────────────────────
    {"id": "jewish",            "ar": "يهودي",             "en": "Jewish",                      "family": "jewish"},
]


SECT_IDS = frozenset(s["id"] for s in SECTS)


def is_valid_sect(value: str | None) -> bool:
    """True if value is a recognised Lebanese sect ID, or None
    (sect is optional / declined-to-state)."""
    if value is None or value == "":
        return True
    return value in SECT_IDS
