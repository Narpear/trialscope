from collections import defaultdict
from typing import Any

from app.aggregators.common import (
    AggregateResult,
    AggregationOptions,
    Scope,
    finish,
    parse_year,
    value_at,
    with_citations,
)
from app.schemas import QueryPlan


def time_trend(
    scopes: list[Scope], plan: QueryPlan, options: AggregationOptions
) -> AggregateResult:
    studies = scopes[0].studies
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
