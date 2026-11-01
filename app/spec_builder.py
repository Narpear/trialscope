from typing import Any

from app.aggregators.common import AggregateResult
from app.schemas import AnalysisType, Encoding, QueryPlan, Visualization

CHART_ENCODING: dict[AnalysisType, dict[str, Any]] = {
    AnalysisType.TIME_TREND: {
        "x": {"field": "year_date", "type": "temporal", "timeUnit": "year"},
        "y": {"field": "trial_count", "type": "quantitative", "title": "Trials"},
        "sort": {"field": "year_date", "order": "ascending"},
        "time_granularity": "year",
        "units": {"trial_count": "trials"},
        "tooltip": ["year", "trial_count"],
    },
    AnalysisType.DISTRIBUTION: {
        "x": {"field": "category", "type": "nominal"},
        "y": {"field": "trial_count", "type": "quantitative", "title": "Trials"},
        "sort": {"field": "trial_count", "order": "descending"},
        "units": {"trial_count": "trials"},
        "tooltip": ["category", "trial_count"],
    },
    AnalysisType.COMPARISON: {
        "x": {"field": "category", "type": "nominal"},
        "xOffset": {"field": "group", "type": "nominal"},
        "y": {"field": "trial_count", "type": "quantitative", "title": "Trials"},
        "color": {"field": "group", "type": "nominal"},
        "sort": {"field": "category", "order": "ascending"},
        "units": {"trial_count": "trials"},
        "tooltip": ["category", "group", "trial_count"],
    },
    AnalysisType.GEOGRAPHIC: {
        "x": {"field": "country", "type": "nominal"},
        "y": {"field": "trial_count", "type": "quantitative", "title": "Trials"},
        "sort": {"field": "trial_count", "order": "descending"},
        "units": {"trial_count": "trials"},
        "tooltip": ["country", "trial_count"],
    },
    AnalysisType.HISTOGRAM: {
        "x": {"field": "bin_start", "type": "quantitative", "title": "Enrollment"},
        "y": {"field": "trial_count", "type": "quantitative", "title": "Trials"},
        "sort": {"field": "bin_start", "order": "ascending"},
        "units": {"bin_start": "participants", "trial_count": "trials"},
        "tooltip": ["bin_start", "bin_end", "trial_count"],
    },
    AnalysisType.SCATTER: {
        "x": {"field": "start_year", "type": "quantitative", "title": "Start year"},
        "y": {"field": "enrollment", "type": "quantitative", "title": "Enrollment"},
        "units": {"enrollment": "participants", "start_year": "calendar year"},
        "tooltip": ["nct_id", "title", "start_year", "enrollment"],
    },
}


def build_visualization(plan: QueryPlan, result: AggregateResult) -> Visualization:
    if plan.analysis_type == AnalysisType.NETWORK:
        encoding = Encoding(
            nodes={"id": "id", "label": "label", "type": "type", "weight": "weight"},
            edges={"source": "source", "target": "target", "weight": "weight"},
            tooltip=["label", "type", "weight"],
        )
    else:
        definition = CHART_ENCODING[plan.analysis_type]
        encoding = Encoding(
            x=definition.get("x"),
            x_offset=definition.get("xOffset"),
            y=definition.get("y"),
            color=definition.get("color"),
            sort=definition.get("sort"),
            units=definition.get("units", {}),
            time_granularity=definition.get("time_granularity"),
            tooltip=definition.get("tooltip", []),
        )
    return Visualization(
        type=result.visualization_type,
        title=result.title,
        encoding=encoding,
        data=result.data,
        nodes=result.nodes,
        edges=result.edges,
    )
