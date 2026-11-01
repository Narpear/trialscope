import json
from pathlib import Path

import httpx
import pytest

from app.clinicaltrials.client import ClinicalTrialsClient
from app.schemas import QueryPlan
from app.settings import Settings


@pytest.mark.asyncio
async def test_fetch_paginates_and_caches_fixture():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "aspirin_studies.json").read_text())
    calls = []

    async def handler(request):
        calls.append(request)
        token = request.url.params.get("pageToken")
        study = fixture["studies"][1 if token else 0]
        content = {"studies": [study]}
        if not token:
            content["totalCount"] = 2
            content["nextPageToken"] = "page-2"
        return httpx.Response(200, json=content)

    client = ClinicalTrialsClient(
        Settings(_env_file=None, openai_api_key=None),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    plan = QueryPlan(
        answerable=True,
        unsupported_reason=None,
        analysis_type="time_trend",
        filters={
            "drug_name": "aspirin",
            "condition": None,
            "sponsor": None,
            "phase": None,
            "country": None,
            "recruitment_status": None,
            "start_year": None,
            "end_year": None,
        },
        group_by=None,
        comparison_groups=[],
        comparison_group_type=None,
        network_entity_types=[],
        interpretation="Count by year",
    )
    studies, total, truncated, url = await client.fetch(plan, 2)
    assert len(studies) == 2
    assert total == 2
    assert truncated is False
    assert "query.intr=aspirin" in url
    assert len(calls) == 2
    await client.fetch(plan, 2)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_invalid_api_json_is_reported():
    async def handler(request):
        return httpx.Response(200, text="not-json")

    client = ClinicalTrialsClient(
        Settings(_env_file=None, openai_api_key=None),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    plan = QueryPlan(
        answerable=True,
        unsupported_reason=None,
        analysis_type="time_trend",
        filters={
            "drug_name": None,
            "condition": None,
            "sponsor": None,
            "phase": None,
            "country": None,
            "recruitment_status": None,
            "start_year": None,
            "end_year": None,
        },
        group_by=None,
        comparison_groups=[],
        comparison_group_type=None,
        network_entity_types=[],
        interpretation="Count by year",
    )
    from app.clinicaltrials.client import ClinicalTrialsError

    with pytest.raises(ClinicalTrialsError, match="invalid JSON"):
        await client.fetch(plan, 2)


def test_year_filters_use_verified_advanced_query():
    plan = QueryPlan(
        answerable=True,
        unsupported_reason=None,
        analysis_type="time_trend",
        filters={
            "drug_name": None,
            "condition": None,
            "sponsor": None,
            "phase": None,
            "country": None,
            "recruitment_status": None,
            "start_year": 2020,
            "end_year": 2022,
        },
        group_by=None,
        comparison_groups=[],
        comparison_group_type=None,
        network_entity_types=[],
        interpretation="Count by year",
    )
    params = ClinicalTrialsClient.build_params(plan, 10)
    assert params["filter.advanced"] == "AREA[StartDate]RANGE[2020-01-01,2022-12-31]"


def test_analysis_requests_only_its_required_fields(make_plan):
    trend = ClinicalTrialsClient.build_params(make_plan("time_trend"), 20)
    comparison = ClinicalTrialsClient.build_params(make_plan("comparison", group_by="phase"), 20)
    assert set(trend["fields"].split(",")) == {"BriefTitle", "NCTId", "StartDate"}
    assert set(comparison["fields"].split(",")) == {
        "BriefTitle",
        "InterventionName",
        "InterventionOtherName",
        "NCTId",
        "Phase",
    }


def test_phase_filter_uses_advanced_query_combined_with_dates(make_plan):
    filters = {
        "drug_name": None,
        "condition": None,
        "sponsor": None,
        "phase": "PHASE3",
        "country": None,
        "recruitment_status": None,
        "start_year": 2018,
        "end_year": None,
    }
    params = ClinicalTrialsClient.build_params(make_plan("time_trend", filters=filters), 10)
    assert "filter.phase" not in params
    assert params["filter.advanced"] == (
        "AREA[Phase]PHASE3 AND AREA[StartDate]RANGE[2018-01-01,2100-12-31]"
    )
