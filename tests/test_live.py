import pytest

from app.clinicaltrials.client import ClinicalTrialsClient
from app.schemas import QueryPlan
from app.settings import get_settings


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_aspirin_study_query():
    settings = get_settings()
    client = ClinicalTrialsClient(settings)
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
            "start_year": 2020,
            "end_year": 2022,
        },
        group_by=None,
        comparison_groups=[],
        comparison_group_type=None,
        network_entity_types=[],
        interpretation="Live count check",
    )
    try:
        studies, total, _, _ = await client.fetch(plan, 1000)
        assert total > 0
        assert studies
        for study in studies:
            date = study["protocolSection"]["statusModule"]["startDateStruct"]["date"]
            assert 2020 <= int(date[:4]) <= 2022
    finally:
        await client.close()
