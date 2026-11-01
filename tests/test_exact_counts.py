import json
import re
from pathlib import Path

import httpx
import pytest

from app.clinicaltrials.client import ClinicalTrialsClient
from app.query_service import QueryService
from app.schemas import QueryRequest
from app.settings import Settings

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "aspirin_studies.json").read_text())
PHASE_TOTALS = {"PHASE4": 120, "PHASE3": 45, "MISSING": 7}
YEAR_TOTALS = {2019: 30, 2020: 0, 2021: 12}


def handler(request):
    """Fake registry: 500 matches, but only the two fixture studies are ever returned."""
    advanced = request.url.params.get("filter.advanced", "")
    if request.url.params.get("pageSize") == "1":
        phase = re.search(r"AREA\[Phase\](\w+)", advanced)
        year = re.search(r"RANGE\[(\d{4})-01-01,\d{4}-12-31\]$", advanced)
        if phase:
            total = PHASE_TOTALS.get(phase.group(1), 0)
        elif year:
            total = YEAR_TOTALS.get(int(year.group(1)), 0)
        else:
            total = 0
        return httpx.Response(200, json={"totalCount": total, "studies": []})
    return httpx.Response(200, json={"totalCount": 500, "studies": FIXTURE["studies"]})


def service(budget=40):
    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        clinicaltrials_requests_per_second=1000,
        exact_count_query_budget=budget,
    )
    client = ClinicalTrialsClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return QueryService(settings, client)


@pytest.mark.asyncio
async def test_truncated_distribution_uses_exact_bucket_counts():
    svc = service()
    try:
        response = await svc.query(
            QueryRequest(query="melanoma by phase", analysis_type="distribution", max_trials=2)
        )
    finally:
        await svc.close()
    rows = {row["category_code"]: row for row in response.visualization.data}
    assert {code: row["trial_count"] for code, row in rows.items()} == {
        "PHASE4": 120,
        "PHASE3": 45,
        "NOT_SPECIFIED": 7,
    }
    assert rows["PHASE4"]["sample_trial_count"] == 2
    assert rows["PHASE3"]["sample_trial_count"] == 0
    assert rows["PHASE3"]["citations"] == []
    assert "AREA%5BPhase%5DPHASE4" in rows["PHASE4"]["count_query_url"]
    assert response.meta.count_basis == "api_count_queries"
    assert response.meta.counts_exact is True
    assert response.meta.truncated is True


@pytest.mark.asyncio
async def test_truncated_time_trend_counts_every_year_including_zero():
    svc = service()
    try:
        response = await svc.query(
            QueryRequest(
                query="trials per year",
                analysis_type="time_trend",
                start_year=2019,
                end_year=2021,
                max_trials=2,
            )
        )
    finally:
        await svc.close()
    assert [(row["year"], row["trial_count"]) for row in response.visualization.data] == [
        (2019, 30),
        (2020, 0),
        (2021, 12),
    ]
    assert response.meta.counts_exact is True


@pytest.mark.asyncio
async def test_sample_only_analysis_warns_with_sample_size():
    svc = service()
    try:
        response = await svc.query(
            QueryRequest(query="countries", analysis_type="geographic", max_trials=2)
        )
    finally:
        await svc.close()
    assert response.meta.count_basis == "sample"
    assert response.meta.counts_exact is False
    assert response.meta.warnings[0].startswith("Counts are based on a sample of 2 of 500")


@pytest.mark.asyncio
async def test_count_query_budget_falls_back_to_sample():
    svc = service(budget=3)
    try:
        response = await svc.query(
            QueryRequest(query="by phase", analysis_type="distribution", max_trials=2)
        )
    finally:
        await svc.close()
    assert response.meta.count_basis == "sample"
    assert "count queries (limit 3)" in response.meta.warnings[0]
    assert all("count_query_url" not in row for row in response.visualization.data)


@pytest.mark.asyncio
async def test_complete_sample_needs_no_count_queries():
    calls = []

    def complete(request):
        calls.append(request)
        return httpx.Response(200, json={"totalCount": 2, "studies": FIXTURE["studies"]})

    settings = Settings(_env_file=None, openai_api_key=None)
    client = ClinicalTrialsClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(complete)))
    svc = QueryService(settings, client)
    try:
        response = await svc.query(QueryRequest(query="by phase", analysis_type="distribution"))
    finally:
        await svc.close()
    assert len(calls) == 1
    assert response.meta.count_basis == "complete_records"
    assert response.meta.counts_exact is True
