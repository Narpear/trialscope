from app.aggregators.common import (
    AggregateResult,
    AggregationOptions,
    Scope,
    categorical_rows,
    finish,
    nct_and_title,
)
from app.schemas import QueryPlan


def distribution(
    scopes: list[Scope], plan: QueryPlan, options: AggregationOptions
) -> AggregateResult:
    studies = scopes[0].studies
    dimension = plan.group_by or "phase"
    rows = categorical_rows(studies, dimension)
    represented = {nct_id for row in rows for nct_id in row["nct_ids"]}
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
