from app.aggregators.common import (
    AggregateResult,
    AggregationOptions,
    Scope,
    categorical_rows,
    finish,
    group_membership,
    nct_and_title,
)
from app.schemas import QueryPlan


def comparison(scopes: list[Scope], plan: QueryPlan, options: AggregationOptions) -> AggregateResult:
    """Group each comparison scope (one API query per group) by the same dimension."""
    dimension = plan.group_by or "phase"
    group_type = plan.comparison_group_type or "drug"
    rows = []
    unmatched = 0
    for scope in scopes:
        membership = {}
        for study in scope.studies:
            evidence = group_membership(study, group_type, scope.label or "")
            if evidence:
                membership[nct_and_title(study)[0]] = evidence
            else:
                unmatched += 1
        for row in categorical_rows(scope.studies, dimension, membership):
            rows.append({"group": scope.label, **row})
    search_field = "query.intr" if group_type == "drug" else "query.cond"
    return finish(
        AggregateResult(
            "grouped_bar_chart",
            f"Trials by {dimension.replace('_', ' ')}: "
            + " vs ".join(scope.label or "" for scope in scopes),
            [],
            assumptions=[
                (
                    f"Each group is a separate ClinicalTrials.gov {search_field} search, so group "
                    "membership follows the registry's own search (including its synonym "
                    "matching). A trial matching several groups is counted in each."
                ),
                "Studies with multiple values contribute once to each distinct category.",
            ],
            warnings=[
                (
                    f"{unmatched} matched trials had no {group_type} field containing the group "
                    "term (the registry matched them through synonyms or other fields); they are "
                    "counted but cited only by their category value."
                )
            ]
            if unmatched
            else [],
        ),
        rows,
    )
