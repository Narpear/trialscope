from collections import defaultdict
from typing import Any

from app.aggregators.common import (
    AggregateResult,
    AggregationOptions,
    Scope,
    finish,
    nct_and_title,
    section,
    value_at,
    with_citations,
)
from app.schemas import QueryPlan


def geographic(
    scopes: list[Scope], plan: QueryPlan, options: AggregationOptions
) -> AggregateResult:
    studies = scopes[0].studies
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
        countries = {location.get("country") for location in locations if location.get("country")}
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
