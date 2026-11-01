"""Semantic checks applied after Pydantic validation of a plan.

Pydantic guarantees the plan's shape; these rules make sure its fields fit together for the
chosen analysis. Fields that the analysis does not use are dropped, defaults are filled in,
and each change is recorded so the response can report it. Plans that cannot be executed
raise ``invalid_plan``.
"""

from typing import Any

from app.planner.openai_planner import PlannerError
from app.schemas import AnalysisType, QueryPlan

MAX_COMPARISON_GROUPS = 4
CATEGORICAL = {AnalysisType.DISTRIBUTION, AnalysisType.COMPARISON}


def _invalid(message: str, plan: QueryPlan) -> PlannerError:
    return PlannerError("invalid_plan", message, {"plan": plan.model_dump(mode="json")})


def validate_plan(plan: QueryPlan) -> tuple[QueryPlan, list[str]]:
    """Return an executable plan and notes describing every adjustment made to it."""
    kind = plan.analysis_type
    updates: dict[str, Any] = {}
    filter_updates: dict[str, Any] = {}
    notes: list[str] = []

    if kind in CATEGORICAL:
        if plan.group_by is None:
            updates["group_by"] = "phase"
            notes.append("No grouping was specified; grouped by phase.")
    elif plan.group_by is not None:
        updates["group_by"] = None
        notes.append(f"Dropped group_by={plan.group_by}, which {kind.value} does not use.")

    if kind == AnalysisType.COMPARISON:
        groups = list(
            {g.strip().casefold(): g.strip() for g in plan.comparison_groups if g.strip()}.values()
        )
        if len(groups) < 2:
            raise _invalid("A comparison needs at least two distinct comparison_groups.", plan)
        if len(groups) != len(plan.comparison_groups):
            notes.append("Removed blank or duplicate comparison groups.")
        if len(groups) > MAX_COMPARISON_GROUPS:
            notes.append(
                f"Compared only the first {MAX_COMPARISON_GROUPS} groups: "
                + ", ".join(groups[:MAX_COMPARISON_GROUPS])
                + "."
            )
            groups = groups[:MAX_COMPARISON_GROUPS]
        updates["comparison_groups"] = groups
        group_type = plan.comparison_group_type
        if group_type is None:
            group_type = updates["comparison_group_type"] = "drug"
            notes.append("No comparison group type was specified; compared groups as drugs.")
        replaced = "drug_name" if group_type == "drug" else "condition"
        if getattr(plan.filters, replaced) is not None:
            filter_updates[replaced] = None
            notes.append(
                f"Dropped the {replaced} filter ({getattr(plan.filters, replaced)!r}); each "
                f"comparison group supplies its own {replaced}."
            )
    else:
        if plan.comparison_groups:
            updates["comparison_groups"] = []
            notes.append(f"Dropped comparison_groups, which {kind.value} does not use.")
        if plan.comparison_group_type is not None:
            updates["comparison_group_type"] = None

    if kind == AnalysisType.NETWORK:
        entities = list(dict.fromkeys(plan.network_entity_types))
        if len(entities) != len(plan.network_entity_types):
            notes.append("Removed duplicate network entity types.")
        if not entities:
            entities = ["sponsor", "drug"]
            notes.append("No network entity types were specified; linked sponsors and drugs.")
        if entities in (["sponsor"], ["condition"]):
            raise _invalid(
                f"A {entities[0]}-only network has no edges; include drugs or a second "
                "entity type.",
                plan,
            )
        updates["network_entity_types"] = entities
    elif plan.network_entity_types:
        updates["network_entity_types"] = []
        notes.append(f"Dropped network_entity_types, which {kind.value} does not use.")

    if filter_updates:
        updates["filters"] = plan.filters.model_copy(update=filter_updates)
    return plan.model_copy(update=updates), notes
