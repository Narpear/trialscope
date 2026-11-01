from datetime import UTC, datetime
from typing import Any

from app.aggregators import aggregate
from app.clinicaltrials.client import ClinicalTrialsClient, ClinicalTrialsError
from app.planner.openai_planner import OpenAIPlanner, PlannerError, fallback_plan
from app.schemas import (
    AnalysisType,
    PlanFilters,
    QueryPlan,
    QueryRequest,
    QueryResponse,
    ResponseMeta,
)
from app.settings import Settings
from app.spec_builder import build_visualization


def merge_explicit_filters(plan: QueryPlan, request: QueryRequest) -> QueryPlan:
    filters = plan.filters.model_dump()
    for field in PlanFilters.model_fields:
        explicit = getattr(request, field, None)
        if explicit is not None:
            filters[field] = explicit
    updates: dict[str, Any] = {"filters": PlanFilters.model_validate(filters)}
    if request.analysis_type is not None:
        updates["analysis_type"] = request.analysis_type
    return plan.model_copy(update=updates)


def filter_years(studies: list[dict[str, Any]], plan: QueryPlan) -> list[dict[str, Any]]:
    if plan.filters.start_year is None and plan.filters.end_year is None:
        return studies
    from app.aggregators.core import parse_year, value_at

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
        try:
            fetched, total, truncated, request_url = await self.client.fetch(plan, max_trials)
        except ClinicalTrialsError as exc:
            raise PlannerError("clinicaltrials_unavailable", str(exc)) from exc
        filtered = filter_years(fetched, plan)
        result = aggregate(
            filtered,
            plan,
            self.settings.network_top_n,
            self.settings.network_min_edge_weight,
            self.settings.network_excluded_interventions,
        )
        if not result.data and not result.nodes and not result.warnings:
            result.warnings = ["No matching studies were available to visualize."]
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
                total_matching=total,
                trials_analyzed=len(filtered),
                truncated=truncated or total > len(fetched),
                assumptions=result.assumptions or [],
                warnings=result.warnings or [],
                api_query_url=request_url,
                generated_at=datetime.now(UTC),
                total_citations=result.total_citations,
                network_top_n=self.settings.network_top_n
                if plan.analysis_type == AnalysisType.NETWORK
                else None,
                network_min_edge_weight=self.settings.network_min_edge_weight
                if plan.analysis_type == AnalysisType.NETWORK
                else None,
                network_excluded_interventions=sorted(
                    {" ".join(name.casefold().split()) for name in self.settings.network_excluded_interventions}
                )
                if plan.analysis_type == AnalysisType.NETWORK
                else None,
            ),
        )
