from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AnalysisType(StrEnum):
    TIME_TREND = "time_trend"
    DISTRIBUTION = "distribution"
    COMPARISON = "comparison"
    GEOGRAPHIC = "geographic"
    NETWORK = "network"
    HISTOGRAM = "histogram"
    SCATTER = "scatter"


class Phase(StrEnum):
    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"


class RecruitmentStatus(StrEnum):
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    UNKNOWN = "UNKNOWN"


GroupBy = Literal["phase", "status", "sponsor", "sponsor_class", "intervention_type", "condition"]
CountBasis = Literal["complete_records", "api_count_queries", "sample"]
ComparisonGroupType = Literal["drug", "condition"]


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    drug_name: str | None = Field(default=None, max_length=200)
    condition: str | None = Field(default=None, max_length=200)
    sponsor: str | None = Field(default=None, max_length=200)
    phase: Phase | None = None
    country: str | None = Field(default=None, max_length=100)
    recruitment_status: RecruitmentStatus | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    max_trials: int = Field(default=5000, ge=1, le=10000)
    analysis_type: AnalysisType | None = None
    group_by: GroupBy | None = None
    comparison_groups: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, min_length=2, max_length=4
    )
    comparison_group_type: ComparisonGroupType | None = None

    @model_validator(mode="after")
    def years_are_ordered(self) -> "QueryRequest":
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        return self

    @field_validator("query")
    @classmethod
    def query_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class PlanFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug_name: str | None
    condition: str | None
    sponsor: str | None
    phase: Phase | None
    country: str | None
    recruitment_status: RecruitmentStatus | None
    start_year: int | None = Field(ge=1900, le=2100)
    end_year: int | None = Field(ge=1900, le=2100)

    @model_validator(mode="after")
    def years_are_ordered(self) -> "PlanFilters":
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        return self


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answerable: bool
    unsupported_reason: str | None
    analysis_type: AnalysisType
    filters: PlanFilters
    group_by: GroupBy | None
    comparison_groups: list[str]
    comparison_group_type: ComparisonGroupType | None
    network_entity_types: list[Literal["sponsor", "drug", "condition"]]
    interpretation: str = Field(min_length=1, max_length=300)


class Citation(BaseModel):
    nct_id: str
    field_path: str
    exact_value: Any
    title: str


class Encoding(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    x: dict[str, Any] | None = None
    x_offset: dict[str, Any] | None = Field(default=None, alias="xOffset")
    y: dict[str, Any] | None = None
    color: dict[str, Any] | None = None
    tooltip: list[str] = Field(default_factory=list)
    sort: dict[str, Any] | None = None
    units: dict[str, str] = Field(default_factory=dict)
    time_granularity: str | None = None
    nodes: dict[str, str] | None = None
    edges: dict[str, str] | None = None


class Visualization(BaseModel):
    type: str
    title: str
    encoding: Encoding
    data: list[dict[str, Any]]
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class GroupQuery(BaseModel):
    group: str
    total_matching: int
    trials_analyzed: int
    truncated: bool
    api_query_url: str


class ResponseMeta(BaseModel):
    query_interpretation: str
    plan: QueryPlan
    planner_mode: Literal["llm", "fallback"]
    filters_applied: dict[str, Any]
    total_matching: int
    trials_analyzed: int
    truncated: bool
    assumptions: list[str]
    warnings: list[str]
    api_query_url: str
    source: str = "clinicaltrials.gov"
    generated_at: datetime
    total_citations: int
    counts_exact: bool
    count_basis: CountBasis
    group_queries: list[GroupQuery] | None = None
    network_top_n: int | None = None
    network_min_edge_weight: int | None = None
    network_excluded_interventions: list[str] | None = None


class QueryResponse(BaseModel):
    visualization: Visualization
    meta: ResponseMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
