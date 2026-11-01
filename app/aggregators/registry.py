from typing import Any

from app.aggregators.core import AGGREGATORS, AggregateResult, network
from app.schemas import AnalysisType, QueryPlan


def aggregate(
    studies: list[dict[str, Any]], plan: QueryPlan, top_n: int = 30, min_edge_weight: int = 2
) -> AggregateResult:
    function = AGGREGATORS[plan.analysis_type]
    if plan.analysis_type == AnalysisType.NETWORK:
        return network(studies, plan, top_n, min_edge_weight)
    return function(studies, plan)
