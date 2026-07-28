"""
Classifies raw_hospitals.json (Overpass output) into primary/secondary/tertiary
tiers and writes std_hospitals.json, sorted tertiary -> secondary -> primary.

Fixes over the earlier version:
  1. Facility TYPE is checked before brand-name keywords, so a small branded
     "clinic" (e.g. "The Apollo Clinic") can no longer be misclassified as
     tertiary just because the brand name matches a flagship hospital chain.
  2. Bare `amenity=hospital` with no `emergency` tag now defaults to
     SECONDARY, not primary. OSM's `emergency` tag is sparse/rarely filled by
     mappers — treating "untagged" the same as "confirmed no ER" was
     silently demoting real hospitals to primary. Missing data != no capability.
  3. `is_clinic()` is a single source of truth for "this is not an inpatient
     hospital", used consistently everywhere instead of scattered checks.

This is still name/tag pattern-matching, not verified clinical data — OSM has
no ICU/trauma/bed-count fields. Treat `verify_recommended=True` rows (tertiary
and secondary) as a checklist for manual confirmation before trusting them in
a routing decision. Primary-tier entries are lower-stakes for an ambulance
routing use case (rarely the destination for an emergency), so left
best-effort.
"""

import json
from pathlib import Path

INPUT_PATH = Path("raw_hospitals.json")
OUTPUT_PATH = Path("std_hospitals.json")

# Facilities that are not general emergency-capable hospitals at all —
# excluded outright regardless of any other tag/keyword.
EXCLUDE_KEYWORDS = [
    "dental", "optical", "opticals", "eye care", "eye hospital",
    "homeopath", "homoeopath", "veterinary", "vet clinic", "vet hospital",
    "physiotherapy", "physio", "ayurved", "arya vaidya", "unani",
    "skin clinic", "dermat", "ivf", "fertility", "diagnostic",
    "diagnostics", "pathology", "path lab", "pharmacy", "chemist",
    "cosmetic", "aesthetic", "spa", "wellness centre", "wellness center",
]

# Facility-type signals that mean "this is a clinic/outpatient point,
# not an inpatient hospital" — checked BEFORE any brand keyword, so a
# branded outpatient clinic can never be promoted to tertiary/secondary.
CLINIC_TYPE_SIGNALS = [
    "clinic", "dispensary", "polyclinic", "consultation",
    "diagnostic centre", "diagnostic center", "day care",
]

# Small/basic public-health-tier facilities.
PRIMARY_KEYWORDS = [
    "primary health centre", "primary health center", "phc",
    "urban health centre", "urban health center",
    "health centre", "health center", "sub centre", "sub center",
    "nursing home", "maternity home",
]

# Real-world knowledge: major multi-specialty / teaching / referral / trauma
# institutions in Bengaluru. Only applies once we've confirmed (below) the
# element is an actual hospital, not a clinic bearing the same brand name.
TERTIARY_KEYWORDS = [
    "medical college", "institute of medical", "institute", "research institute",
    "multispeciality", "multi-speciality", "multispecialty", "multi-specialty",
    "super speciality", "superspeciality", "super specialty", "superspecialty",
    "teaching hospital", "trauma center", "trauma centre",
    "nimhans", "victoria hospital", "bowring", "vani vilas",
    "manipal hospital", "manipal hospitals",
    "narayana health", "narayana hrudayalaya", "narayana institute",
    "fortis hospital", "fortis hospitals",
    "apollo hospital", "apollo hospitals",
    "aster cmi", "aster rv", "aster hospital",
    "sparsh hospital", "columbia asia", "vikram hospital",
    "mazumdar shaw", "mazumdar-shaw", "st john's medical",
    "st. john's medical", "bgs gleneagles", "sagar hospital",
    "hosmat", "jayadeva", "kidwai", "people tree hospital",
    "sri jayadeva", "rajarajeswari medical", "ramaiah medical",
    "m s ramaiah", "bangalore medical college", "bmcri",
    "command hospital", "cauvery hospital",
]

# Signals that a general (non-clinic) hospital does have real emergency /
# inpatient capability, even without matching a big-brand keyword.
SECONDARY_POSITIVE_SIGNALS = ["emergency", "trauma", "icu", "24 hour", "24/7", "24x7"]


def is_clinic(name_lower: str, tags: dict) -> bool:
    amenity = tags.get("amenity", "")
    healthcare = tags.get("healthcare", "")
    if amenity == "clinic" or healthcare == "clinic":
        return True
    return any(sig in name_lower for sig in CLINIC_TYPE_SIGNALS)


def is_excluded(name_lower: str) -> bool:
    return any(kw in name_lower for kw in EXCLUDE_KEYWORDS)


def classify(tags: dict) -> tuple:
    """Returns (tier, verify_recommended)."""
    name_lower = tags.get("name", "").strip().lower()
    amenity = tags.get("amenity", "")
    emergency = tags.get("emergency", "").strip().lower()
    healthcare_speciality = tags.get("healthcare:speciality", "").lower()

    clinic = is_clinic(name_lower, tags)

    # --- Primary tier: explicit small-facility signals, or any clinic ---
    if clinic:
        return "primary", False
    if any(kw in name_lower for kw in PRIMARY_KEYWORDS):
        return "primary", False

    # --- Tertiary tier: only reachable for confirmed non-clinic hospitals ---
    if any(kw in name_lower for kw in TERTIARY_KEYWORDS):
        return "tertiary", True
    if healthcare_speciality and "," in healthcare_speciality:
        # multiple listed specialities on a real hospital tag is a decent
        # multi-specialty signal even without a brand-name match
        if amenity == "hospital":
            return "tertiary", True

    # --- Secondary tier: bare `amenity=hospital` defaults here now,  ---
    # --- since missing `emergency` tag != confirmed no capability     ---
    if amenity == "hospital":
        if emergency == "no":
            # explicitly tagged as NOT having emergency care — genuine signal,
            # not just missing data, so this is the one case we keep at primary
            return "primary", False
        return "secondary", True  # covers "yes", "unknown", and untagged

    # --- Fallback for anything else (e.g. healthcare=* without amenity=hospital) ---
    return "primary", False


def extract_latlon(el: dict):
    lat = el.get("lat")
    lon = el.get("lon")
    if lat is None or lon is None:
        center = el.get("center", {})
        lat, lon = center.get("lat"), center.get("lon")
    return lat, lon


def process():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    elements = raw.get("elements", [])
    seen = set()
    cleaned = []

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            continue

        name_lower = name.lower()
        if is_excluded(name_lower):
            continue

        lat, lon = extract_latlon(el)
        if lat is None or lon is None:
            continue

        key = (name_lower, round(lat, 4), round(lon, 4))
        if key in seen:
            continue
        seen.add(key)

        tier, verify_recommended = classify(tags)

        cleaned.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "type": tier,
            "verify_recommended": verify_recommended,
            "emergency": tags.get("emergency", "unknown"),
            "operator_type": tags.get("operator:type", "unknown"),
            "phone": tags.get("phone", tags.get("contact:phone", "")),
            "addr_street": tags.get("addr:street", ""),
        })

    tier_order = {"tertiary": 0, "secondary": 1, "primary": 2}
    cleaned.sort(key=lambda h: (tier_order.get(h["type"], 3), h["name"].lower()))

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)

    counts = {}
    for h in cleaned:
        counts[h["type"]] = counts.get(h["type"], 0) + 1

    verify_count = sum(1 for h in cleaned if h["verify_recommended"])

    print(f"Processed {len(elements)} raw elements -> {len(cleaned)} clean hospitals")
    print(f"Breakdown: {counts}")
    print(f"Flagged for manual verification (tertiary + secondary): {verify_count}")
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    process()