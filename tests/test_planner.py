from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.planner.openai_planner import OpenAIPlanner, PlannerError, fallback_plan
from app.schemas import QueryPlan, QueryRequest


def plan_payload():
    return {
        "answerable": True,
        "unsupported_reason": None,
        "analysis_type": "time_trend",
        "filters": {
            "drug_name": "aspirin",
            "condition": None,
            "sponsor": None,
            "phase": None,
            "country": None,
            "recruitment_status": None,
            "start_year": None,
            "end_year": None,
        },
        "group_by": None,
        "comparison_groups": [],
        "network_entity_types": [],
        "interpretation": "Count aspirin trials by start year.",
    }


@pytest.mark.asyncio
async def test_openai_planner_validates_structured_output():
    planner = OpenAIPlanner("not-a-real-test-key", "gpt-5.4-mini")
    planner.client = SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    output_text=QueryPlan(**plan_payload()).model_dump_json()
                )
            )
        )
    )
    plan = await planner.plan(QueryRequest(query="How many aspirin trials by year?"))
    assert plan.analysis_type == "time_trend"
    assert planner.client.responses.create.await_count == 1


@pytest.mark.asyncio
async def test_openai_planner_retries_validation_once():
    planner = OpenAIPlanner("not-a-real-test-key", "gpt-5.4-mini")
    planner.client = SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                side_effect=[
                    SimpleNamespace(output_text='{"answerable": true}'),
                    SimpleNamespace(output_text=QueryPlan(**plan_payload()).model_dump_json()),
                ]
            )
        )
    )
    plan = await planner.plan(QueryRequest(query="How many aspirin trials by year?"))
    assert plan.analysis_type == "time_trend"
    assert planner.client.responses.create.await_count == 2


@pytest.mark.asyncio
async def test_openai_planner_returns_structured_error_after_second_invalid_response():
    planner = OpenAIPlanner("not-a-real-test-key", "gpt-5.4-mini")
    planner.client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(output_text="{}")))
    )
    with pytest.raises(PlannerError) as error:
        await planner.plan(QueryRequest(query="How many trials?"))
    assert error.value.code == "planner_invalid_plan"
    assert planner.client.responses.create.await_count == 2


def test_fallback_requires_analysis_type_and_uses_structured_filters():
    with pytest.raises(PlannerError):
        fallback_plan(QueryRequest(query="trials over time"))
    request = QueryRequest(query="trials by phase", analysis_type="distribution", phase="PHASE3")
    plan = fallback_plan(request)
    assert plan.analysis_type == "distribution"
    assert plan.filters.phase == "PHASE3"
