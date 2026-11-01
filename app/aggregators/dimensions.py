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


# Display labels follow ClinicalTrials.gov's own wording where it has one.
LABELS: dict[str, dict[str, str]] = {
    "phase": {
        "EARLY_PHASE1": "Early Phase 1",
        "PHASE1": "Phase 1",
        "PHASE2": "Phase 2",
        "PHASE3": "Phase 3",
        "PHASE4": "Phase 4",
        "NA": "Not Applicable",
    },
    "status": {
        "RECRUITING": "Recruiting",
        "NOT_YET_RECRUITING": "Not yet recruiting",
        "ENROLLING_BY_INVITATION": "Enrolling by invitation",
        "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
        "COMPLETED": "Completed",
        "SUSPENDED": "Suspended",
        "TERMINATED": "Terminated",
        "WITHDRAWN": "Withdrawn",
        "UNKNOWN": "Unknown status",
        "AVAILABLE": "Available (expanded access)",
        "NO_LONGER_AVAILABLE": "No longer available (expanded access)",
        "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available (expanded access)",
        "APPROVED_FOR_MARKETING": "Approved for marketing (expanded access)",
        "WITHHELD": "Withheld",
    },
    "intervention_type": {"DIETARY_SUPPLEMENT": "Dietary Supplement"},
    "sponsor_class": {
        "INDUSTRY": "Industry",
        "NIH": "NIH",
        "FED": "U.S. federal (non-NIH)",
        "OTHER_GOV": "Other government",
        "INDIV": "Individual",
        "NETWORK": "Network",
        "AMBIG": "Ambiguous",
        "OTHER": "Other (academic, hospital, nonprofit)",
        "UNKNOWN": "Unknown",
    },
}


def category_label(dimension: str, code: str) -> str:
    if code == NOT_SPECIFIED:
        return "Not specified"
    return LABELS.get(dimension, {}).get(code) or code.replace("_", " ").title()
