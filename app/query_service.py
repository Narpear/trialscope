from datetime import UTC, datetime
from typing import Any

from app.aggregators import AggregateResult, AggregationOptions, Scope, aggregate
from app.aggregators.common import parse_year, value_at
from app.clinicaltrials.client import ClinicalTrialsClient, ClinicalTrialsError
from app.exact_counts import CountOutcome, add_exact_counts
from app.planner.openai_planner import OpenAIPlanner, PlannerError, fallback_plan
from app.schemas import (
    AnalysisType,
    GroupQuery,
    PlanFilters,
    QueryPlan,
    QueryRequest,
    QueryResponse,
    ResponseMeta,
)
from app.settings import Settings
from app.spec_builder import build_visualization

PLAN_OVERRIDES = ("analysis_type", "group_by", "comparison_groups", "comparison_group_type")


def merge_explicit_filters(plan: QueryPlan, request: QueryRequest) -> QueryPlan:
    filters = plan.filters.model_dump()
    for field in PlanFilters.model_fields:
        explicit = getattr(request, field, None)
        if explicit is not None:
            filters[field] = explicit
    updates: dict[str, Any] = {"filters": PlanFilters.model_validate(filters)}
    for field in PLAN_OVERRIDES:
        explicit = getattr(request, field)
        if explicit is not None:
            updates[field] = explicit
    return plan.model_copy(update=updates)


def scope_plans(plan: QueryPlan) -> list[tuple[str | None, QueryPlan]]:
    """Return one retrieval plan per comparison group, or the plan itself otherwise."""
    if plan.analysis_type != AnalysisType.COMPARISON:
        return [(None, plan)]
    groups = list({group.strip().casefold(): group.strip() for group in plan.comparison_groups
                   if group.strip()}.values())
    if len(groups) < 2:
        raise PlannerError(
            "invalid_plan",
            "A comparison needs at least two distinct comparison_groups.",
            {"plan": plan.model_dump(mode="json")},
        )
    field = "condition" if plan.comparison_group_type == "condition" else "drug_name"
    return [
        (group, plan.model_copy(update={"filters": plan.filters.model_copy(update={field: group})}))
        for group in groups
    ]


def filter_years(studies: list[dict[str, Any]], plan: QueryPlan) -> list[dict[str, Any]]:
    if plan.filters.start_year is None and plan.filters.end_year is None:
        return studies
    filtered = []
    for study in studies:
        year = parse_year(value_at(study, "protocolSection.statusModule.startDateStruct.date"))
        if year is None:
            continue
        if plan.filters.start_year is not None and year < plan.filters.start_year:
            continue
        if plan.filters.end_year is not None and year > plan.filters.end_year:
            continue
        filtered.append(study)
    return filtered


class QueryService:
    def __init__(self, settings: Settings, client: ClinicalTrialsClient | None = None):
        self.settings = settings
        self.client = client or ClinicalTrialsClient(settings)
        self.planner = (
            OpenAIPlanner(settings.openai_api_key, settings.openai_model)
            if settings.openai_api_key
            else None
        )

    async def close(self) -> None:
        await self.client.close()
        if self.planner:
            await self.planner.client.close()

    async def _collect(self, label: str | None, plan: QueryPlan, max_trials: int) -> Scope:
        try:
            fetched, total, truncated, request_url = await self.client.fetch(plan, max_trials)
        except ClinicalTrialsError as exc:
            raise PlannerError("clinicaltrials_unavailable", str(exc)) from exc
        return Scope(
            label=label,
            studies=filter_years(fetched, plan),
            total=total,
            truncated=truncated or total > len(fetched),
            api_query_url=request_url,
        )

    def _describe_counts(
        self, result: AggregateResult, scopes: list[Scope], outcome: CountOutcome, max_trials: int
    ) -> None:
        """State plainly whether the visualized counts are registry totals or sample counts."""
        analyzed = sum(len(scope.studies) for scope in scopes)
        total = sum(scope.total for scope in scopes)
        assumptions = result.assumptions = result.assumptions or []
        warnings = result.warnings = result.warnings or []
        if outcome.basis == "complete_records":
            assumptions.append(
                f"All {total:,} matching trials were analyzed, so counts are exact registry totals."
            )
        elif outcome.basis == "api_count_queries":
            assumptions.append(
                "Each trial_count is an exact ClinicalTrials.gov total from one countTotal query "
                f"per bucket (count_query_url). The {analyzed:,} fetched trials supply citations "
                "and nct_ids only; sample_trial_count is how many of them fall in the bucket."
            )
        else:
            warnings.insert(
                0,
                f"Counts are based on a sample of {analyzed:,} of {total:,} matching trials (the "
                f"first {max_trials:,} per query in ClinicalTrials.gov's default order), so they "
                f"are not registry totals. {outcome.note} Raising max_trials (up to "
                f"{self.settings.max_trials_cap:,}) or narrowing the filters analyzes more trials.",
            )

    async def query(self, request: QueryRequest) -> QueryResponse:
        if self.planner:
            plan = await self.planner.plan(request)
            planner_mode = "llm"
        else:
            plan = fallback_plan(request)
            planner_mode = "fallback"
        if not plan.answerable:
            raise PlannerError(
                "unsupported_query",
                plan.unsupported_reason
                or "This question cannot be answered from ClinicalTrials.gov registry data.",
                {"plan": plan.model_dump(mode="json")},
            )
        plan = merge_explicit_filters(plan, request)
        max_trials = min(request.max_trials, self.settings.max_trials_cap)
        planned = scope_plans(plan)
        scopes = [await self._collect(label, scope_plan, max_trials) for label, scope_plan in planned]
        try:
            outcome = await add_exact_counts(
                self.client,
                [(scope_plan, scope) for (_, scope_plan), scope in zip(planned, scopes, strict=True)],
                self.settings.exact_count_query_budget,
            )
        except ClinicalTrialsError as exc:
            raise PlannerError("clinicaltrials_unavailable", str(exc)) from exc
        is_network = plan.analysis_type == AnalysisType.NETWORK
        result = aggregate(
            scopes,
            plan,
            AggregationOptions(
                network_top_n=self.settings.network_top_n,
                network_min_edge_weight=self.settings.network_min_edge_weight,
                network_excluded_interventions=self.settings.network_excluded_interventions,
            ),
        )
        if not result.data and not result.nodes and not result.warnings:
            result.warnings = ["No matching studies were available to visualize."]
        self._describe_counts(result, scopes, outcome, max_trials)
        visualization = build_visualization(plan, result)
        effective_filters = {
            key: value
            for key, value in plan.filters.model_dump(mode="json").items()
            if value is not None
        }
        return QueryResponse(
            visualization=visualization,
            meta=ResponseMeta(
                query_interpretation=plan.interpretation,
                plan=plan,
                planner_mode=planner_mode,
                filters_applied=effective_filters,
                total_matching=sum(scope.total for scope in scopes),
                trials_analyzed=sum(len(scope.studies) for scope in scopes),
                truncated=any(scope.truncated for scope in scopes),
                assumptions=result.assumptions or [],
                warnings=result.warnings or [],
                api_query_url=scopes[0].api_query_url,
                generated_at=datetime.now(UTC),
                total_citations=result.total_citations,
                counts_exact=outcome.basis != "sample",
                count_basis=outcome.basis,
                group_queries=[
                    GroupQuery(
                        group=scope.label,
                        total_matching=scope.total,
                        trials_analyzed=len(scope.studies),
                        truncated=scope.truncated,
                        api_query_url=scope.api_query_url,
                    )
                    for scope in scopes
                    if scope.label is not None
                ]
                or None,
                network_top_n=self.settings.network_top_n if is_network else None,
                network_min_edge_weight=self.settings.network_min_edge_weight
                if is_network
                else None,
                network_excluded_interventions=sorted(
                    {" ".join(name.casefold().split())
                     for name in self.settings.network_excluded_interventions}
                )
                if is_network
                else None,
            ),
        )
