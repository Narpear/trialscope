from collections import defaultdict
from itertools import combinations
from typing import Any

from app.aggregators.common import (
    MAX_CITATIONS_PER_DATUM,
    AggregateResult,
    _interventions,
    _normalize,
    citation,
    nct_and_title,
    value_at,
)
from app.schemas import QueryPlan


def network(
    studies: list[dict[str, Any]],
    plan: QueryPlan,
    top_n: int = 30,
    min_edge_weight: int = 2,
    excluded_interventions: list[str] | None = None,
) -> AggregateResult:
    entities = plan.network_entity_types or ["sponsor", "drug"]
    excluded = {_normalize(name) for name in excluded_interventions or []}
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
            names = [
                item
                for item in _interventions(study)
                if _normalize(item[0]) not in excluded
            ]
            nodes["drug"] = [
                add_node("drug", name, study, path, value) for name, path, value in names
            ]
            for name, path, value in names:
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
        if len(entities) == 1 and entities[0] == "drug":
            for left, right in combinations(sorted({node[1] for node in nodes["drug"]}), 2):
                edge_records[(left, right)][nct_and_title(study)[0]] = [
                    node_evidence[node_id] for node_id in (left, right) if node_id in node_evidence
                ]

    ranked = sorted(
        node_records.values(), key=lambda node: (-len(node["nct_ids"]), node["label"].casefold())
    )[:top_n]
    allowed_nodes = {node["id"] for node in ranked}
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
            "Intervention labels are normalized by case and whitespace only; brand/generic variants remain separate.",
            (
                "Configured generic intervention names are excluded from drug nodes and edges: "
                + ", ".join(sorted(excluded))
                + "."
            )
            if excluded
            else "No generic intervention names are excluded.",
        ],
    )
    result.total_citations = sum(len(node["citations"]) for node in nodes_out) + sum(
        len(edge["citations"]) for edge in edges_out
    )
    return result
