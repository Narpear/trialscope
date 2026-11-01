import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.schemas import QueryPlan, QueryRequest


class PlannerError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class OpenAIPlanner:
    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def plan(self, request: QueryRequest) -> QueryPlan:
        validation_feedback = ""
        schema = QueryPlan.model_json_schema()
        for attempt in range(2):
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "Plan a clinical-trial registry query. Output only the requested "
                                "structured plan. Use only supported registry information. Mark "
                                "unanswerable when the question asks for clinical conclusions, "
                                "outcomes absent from the returned registry fields, or unrelated "
                                "information. Never produce counts, data points, or citations. "
                                "Filters should reflect the user's intent. Choose distribution "
                                "when one study population is grouped by a single registry "
                                "category such as phase, intervention type, condition, or sponsor; "
                                "phrases like 'across phases', 'by phase', 'most common "
                                "intervention types', and 'distribution' do not by themselves "
                                "mean comparison. Choose comparison only when the user explicitly "
                                "asks to compare two or more named groups, such as drug A versus "
                                "drug B or condition A against condition B; put each compared entity in "
                                "comparison_groups, set comparison_group_type to drug or condition, "
                                "and do not repeat the compared entities in filters. Sponsor categories "
                                "or sponsor types (industry, NIH, other government, etc.) use "
                                "group_by=sponsor_class. For an unanswerable "
                                "question, set answerable=false and provide a concise "
                                "unsupported_reason; the analysis_type is unused in that case. "
                                "Descriptive plots of supported registry fields are answerable: "
                                "in particular, a request to plot numeric enrollment against study "
                                "start year is a scatter query, not a request for clinical "
                                "effectiveness or causation."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Question: {request.query}\n"
                                f"Explicit structured filters: {json.dumps(request.model_dump(mode='json'))}\n"
                                f"{validation_feedback}"
                            ),
                        },
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "query_plan",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                )
                if not response.output_text:
                    raise PlannerError("planner_empty_response", "The planner returned no plan.")
                return QueryPlan.model_validate_json(response.output_text)
            except ValidationError as exc:
                validation_feedback = (
                    "The prior response failed validation. Correct these errors and retry: "
                    f"{exc.errors(include_url=False)}"
                )
                if attempt:
                    raise PlannerError(
                        "planner_invalid_plan",
                        "The planner returned an invalid plan after one retry.",
                        {"validation_errors": exc.errors(include_url=False)},
                    ) from exc
            except PlannerError:
                raise
            except Exception as exc:
                raise PlannerError("planner_unavailable", "The planning provider failed.") from exc
        raise PlannerError("planner_invalid_plan", "The planner could not produce a valid plan.")


def fallback_plan(request: QueryRequest) -> QueryPlan:
    if request.analysis_type is None:
        raise PlannerError(
            "planner_key_required",
            "Set OPENAI_API_KEY or provide analysis_type for deterministic fallback planning.",
        )
    return QueryPlan(
        answerable=True,
        unsupported_reason=None,
        analysis_type=request.analysis_type,
        filters={
            "drug_name": request.drug_name,
            "condition": request.condition,
            "sponsor": request.sponsor,
            "phase": request.phase,
            "country": request.country,
            "recruitment_status": request.recruitment_status,
            "start_year": request.start_year,
            "end_year": request.end_year,
        },
        group_by=request.group_by
        or ("phase" if request.analysis_type in ("distribution", "comparison") else None),
        comparison_groups=request.comparison_groups or [],
        comparison_group_type=request.comparison_group_type
        or ("drug" if request.analysis_type == "comparison" else None),
        network_entity_types=["sponsor", "drug"] if request.analysis_type == "network" else [],
        interpretation=f"Deterministic {request.analysis_type.value} requested by caller.",
    )
