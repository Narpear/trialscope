from app.aggregators import aggregate
from app.spec_builder import build_visualization


def test_grouped_comparison_encoding_specifies_series_and_offset(studies, make_plan):
    plan = make_plan(
        "comparison",
        group_by="phase",
        comparison_groups=["Tirofiban", "Placebo"],
    )
    result = aggregate(studies, plan)
    visualization = build_visualization(plan, result)
    encoding = visualization.encoding.model_dump(by_alias=True, exclude_none=True)
    assert visualization.type == "grouped_bar_chart"
    assert encoding["x"]["field"] == "category"
    assert encoding["xOffset"]["field"] == "group"
    assert encoding["color"]["field"] == "group"
