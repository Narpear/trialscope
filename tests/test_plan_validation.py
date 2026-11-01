import pytest

from app.planner.openai_planner import PlannerError
from app.planner.validation import validate_plan

FILTERS = {
    "drug_name": "pembrolizumab OR nivolumab",
    "condition": "melanoma",
    "sponsor": None,
    "phase": None,
    "country": None,
    "recruitment_status": None,
    "start_year": None,
    "end_year": None,
}


def test_comparison_drops_filter_replaced_by_groups_and_fills_defaults(make_plan):
    plan, notes = validate_plan(
        make_plan(
            "comparison",
            filters=FILTERS,
            comparison_groups=["Pembrolizumab", " pembrolizumab ", "Nivolumab"],
        )
    )
    assert plan.comparison_groups == ["pembrolizumab", "Nivolumab"]
    assert plan.comparison_group_type == "drug"
    assert plan.group_by == "phase"
    assert plan.filters.drug_name is None
    assert plan.filters.condition == "melanoma"
    assert len(notes) == 4


@pytest.mark.parametrize("groups", [[], ["pembrolizumab"], ["x", " X "]])
def test_comparison_needs_two_distinct_groups(make_plan, groups):
    with pytest.raises(PlannerError) as error:
        validate_plan(make_plan("comparison", comparison_groups=groups))
    assert error.value.code == "invalid_plan"


def test_network_deduplicates_entity_types(make_plan):
    plan, notes = validate_plan(make_plan("network", network_entity_types=["drug", "drug"]))
    assert plan.network_entity_types == ["drug"]
    assert notes == ["Removed duplicate network entity types."]


def test_single_non_drug_network_is_rejected(make_plan):
    with pytest.raises(PlannerError):
        validate_plan(make_plan("network", network_entity_types=["sponsor"]))


def test_irrelevant_fields_are_dropped_with_notes(make_plan):
    plan, notes = validate_plan(
        make_plan(
            "geographic",
            group_by="condition",
            comparison_groups=["a", "b"],
            network_entity_types=["drug"],
        )
    )
    assert plan.group_by is None
    assert plan.comparison_groups == []
    assert plan.network_entity_types == []
    assert len(notes) == 3


def test_valid_plan_is_unchanged(make_plan):
    original = make_plan("distribution", group_by="sponsor_class")
    plan, notes = validate_plan(original)
    assert plan == original
    assert notes == []
