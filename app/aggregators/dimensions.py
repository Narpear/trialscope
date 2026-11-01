"""Registry categories that ClinicalTrials.gov can count exactly with one query per bucket."""

NOT_SPECIFIED = "NOT_SPECIFIED"

# Search area and the complete set of registry codes for each countable dimension.
COUNTABLE_DIMENSIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "phase": ("Phase", ("EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA")),
    "status": (
        "OverallStatus",
        (
            "RECRUITING",
            "NOT_YET_RECRUITING",
            "ENROLLING_BY_INVITATION",
            "ACTIVE_NOT_RECRUITING",
            "COMPLETED",
            "SUSPENDED",
            "TERMINATED",
            "WITHDRAWN",
            "UNKNOWN",
            "AVAILABLE",
            "NO_LONGER_AVAILABLE",
            "TEMPORARILY_NOT_AVAILABLE",
            "APPROVED_FOR_MARKETING",
            "WITHHELD",
        ),
    ),
    "intervention_type": (
        "InterventionType",
        (
            "DRUG",
            "BIOLOGICAL",
            "DEVICE",
            "PROCEDURE",
            "RADIATION",
            "BEHAVIORAL",
            "GENETIC",
            "DIETARY_SUPPLEMENT",
            "COMBINATION_PRODUCT",
            "DIAGNOSTIC_TEST",
            "OTHER",
        ),
    ),
    "sponsor_class": (
        "LeadSponsorClass",
        ("INDUSTRY", "NIH", "FED", "OTHER_GOV", "INDIV", "NETWORK", "AMBIG", "OTHER", "UNKNOWN"),
    ),
}

# Dimensions where every study has a value, so no "not specified" bucket is queried.
ALWAYS_PRESENT = {"status"}


def bucket_clauses(dimension: str) -> dict[str, str]:
    area, codes = COUNTABLE_DIMENSIONS[dimension]
    clauses = {code: f"AREA[{area}]{code}" for code in codes}
    if dimension not in ALWAYS_PRESENT:
        clauses[NOT_SPECIFIED] = f"AREA[{area}]MISSING"
    return clauses


def category_label(code: str) -> str:
    return "Not specified" if code == NOT_SPECIFIED else code.replace("_", " ").title()
