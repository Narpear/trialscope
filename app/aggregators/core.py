import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from app.schemas import AnalysisType, QueryPlan

MAX_CITATIONS_PER_DATUM = 5


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


def with_citations(
    row: dict[str, Any], studies: list[tuple[dict[str, Any], str, Any]]
) -> dict[str, Any]:
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


def time_trend(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    buckets: dict[int, list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    missing = 0
    for study in studies:
        date = value_at(study, "protocolSection.statusModule.startDateStruct.date")
        year = parse_year(date)
        if year is None:
            missing += 1
            continue
        if plan.filters.start_year is not None and year < plan.filters.start_year:
            continue
        if plan.filters.end_year is not None and year > plan.filters.end_year:
            continue
        buckets[year].append((study, "protocolSection.statusModule.startDateStruct.date", date))
    rows = [
        with_citations(
            {"year": year, "year_date": f"{year:04d}-01-01", "trial_count": len(records)},
            records,
        )
        for year, records in sorted(buckets.items())
    ]
    return finish(
        AggregateResult(
            "time_series",
            "Clinical trials by start year",
            [],
            assumptions=[
                "Study start dates with month or day precision are bucketed by calendar year."
            ],
            warnings=[f"{missing} trials had no usable start date and were excluded."]
            if missing
            else [],
        ),
        rows,
    )


def _phase_values(study: dict[str, Any]) -> list[str]:
    raw = section(study, "designModule").get("phases") or []
    return [str(item).replace("_", " ").title() for item in raw] or ["Not specified"]


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
        return [(v, "protocolSection.conditionsModule.conditions", raw) for v in raw]
    return _group_values(study, "phase")


def distribution(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    dimension = plan.group_by or "phase"
    records: dict[str, list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    for study in studies:
        unique: dict[str, tuple[str, Any]] = {}
        for label, path, exact in _group_values(study, dimension):
            unique.setdefault(label, (path, exact))
        for label, (path, exact) in unique.items():
            records[label].append((study, path, exact))
    rows = [
        with_citations({"category": label, "trial_count": len(entries)}, entries)
        for label, entries in sorted(
            records.items(), key=lambda item: (-len(item[1]), item[0].casefold())
        )
    ]
    represented = {
        nct_and_title(study)[0] for entries in records.values() for study, _, _ in entries
    }
    missing = len({nct_and_title(study)[0] for study in studies} - represented)
    return finish(
        AggregateResult(
            "bar_chart",
            f"Trials by {dimension.replace('_', ' ')}",
            [],
            assumptions=["Studies with multiple values contribute once to each distinct category."],
            warnings=[f"{missing} trials had no value for {dimension}."] if missing else [],
        ),
        rows,
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _interventions(study: dict[str, Any], drug_only: bool = True) -> list[tuple[str, str, Any]]:
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


def comparison(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    groups = plan.comparison_groups or ([plan.filters.drug_name] if plan.filters.drug_name else [])
    groups = [g.strip() for g in groups if g and g.strip()]
    if not groups:
        groups = sorted(
            {
                _normalize(name): name for study in studies for name, _, _ in _interventions(study)
            }.values()
        )[:2]
    dimension = plan.group_by or "phase"
    evidence: dict[tuple[str, str], list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    for study in studies:
        names = _interventions(study)
        for group in groups:
            target = _normalize(group)
            matches = [(study, path, name) for name, path, _ in names if _normalize(name) == target]
            if not matches:
                continue
            group_evidence = matches[0]
            categories = {}
            for label, path, exact in _group_values(study, dimension):
                categories.setdefault(label, (path, exact))
            for category, (path, exact) in categories.items():
                evidence[(group, category)].extend([group_evidence, (study, path, exact)])
    rows = [
        with_citations({"group": group, "category": category}, entries)
        for (group, category), entries in sorted(evidence.items())
    ]
    return finish(
        AggregateResult(
            "grouped_bar_chart",
            f"Trials by {dimension.replace('_', ' ')}: comparison",
            [],
            assumptions=[
                "Intervention names are matched case-insensitively after whitespace normalization; brand and generic names are not merged."
            ],
            warnings=[
                "No explicit comparison groups were supplied; compared the two most frequent intervention names."
            ]
            if not plan.comparison_groups
            else [],
        ),
        rows,
    )


def geographic(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    records: dict[str, list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    status_path = "protocolSection.statusModule.overallStatus"
    status_filter = (
        plan.filters.recruitment_status.value if plan.filters.recruitment_status else None
    )
    missing = 0
    for study in studies:
        status = value_at(study, status_path)
        if status_filter and status != status_filter:
            continue
        locations = section(study, "contactsLocationsModule").get("locations") or []
        countries = {loc.get("country") for loc in locations if loc.get("country")}
        if not countries:
            missing += 1
        for country in countries:
            records[country].append(
                (study, "protocolSection.contactsLocationsModule.locations[].country", country)
            )
    rows = [
        with_citations(
            {"country": country, "trial_count": len({nct_and_title(s)[0] for s, _, _ in entries})},
            entries,
        )
        for country, entries in sorted(records.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    return finish(
        AggregateResult(
            "bar_chart",
            "Clinical trials by country",
            [],
            assumptions=[
                "Each trial contributes once per distinct country with a reported study location."
            ],
            warnings=[f"{missing} trials had no country location and were excluded."]
            if missing
            else [],
        ),
        rows,
    )


def network(
    studies: list[dict[str, Any]], plan: QueryPlan, top_n: int = 30, min_edge_weight: int = 2
) -> AggregateResult:
    entities = plan.network_entity_types or ["sponsor", "drug"]
    edge_records: dict[tuple[str, str], dict[str, list[tuple[dict[str, Any], str, Any]]]] = (
        defaultdict(dict)
    )
    node_records: dict[tuple[str, str], dict[str, Any]] = {}

    def add_node(
        kind: str, label: str, study: dict[str, Any], path: str, value: Any
    ) -> tuple[str, str]:
        node_id = f"{kind}:{_normalize(label)}"
        item = node_records.setdefault(
            (kind, node_id), {"id": node_id, "label": label, "type": kind, "nct_ids": set()}
        )
        item["nct_ids"].add(nct_and_title(study)[0])
        item.setdefault("_evidence", []).append((study, path, value))
        return kind, node_id

    for study in studies:
        nodes: dict[str, list[tuple[str, str]]] = defaultdict(list)
        node_evidence: dict[str, tuple[dict[str, Any], str, Any]] = {}
        if "sponsor" in entities:
            label = value_at(study, "protocolSection.sponsorCollaboratorsModule.leadSponsor.name")
            if label:
                node = add_node(
                    "sponsor",
                    label,
                    study,
                    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
                    label,
                )
                nodes["sponsor"].append(node)
                node_evidence[node[1]] = (
                    study,
                    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
                    label,
                )
        if "drug" in entities:
            nodes["drug"] = [
                add_node("drug", name, study, path, value)
                for name, path, value in _interventions(study)
            ]
            for name, path, value in _interventions(study):
                node_evidence[f"drug:{_normalize(name)}"] = (study, path, value)
        if "condition" in entities:
            raw = value_at(study, "protocolSection.conditionsModule.conditions") or []
            nodes["condition"] = [
                add_node(
                    "condition", name, study, "protocolSection.conditionsModule.conditions", raw
                )
                for name in dict.fromkeys(raw)
            ]
            for name in dict.fromkeys(raw):
                node_evidence[f"condition:{_normalize(name)}"] = (
                    study,
                    "protocolSection.conditionsModule.conditions",
                    raw,
                )
        selected: list[tuple[str, str]] = []
        if len(entities) == 2:
            selected = list(combinations(entities, 2))
        elif len(entities) > 2:
            selected = [("sponsor", "drug"), ("condition", "drug")]
        for left_type, right_type in selected:
            for left in nodes[left_type]:
                for right in nodes[right_type]:
                    source, target = sorted([left[1], right[1]])
                    support = [
                        node_evidence[node_id]
                        for node_id in (left[1], right[1])
                        if node_id in node_evidence
                    ]
                    if support:
                        edge_records[(source, target)][nct_and_title(study)[0]] = support
        if entities == ["drug"] or (len(entities) == 1 and entities[0] == "drug"):
            for left, right in combinations(sorted({node[1] for node in nodes["drug"]}), 2):
                edge_records[(left, right)][nct_and_title(study)[0]] = [
                    node_evidence[node_id] for node_id in (left, right) if node_id in node_evidence
                ]

    ranked = sorted(
        node_records.values(), key=lambda n: (-len(n["nct_ids"]), n["label"].casefold())
    )[:top_n]
    allowed_nodes = {n["id"] for n in ranked}
    nodes_out = [
        {
            "id": node["id"],
            "label": node["label"],
            "type": node["type"],
            "weight": len(node["nct_ids"]),
            "nct_ids": sorted(node["nct_ids"]),
            "citations": [
                citation(*entry) for entry in node["_evidence"][:MAX_CITATIONS_PER_DATUM]
            ],
        }
        for node in ranked
    ]
    edges_out = []
    for (source, target), by_trial in edge_records.items():
        if (
            source not in allowed_nodes
            or target not in allowed_nodes
            or len(by_trial) < min_edge_weight
        ):
            continue
        entries = [entry for trial_entries in by_trial.values() for entry in trial_entries]
        edges_out.append(
            {
                "source": source,
                "target": target,
                "weight": len(by_trial),
                "nct_ids": list(by_trial),
                "citations": [citation(*entry) for entry in entries[:MAX_CITATIONS_PER_DATUM]],
            }
        )
    edges_out.sort(key=lambda edge: (-edge["weight"], edge["source"], edge["target"]))
    result = AggregateResult(
        "network_graph",
        "Clinical trial relationships",
        [],
        nodes=nodes_out,
        edges=edges_out,
        assumptions=[
            "Intervention labels are normalized by case and whitespace only; brand/generic variants remain separate."
        ],
    )
    result.total_citations = sum(len(node["citations"]) for node in nodes_out) + sum(
        len(edge["citations"]) for edge in edges_out
    )
    return result


def histogram(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    observations: list[tuple[float, dict[str, Any], Any]] = []
    missing = 0
    for study in studies:
        raw = value_at(study, "protocolSection.designModule.enrollmentInfo.count")
        if isinstance(raw, (int, float)) and raw >= 0:
            observations.append((float(raw), study, raw))
        else:
            missing += 1
    if not observations:
        return AggregateResult(
            "histogram",
            "Enrollment size distribution",
            [],
            warnings=["No studies reported an enrollment count."],
        )
    low, high = min(o[0] for o in observations), max(o[0] for o in observations)
    width = max(1.0, (high - low) / 10)
    bins: dict[int, list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    for value, study, raw in observations:
        idx = min(9, int((value - low) / width))
        bins[idx].append((study, "protocolSection.designModule.enrollmentInfo.count", raw))
    rows = [
        with_citations(
            {
                "bin_start": int(low + idx * width),
                "bin_end": int(high if idx == 9 else low + (idx + 1) * width),
                "trial_count": len(records),
            },
            records,
        )
        for idx, records in sorted(bins.items())
    ]
    return finish(
        AggregateResult(
            "histogram",
            "Enrollment size distribution",
            [],
            assumptions=[
                "Ten equal-width bins over reported enrollment; enrollment is the registry's reported target or actual count."
            ],
            warnings=[f"{missing} trials had no numeric enrollment count and were excluded."]
            if missing
            else [],
        ),
        rows,
    )


def scatter(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    rows = []
    missing = 0
    for study in studies:
        raw = value_at(study, "protocolSection.designModule.enrollmentInfo.count")
        date = value_at(study, "protocolSection.statusModule.startDateStruct.date")
        year = parse_year(date)
        if not isinstance(raw, (int, float)) or year is None:
            missing += 1
            continue
        row = {
            "start_year": year,
            "enrollment": raw,
            "nct_id": nct_and_title(study)[0],
            "title": nct_and_title(study)[1],
            "trial_count": 1,
        }
        row["citations"] = [
            citation(study, "protocolSection.designModule.enrollmentInfo.count", raw),
            citation(study, "protocolSection.statusModule.startDateStruct.date", date),
        ]
        row["nct_ids"] = [row["nct_id"]]
        rows.append(row)
    return finish(
        AggregateResult(
            "scatter_plot",
            "Enrollment versus start year",
            [],
            assumptions=["Start dates of month/day precision are plotted at the calendar year."],
            warnings=[
                f"{missing} trials lacked a usable start year or numeric enrollment and were excluded."
            ]
            if missing
            else [],
        ),
        rows,
    )


AGGREGATORS: dict[AnalysisType, Callable[..., AggregateResult]] = {
    AnalysisType.TIME_TREND: time_trend,
    AnalysisType.DISTRIBUTION: distribution,
    AnalysisType.COMPARISON: comparison,
    AnalysisType.GEOGRAPHIC: geographic,
    AnalysisType.NETWORK: network,
    AnalysisType.HISTOGRAM: histogram,
    AnalysisType.SCATTER: scatter,
}
