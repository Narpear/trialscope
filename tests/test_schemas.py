import pytest
from pydantic import ValidationError

from app.schemas import QueryRequest


def test_query_request_defaults_and_trim():
    request = QueryRequest(query="  trials by phase ")
    assert request.query == "trials by phase"
    assert request.max_trials == 5000


@pytest.mark.parametrize(
    "payload",
    [
        {"query": " "},
        {"query": "trials", "start_year": 2025, "end_year": 2020},
        {"query": "trials", "phase": "PHASE5"},
        {"query": "trials", "max_trials": 10001},
        {"query": "trials", "unknown": "value"},
    ],
)
def test_invalid_requests_are_rejected(payload):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate(payload)
