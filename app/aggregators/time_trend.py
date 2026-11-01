from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.aggregators.common import (
    AggregateResult,
    AggregationOptions,
    Scope,
    apply_exact_count,
    finish,
    parse_year,
    value_at,
    with_citations,
)
from app.schemas import QueryPlan


def time_trend(
    scopes: list[Scope], plan: QueryPlan, options: AggregationOptions
) -> AggregateResult:
    scope = scopes[0]
    buckets: dict[int, list[tuple[dict[str, Any], str, Any]]] = defaultdict(list)
    missing = 0
    for study in scope.studies:
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
    if scope.bucket_counts is not None:
        years = sorted(scope.bucket_counts)
    else:
        years = year_range(plan, buckets) if buckets else []
    rows = []
    for year in years:
        row = with_citations({"year": year, "year_date": f"{year:04d}-01-01"}, buckets.get(year, []))
        if scope.bucket_counts is not None:
            apply_exact_count(row, scope.bucket_counts[year])
        rows.append(row)
    if scope.missing_count is not None:
        missing = scope.missing_count
    return finish(
        AggregateResult(
            "time_series",
            "Clinical trials by start year",
            [],
            assumptions=[
                "Study start dates with month or day precision are bucketed by calendar year.",
                "Every year in the range is listed; years with no trials have trial_count 0.",
                *calendar_notes(rows),
            ],
            warnings=[f"{missing} trials had no usable start date and were excluded."]
            if missing
            else [],
        ),
        rows,
    )


def year_range(plan: QueryPlan, buckets: dict[int, Any]) -> list[int]:
    """Consecutive years from the requested (or first observed) start to the last relevant year.

    An end_year beyond the data stops at the later of the last observed year and the current
    year, so a far-future end_year does not produce a long run of empty years.
    """
    start = plan.filters.start_year if plan.filters.start_year is not None else min(buckets)
    end = max(buckets)
    if plan.filters.end_year is not None:
        end = min(plan.filters.end_year, max(end, current_year()))
    return list(range(start, end + 1))


def calendar_notes(rows: list[dict[str, Any]]) -> list[str]:
    this_year = current_year()
    notes = []
    future = [row for row in rows if row["year"] > this_year and row["trial_count"]]
    if future:
        trials = sum(row["trial_count"] for row in future)
        notes.append(
            f"{trials} trials have anticipated start dates after {this_year} "
            f"({future[0]['year']}–{future[-1]['year']}); registries record planned start "
            "dates, so these trials have not started yet."
        )
    if any(row["year"] == this_year for row in rows):
        notes.append(f"{this_year} is in progress, so its count is not final.")
    return notes


def current_year() -> int:
    return datetime.now(UTC).year
