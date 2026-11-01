import json
from pathlib import Path

import pytest

from app.aggregators import Scope
from app.schemas import QueryPlan


def scope(studies, label=None):
    return [Scope(label, studies, len(studies), False, "https://example.test/studies")]

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "aspirin_studies.json"


@pytest.fixture
def studies():
    return json.loads(FIXTURE_PATH.read_text())["studies"]


@pytest.fixture
def pembrolizumab_studies():
    path = Path(__file__).parent / "fixtures" / "pembrolizumab_lung_cancer_studies.json"
    return json.loads(path.read_text())["studies"]


@pytest.fixture
def make_plan():
    def factory(analysis_type, **overrides):
        values = {
            "answerable": True,
            "unsupported_reason": None,
            "analysis_type": analysis_type,
            "filters": {
                "drug_name": None,
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
            "comparison_group_type": None,
            "network_entity_types": [],
            "interpretation": "Test registry query",
        }
        values.update(overrides)
        return QueryPlan.model_validate(values)

    return factory
