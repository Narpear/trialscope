from collections import defaultdict
from typing import Any

from app.aggregators.common import (
    AggregateResult,
    _group_values,
    finish,
    nct_and_title,
    with_citations,
)
from app.schemas import QueryPlan


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
