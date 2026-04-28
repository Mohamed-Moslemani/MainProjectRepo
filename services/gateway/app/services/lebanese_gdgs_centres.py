"""GDGS centre directory for biometric appointments.

The General Directorate of General Security operates regional
branches across Lebanon's eight governorates. Citizens applying for
a new passport must visit one of these for fingerprint capture.

Slugs are stable IDs the API uses; bilingual names + addresses are
for SPA display. Coordinates are approximate — used to compute
"nearest centre to your registry place" in the booking UI.

Production should pull this from a config table editable by an admin
without redeploy; for now the static list captures all current
public-facing branches (as of GDGS's 2025 listings).
"""

GDGS_CENTRES: list[dict] = [
    {
        "id": "gdgs-beirut-mathaf",
        "ar": "الأمن العام - بيروت (المتحف)",
        "en": "GDGS - Beirut (Museum)",
        "address_en": "Damascus Road, Beirut",
        "governorate": "Beirut",
        "lat": 33.8830, "lng": 35.5165,
    },
    {
        "id": "gdgs-baabda",
        "ar": "الأمن العام - بعبدا",
        "en": "GDGS - Baabda",
        "address_en": "Baabda Government Serail",
        "governorate": "Mount Lebanon",
        "lat": 33.8345, "lng": 35.5419,
    },
    {
        "id": "gdgs-jounieh",
        "ar": "الأمن العام - جونية",
        "en": "GDGS - Jounieh",
        "address_en": "Jounieh, Keserwan",
        "governorate": "Mount Lebanon",
        "lat": 33.9809, "lng": 35.6178,
    },
    {
        "id": "gdgs-tripoli",
        "ar": "الأمن العام - طرابلس",
        "en": "GDGS - Tripoli",
        "address_en": "Government Serail, Tripoli",
        "governorate": "North Lebanon",
        "lat": 34.4360, "lng": 35.8497,
    },
    {
        "id": "gdgs-halba",
        "ar": "الأمن العام - حلبا",
        "en": "GDGS - Halba",
        "address_en": "Halba, Akkar",
        "governorate": "Akkar",
        "lat": 34.5447, "lng": 36.0853,
    },
    {
        "id": "gdgs-saida",
        "ar": "الأمن العام - صيدا",
        "en": "GDGS - Saida",
        "address_en": "Government Serail, Saida",
        "governorate": "South Lebanon",
        "lat": 33.5571, "lng": 35.3717,
    },
    {
        "id": "gdgs-nabatieh",
        "ar": "الأمن العام - النبطية",
        "en": "GDGS - Nabatieh",
        "address_en": "Government Serail, Nabatieh",
        "governorate": "Nabatieh",
        "lat": 33.3786, "lng": 35.4839,
    },
    {
        "id": "gdgs-zahle",
        "ar": "الأمن العام - زحلة",
        "en": "GDGS - Zahle",
        "address_en": "Government Serail, Zahle",
        "governorate": "Beqaa",
        "lat": 33.8463, "lng": 35.9019,
    },
    {
        "id": "gdgs-baalbek",
        "ar": "الأمن العام - بعلبك",
        "en": "GDGS - Baalbek",
        "address_en": "Government Serail, Baalbek",
        "governorate": "Baalbek-Hermel",
        "lat": 34.0058, "lng": 36.2153,
    },
]


CENTRE_IDS = frozenset(c["id"] for c in GDGS_CENTRES)


def is_valid_centre(centre_id: str | None) -> bool:
    return centre_id in CENTRE_IDS


def find_centre(centre_id: str) -> dict | None:
    for c in GDGS_CENTRES:
        if c["id"] == centre_id:
            return c
    return None
