from typing import Any

from app.aggregators.common import (
    AggregateResult,
    citation,
    finish,
    nct_and_title,
    parse_year,
    value_at,
)
from app.schemas import QueryPlan


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
        nct_id, title = nct_and_title(study)
        row = {
            "start_year": year,
            "enrollment": raw,
            "nct_id": nct_id,
            "title": title,
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
