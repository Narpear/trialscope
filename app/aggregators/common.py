import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

MAX_CITATIONS_PER_DATUM = 5

Evidence = tuple[dict[str, Any], str, Any]


@dataclass
class Scope:
    """Studies returned by one ClinicalTrials.gov query: the whole request or one comparison group."""

    label: str | None
    studies: list[dict[str, Any]]
    total: int
    truncated: bool
    api_query_url: str


@dataclass
class AggregationOptions:
    network_top_n: int = 30
    network_min_edge_weight: int = 2
    network_excluded_interventions: list[str] = field(default_factory=list)


@dataclass
class AggregateResult:
    visualization_type: str
    title: str
    data: list[dict[str, Any]]
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    assumptions: list[str] | None = None
    warnings: list[str] | None = None
    total_citations: int = 0


def section(study: dict[str, Any], module: str) -> dict[str, Any]:
    return study.get("protocolSection", {}).get(module, {}) or {}


def value_at(study: dict[str, Any], path: str) -> Any:
    value: Any = study
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def nct_and_title(study: dict[str, Any]) -> tuple[str, str]:
    ident = section(study, "identificationModule")
    return str(ident.get("nctId", "unknown")), str(ident.get("briefTitle", "Untitled study"))


def citation(study: dict[str, Any], path: str, exact: Any) -> dict[str, Any]:
    nct_id, title = nct_and_title(study)
    return {"nct_id": nct_id, "field_path": path, "exact_value": exact, "title": title}


def with_citations(row: dict[str, Any], studies: list[Evidence]) -> dict[str, Any]:
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for study, path, exact in studies:
        ref = citation(study, path, exact)
        unique.setdefault((ref["nct_id"], path, repr(exact)), ref)
    refs = list(unique.values())
    trial_ids = list(dict.fromkeys(ref["nct_id"] for ref in refs))
    row["trial_count"] = len(trial_ids)
    row["nct_ids"] = trial_ids
    row["citations"] = refs[:MAX_CITATIONS_PER_DATUM]
    return row


def finish(result: AggregateResult, rows: list[dict[str, Any]]) -> AggregateResult:
    result.data = rows
    result.total_citations = sum(len(row.get("citations", [])) for row in rows)
    return result


def parse_year(value: Any) -> int | None:
    if not isinstance(value, str) or not re.match(r"^\d{4}(?:-\d{2})?(?:-\d{2})?$", value):
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _group_values(study: dict[str, Any], dimension: str) -> list[tuple[str, str, Any]]:
    if dimension == "phase":
        raw = section(study, "designModule").get("phases") or []
        return [
            (v.replace("_", " ").title(), "protocolSection.designModule.phases", raw) for v in raw
        ] or [("Not specified", "protocolSection.designModule.phases", raw)]
    if dimension == "sponsor":
        raw = section(study, "sponsorCollaboratorsModule").get("leadSponsor", {}).get("name")
        return (
            [(raw, "protocolSection.sponsorCollaboratorsModule.leadSponsor.name", raw)]
            if raw
            else []
        )
    if dimension == "sponsor_class":
        raw = section(study, "sponsorCollaboratorsModule").get("leadSponsor", {}).get("class")
        return (
            [(raw, "protocolSection.sponsorCollaboratorsModule.leadSponsor.class", raw)]
            if raw
            else []
        )
    if dimension == "intervention_type":
        raw = section(study, "armsInterventionsModule").get("interventions") or []
        return [
            (
                item.get("type", "Not specified").title(),
                "protocolSection.armsInterventionsModule.interventions[].type",
                item.get("type"),
            )
            for item in raw
        ]
    if dimension == "condition":
        raw = section(study, "conditionsModule").get("conditions") or []
        return [(value, "protocolSection.conditionsModule.conditions", raw) for value in raw]
    raise ValueError(f"Unsupported grouping dimension: {dimension}")


def categorical_rows(
    studies: list[dict[str, Any]],
    dimension: str,
    extra_evidence: dict[str, Evidence] | None = None,
) -> list[dict[str, Any]]:
    """Count each study once per distinct category value, citing the category field.

    ``extra_evidence`` maps an NCT ID to an additional citation (such as comparison-group
    membership) placed before that study's category citation.
    """
    records: dict[str, list[Evidence]] = defaultdict(list)
    for study in studies:
        unique: dict[str, tuple[str, Any]] = {}
        for label, path, exact in _group_values(study, dimension):
            unique.setdefault(label, (path, exact))
        membership = (extra_evidence or {}).get(nct_and_title(study)[0])
        for label, (path, exact) in unique.items():
            if membership:
                records[label].append(membership)
            records[label].append((study, path, exact))
    return [
        with_citations({"category": label}, entries)
        for label, entries in sorted(
            records.items(),
            key=lambda item: (-len({nct_and_title(s)[0] for s, _, _ in item[1]}), item[0].casefold()),
        )
    ]


def group_membership(
    study: dict[str, Any], group_type: str, group: str
) -> Evidence | None:
    """Find the record field showing why ClinicalTrials.gov matched ``study`` to ``group``."""
    term = _normalize(group)
    if group_type == "drug":
        interventions = section(study, "armsInterventionsModule").get("interventions") or []
        for item in interventions:
            if term in _normalize(item.get("name", "")):
                return (
                    study,
                    "protocolSection.armsInterventionsModule.interventions[].name",
                    item["name"],
                )
        for item in interventions:
            for other in item.get("otherNames") or []:
                if term in _normalize(other):
                    return (
                        study,
                        "protocolSection.armsInterventionsModule.interventions[].otherNames",
                        other,
                    )
        return None
    conditions = section(study, "conditionsModule").get("conditions") or []
    if any(term in _normalize(value) for value in conditions):
        return study, "protocolSection.conditionsModule.conditions", conditions
    keywords = section(study, "conditionsModule").get("keywords") or []
    if any(term in _normalize(value) for value in keywords):
        return study, "protocolSection.conditionsModule.keywords", keywords
    return None


def _interventions(
    study: dict[str, Any], drug_only: bool = True
) -> list[tuple[str, str, Any]]:
    raw = section(study, "armsInterventionsModule").get("interventions") or []
    values = []
    for item in raw:
        if drug_only and item.get("type", "").upper() != "DRUG":
            continue
        name = item.get("name")
        if name:
            values.append(
                (name, "protocolSection.armsInterventionsModule.interventions[].name", name)
            )
    return values
