from collections import defaultdict
from typing import Any

from app.aggregators.common import AggregateResult, finish, value_at, with_citations
from app.schemas import QueryPlan


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
    low, high = min(item[0] for item in observations), max(item[0] for item in observations)
    width = max(1.0, (high - low) / 10)
    bins: dict[int, list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    for value, study, raw in observations:
        index = min(9, int((value - low) / width))
        bins[index].append((study, "protocolSection.designModule.enrollmentInfo.count", raw))
    rows = [
        with_citations(
            {
                "bin_start": int(low + index * width),
                "bin_end": int(high if index == 9 else low + (index + 1) * width),
                "trial_count": len(records),
            },
            records,
        )
        for index, records in sorted(bins.items())
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
