from typing import Any

from app.aggregators.common import AggregateResult
from app.aggregators.comparison import comparison
from app.aggregators.distribution import distribution
from app.aggregators.geographic import geographic
from app.aggregators.histogram import histogram
from app.aggregators.network import network
from app.aggregators.scatter import scatter
from app.aggregators.time_trend import time_trend
from app.schemas import AnalysisType, QueryPlan

AGGREGATORS = {
    AnalysisType.TIME_TREND: time_trend,
    AnalysisType.DISTRIBUTION: distribution,
    AnalysisType.COMPARISON: comparison,
    AnalysisType.GEOGRAPHIC: geographic,
    AnalysisType.NETWORK: network,
    AnalysisType.HISTOGRAM: histogram,
    AnalysisType.SCATTER: scatter,
}


def aggregate(
    studies: list[dict[str, Any]],
    plan: QueryPlan,
    top_n: int = 30,
    min_edge_weight: int = 2,
    excluded_interventions: list[str] | None = None,
) -> AggregateResult:
    function = AGGREGATORS[plan.analysis_type]
    if plan.analysis_type == AnalysisType.NETWORK:
        return network(studies, plan, top_n, min_edge_weight, excluded_interventions)
    return function(studies, plan)
