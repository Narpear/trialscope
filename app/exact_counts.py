"""Exact registry totals for truncated samples, using one countTotal query per bucket.

Records fetched for an analysis are capped (``max_trials``), so a sample-based count
under-reports any query with more matches than the cap. Time trends and fixed-category
distributions/comparisons can instead be counted exactly: each bucket (a start year, or a
phase/status/intervention-type/sponsor-class code) is a ClinicalTrials.gov query whose
``totalCount`` is the answer. The fetched sample still supplies citations.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from app.aggregators.common import BucketCount, Scope
from app.aggregators.dimensions import COUNTABLE_DIMENSIONS, bucket_clauses
from app.clinicaltrials.client import ClinicalTrialsClient
from app.schemas import AnalysisType, CountBasis, QueryPlan

MISSING_START_DATE = "AREA[StartDate]MISSING"


@dataclass
class CountOutcome:
    basis: CountBasis
    note: str | None = None


def counted_dimension(plan: QueryPlan) -> str | None:
    """The dimension whose buckets can be counted exactly, or None for sample-only analyses."""
    if plan.analysis_type == AnalysisType.TIME_TREND:
        return "start_year"
    if plan.analysis_type in (AnalysisType.DISTRIBUTION, AnalysisType.COMPARISON):
        dimension = plan.group_by or "phase"
        return dimension if dimension in COUNTABLE_DIMENSIONS else None
    return None


async def _year_clauses(client: ClinicalTrialsClient, plan: QueryPlan) -> dict[Any, str]:
    start, end = plan.filters.start_year, plan.filters.end_year
    if start is None or end is None:
        bounds = await client.start_year_bounds(plan.filters)
        if bounds is None:
            return {}
        start = bounds[0] if start is None else start
        end = bounds[1] if end is None else min(end, bounds[1])
    return {year: f"AREA[StartDate]RANGE[{year}-01-01,{year}-12-31]" for year in range(start, end + 1)}


async def add_exact_counts(
    client: ClinicalTrialsClient,
    scopes: list[tuple[QueryPlan, Scope]],
    budget: int,
) -> CountOutcome:
    """Attach exact bucket counts to truncated scopes when the query budget allows it."""
    truncated = [(plan, scope) for plan, scope in scopes if scope.truncated]
    if not truncated:
        return CountOutcome("complete_records")
    dimension = counted_dimension(truncated[0][0])
    if dimension is None:
        return CountOutcome(
            "sample", "Exact registry totals are not available for this analysis type."
        )

    planned: list[tuple[QueryPlan, Scope, dict[Any, str]]] = []
    for plan, scope in truncated:
        if dimension == "start_year":
            clauses = await _year_clauses(client, plan)
        else:
            clauses = bucket_clauses(dimension)
        planned.append((plan, scope, clauses))
    filters = truncated[0][0].filters
    # A start-year filter already excludes undated studies at the API.
    needs_missing = (
        dimension == "start_year" and filters.start_year is None and filters.end_year is None
    )
    queries = sum(len(clauses) + needs_missing for _, _, clauses in planned)
    if queries > budget:
        return CountOutcome(
            "sample",
            f"Exact totals would need {queries} ClinicalTrials.gov count queries (limit "
            f"{budget}); narrow the year range or other filters for exact counts.",
        )

    for plan, scope, clauses in planned:
        keys = list(clauses)
        results = await asyncio.gather(
            *(client.count(plan.filters, clauses[key]) for key in keys)
        )
        scope.bucket_counts = {
            key: BucketCount(count, url) for key, (count, url) in zip(keys, results, strict=True)
        }
        if needs_missing:
            scope.missing_count, _ = await client.count(plan.filters, MISSING_START_DATE)
    return CountOutcome("api_count_queries")
