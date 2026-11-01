from collections import defaultdict
from typing import Any

from app.aggregators.common import (
    AggregateResult,
    _group_values,
    _interventions,
    _normalize,
    finish,
    with_citations,
)
from app.schemas import QueryPlan


def comparison(studies: list[dict[str, Any]], plan: QueryPlan) -> AggregateResult:
    groups = plan.comparison_groups or ([plan.filters.drug_name] if plan.filters.drug_name else [])
    groups = [group.strip() for group in groups if group and group.strip()]
    if not groups:
        groups = sorted(
            {
                _normalize(name): name
                for study in studies
                for name, _, _ in _interventions(study)
            }.values()
        )[:2]
    dimension = plan.group_by or "phase"
    evidence: dict[tuple[str, str], list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    for study in studies:
        names = _interventions(study)
        for group in groups:
            target = _normalize(group)
            matches = [
                (study, path, name) for name, path, _ in names if _normalize(name) == target
            ]
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
