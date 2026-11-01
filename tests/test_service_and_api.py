import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.planner.openai_planner import PlannerError
from app.query_service import QueryService, merge_explicit_filters
from app.schemas import QueryPlan, QueryRequest
from app.settings import Settings


def test_explicit_filters_and_analysis_override_plan(make_plan=None):
    plan = QueryPlan(
        answerable=True,
        unsupported_reason=None,
        analysis_type="distribution",
        filters={
            "drug_name": "model drug",
            "condition": None,
            "sponsor": None,
            "phase": None,
            "country": None,
            "recruitment_status": None,
            "start_year": None,
            "end_year": None,
        },
        group_by="phase",
        comparison_groups=[],
        comparison_group_type=None,
        network_entity_types=[],
        interpretation="Plan",
    )
    request = QueryRequest(
        query="Compare treatments", drug_name="explicit drug", analysis_type="comparison"
    )
    merged = merge_explicit_filters(plan, request)
    assert merged.filters.drug_name == "explicit drug"
    assert merged.analysis_type == "comparison"


def test_health_schema_root_and_validation_error():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        schema = client.get("/api/schema").json()
        assert "properties" in schema["request"]
        assert "visualization" in schema["response"]["properties"]
        response = client.post("/api/query", json={"query": " ", "max_trials": 1})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert client.get("/").status_code == 200


@pytest.mark.asyncio
async def test_service_no_key_fallback_and_explicit_type():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "aspirin_studies.json").read_text())

    async def handler(request):
        return httpx.Response(200, json={"totalCount": 2, "studies": fixture["studies"]})

    settings = Settings(_env_file=None, openai_api_key=None)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    from app.clinicaltrials.client import ClinicalTrialsClient

    service = QueryService(settings, ClinicalTrialsClient(settings, client))
    try:
        response = await service.query(
            QueryRequest(
                query="trials started by year", analysis_type="time_trend", drug_name="aspirin"
            )
        )
        assert response.meta.planner_mode == "fallback"
        assert response.meta.trials_analyzed == 2
        assert response.meta.total_citations == 2
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_service_reports_network_exclusion_metadata():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "aspirin_studies.json").read_text())

    async def handler(request):
        return httpx.Response(200, json={"totalCount": 2, "studies": fixture["studies"]})

    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        network_excluded_interventions=[" PLACEBO "],
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    from app.clinicaltrials.client import ClinicalTrialsClient

    service = QueryService(settings, ClinicalTrialsClient(settings, client))
    try:
        response = await service.query(
            QueryRequest(query="show a sponsor and drug network", analysis_type="network")
        )
        assert response.meta.network_excluded_interventions == ["placebo"]
        assert all(
            node["label"].casefold() != "placebo" for node in response.visualization.nodes or []
        )
    finally:
        await service.close()


def test_rate_limiter_rejects_excess_requests():
    from app.rate_limit import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("127.0.0.1")
    assert limiter.allow("127.0.0.1")
    assert not limiter.allow("127.0.0.1")


@pytest.mark.asyncio
async def test_comparison_queries_each_group_separately():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "aspirin_studies.json").read_text())
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"totalCount": 2, "studies": fixture["studies"]})

    settings = Settings(_env_file=None, openai_api_key=None)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    from app.clinicaltrials.client import ClinicalTrialsClient

    service = QueryService(settings, ClinicalTrialsClient(settings, client))
    try:
        response = await service.query(
            QueryRequest(
                query="Compare phases for breast versus prostate cancer trials",
                analysis_type="comparison",
                comparison_groups=["breast cancer", "prostate cancer"],
                comparison_group_type="condition",
                group_by="sponsor_class",
                country="United States",
            )
        )
        searched = [request.url.params.get("query.cond") for request in requests]
        assert searched == ["breast cancer", "prostate cancer"]
        assert all(request.url.params.get("query.locn") == "United States" for request in requests)
        assert [query.group for query in response.meta.group_queries] == searched
        assert {row["group"] for row in response.visualization.data} == set(searched)
        assert {row["category_code"] for row in response.visualization.data} <= {
            "INDUSTRY", "OTHER", "NIH", "FED", "OTHER_GOV", "INDIV", "NETWORK", "AMBIG", "UNKNOWN"
        }
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_comparison_without_two_groups_is_rejected():
    settings = Settings(_env_file=None, openai_api_key=None)
    service = QueryService(settings)
    try:
        with pytest.raises(PlannerError) as error:
            await service.query(QueryRequest(query="Compare trials", analysis_type="comparison"))
        assert error.value.code == "invalid_plan"
    finally:
        await service.close()
