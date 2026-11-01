import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.schemas import QueryPlan, QueryRequest

SYSTEM_PROMPT = """\
You turn a question about clinical trials into a query plan for the ClinicalTrials.gov \
registry. You only plan: the service retrieves the records and computes every number, so \
never put counts, data points, trial IDs or citations in the plan.

Answerability. A question is answerable when it asks about what registry fields record: \
how many trials there are, when they started, their phases, recruitment statuses, lead \
sponsors and sponsor types, conditions, interventions and intervention types, site \
countries, and enrollment counts. Describing or plotting these fields is answerable for any \
drug or disease. Set answerable=false with a short unsupported_reason when the answer needs \
something these fields do not contain: whether a treatment works or is better, safety, \
adverse events, survival or other outcomes, causal claims, or topics unrelated to clinical \
trials. analysis_type is ignored for unanswerable plans.

Analysis types. Choose by the shape of the answer:
- time_trend: number of trials per start year.
- distribution: one set of trials split into the categories of a single field, given by \
group_by: phase, status (overall recruitment status), intervention_type, sponsor (lead \
sponsor name), sponsor_class (industry, NIH, other government, network, individual, other) \
or condition.
- comparison: the same category split shown side by side for two to four groups that the \
question names. Each group is a drug or a condition: list them in comparison_groups, set \
comparison_group_type, and pick group_by as for distribution. Do not repeat the groups in \
filters. A single set of trials split by a field is a distribution, not a comparison.
- geographic: number of trials per country with study sites.
- network: links between entities that appear in the same trials. network_entity_types lists \
the linked kinds (sponsor, drug, condition); use only drug for drugs tested together.
- histogram: how trial enrollment sizes are distributed.
- scatter: one point per trial, enrollment against start year.

Filters. Set a filter only when the question restricts which trials count, and leave the \
rest null. drug_name and condition are search terms: use the user's wording without adding \
synonyms or boolean operators. Map recruitment wording to recruitment_status, phase wording \
to phase, and year limits (since, before, between) to start_year and end_year. Explicit \
structured filters supplied with the question take precedence.

Leave group_by, comparison_groups, comparison_group_type and network_entity_types null or \
empty when the chosen analysis does not use them. interpretation is one sentence restating \
the plan."""


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
                            "content": SYSTEM_PROMPT,
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
        group_by=request.group_by,
        comparison_groups=request.comparison_groups or [],
        comparison_group_type=request.comparison_group_type,
        network_entity_types=[],
        interpretation=f"Deterministic {request.analysis_type.value} requested by caller.",
    )
