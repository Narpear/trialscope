from app.aggregators.common import AggregateResult, AggregationOptions, Scope
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
    scopes: list[Scope], plan: QueryPlan, options: AggregationOptions | None = None
) -> AggregateResult:
    """Dispatch to the plan's aggregator. Comparisons receive one scope per group."""
    return AGGREGATORS[plan.analysis_type](scopes, plan, options or AggregationOptions())
