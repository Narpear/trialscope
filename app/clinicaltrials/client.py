import asyncio
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode

import httpx

from app.aggregators.common import parse_year, value_at
from app.schemas import PlanFilters, QueryPlan
from app.settings import Settings

COMMON_FIELDS = {"NCTId", "BriefTitle"}
DIMENSION_FIELD = {
    "phase": "Phase",
    "status": "OverallStatus",
    "sponsor": "LeadSponsorName",
    "sponsor_class": "LeadSponsorClass",
    "intervention_type": "InterventionType",
    "condition": "Condition",
}
START_DATE_PATH = "protocolSection.statusModule.startDateStruct.date"


class ClinicalTrialsError(Exception):
    pass


class RequestPacer:
    """Token bucket that keeps this process under ClinicalTrials.gov's per-IP rate limit."""

    def __init__(self, rate_per_second: float, burst: int):
        self.rate = rate_per_second
        self.capacity = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


def filter_params(filters: PlanFilters, extra_clause: str | None = None) -> dict[str, Any]:
    """Translate plan filters (plus an optional Essie clause) into v2 search parameters."""
    params: dict[str, Any] = {}
    if filters.condition:
        params["query.cond"] = filters.condition
    if filters.drug_name:
        params["query.intr"] = filters.drug_name
    if filters.sponsor:
        params["query.spons"] = filters.sponsor
    if filters.country:
        params["query.locn"] = filters.country
    if filters.recruitment_status:
        params["filter.overallStatus"] = filters.recruitment_status.value
    # The v2 API has no filter.phase parameter; phase and dates use Essie expressions.
    clauses = []
    if filters.phase:
        clauses.append(f"AREA[Phase]{filters.phase.value}")
    if filters.start_year is not None or filters.end_year is not None:
        start = f"{filters.start_year or 1900}-01-01"
        end = f"{filters.end_year or 2100}-12-31"
        clauses.append(f"AREA[StartDate]RANGE[{start},{end}]")
    if extra_clause:
        clauses.append(extra_clause)
    if clauses:
        params["filter.advanced"] = " AND ".join(clauses)
    return params


class ClinicalTrialsClient:
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        cache_ttl: float = 300,
        cache_size: int = 512,
        pacer: RequestPacer | None = None,
    ):
        self.settings = settings
        self.http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={"Accept": "application/json"},
        )
        self._owns_client = http_client is None
        self.pacer = pacer or RequestPacer(
            settings.clinicaltrials_requests_per_second, settings.clinicaltrials_request_burst
        )
        self.cache_ttl = cache_ttl
        self.cache_size = cache_size
        self._cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return f"{self.settings.clinicaltrials_base_url.rstrip('/')}/studies"

    async def close(self) -> None:
        if self._owns_client:
            await self.http.aclose()

    @staticmethod
    def build_params(plan: QueryPlan, max_trials: int) -> dict[str, Any]:
        fields = set(COMMON_FIELDS)
        if plan.analysis_type.value == "time_trend":
            fields.add("StartDate")
        elif plan.analysis_type.value == "distribution":
            fields.add(DIMENSION_FIELD[plan.group_by or "phase"])
        elif plan.analysis_type.value == "comparison":
            fields.add(DIMENSION_FIELD[plan.group_by or "phase"])
            if plan.comparison_group_type == "condition":
                fields.update({"Condition", "Keyword"})
            else:
                fields.update({"InterventionName", "InterventionOtherName"})
        elif plan.analysis_type.value == "geographic":
            fields.update({"OverallStatus", "LocationCountry"})
        elif plan.analysis_type.value == "network":
            entities = plan.network_entity_types or ["sponsor", "drug"]
            if "sponsor" in entities:
                fields.add("LeadSponsorName")
            if "drug" in entities:
                fields.update({"InterventionName", "InterventionType"})
            if "condition" in entities:
                fields.add("Condition")
        elif plan.analysis_type.value == "histogram":
            fields.add("EnrollmentCount")
        elif plan.analysis_type.value == "scatter":
            fields.update({"StartDate", "EnrollmentCount"})
        return {
            "format": "json",
            "countTotal": "true",
            "pageSize": min(max_trials, 1000),
            "fields": ",".join(sorted(fields)),
            **filter_params(plan.filters),
        }

    def _cache_get(self, key: tuple) -> Any:
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            self._cache.move_to_end(key)
            return cached[1]
        if cached:
            del self._cache[key]
        return None

    def _cache_put(self, key: tuple, value: Any) -> None:
        self._cache[key] = (time.monotonic(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    async def _get_page(self, params: dict[str, Any]) -> dict[str, Any]:
        attempts = 5
        for attempt in range(attempts):
            await self.pacer.wait()
            try:
                response = await self.http.get(self.base_url, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == attempts - 1:
                    raise ClinicalTrialsError(
                        "ClinicalTrials.gov request failed after retries."
                    ) from exc
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == attempts - 1:
                    raise ClinicalTrialsError(
                        f"ClinicalTrials.gov returned HTTP {response.status_code} after retries."
                    )
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                await asyncio.sleep(min(delay, 8))
                continue
            if response.is_error:
                raise ClinicalTrialsError(
                    f"ClinicalTrials.gov returned HTTP {response.status_code}."
                )
            try:
                page = response.json()
            except ValueError as exc:
                raise ClinicalTrialsError("ClinicalTrials.gov returned invalid JSON.") from exc
            if not isinstance(page, dict) or not isinstance(page.get("studies"), list):
                raise ClinicalTrialsError("ClinicalTrials.gov response omitted the studies field.")
            return page
        raise ClinicalTrialsError("ClinicalTrials.gov request failed after retries.")

    async def count(self, filters: PlanFilters, clause: str | None = None) -> tuple[int, str]:
        """Return the exact registry total for ``filters`` AND ``clause``, plus the query URL."""
        params = {
            "format": "json",
            "countTotal": "true",
            "pageSize": 1,
            "fields": "NCTId",
            **filter_params(filters, clause),
        }
        url = f"{self.base_url}?{urlencode(params)}"
        key = ("count", *sorted((k, str(v)) for k, v in params.items()))
        async with self._lock:
            cached = self._cache_get(key)
        if cached is not None:
            return cached, url
        page = await self._get_page(params)
        try:
            total = int(page["totalCount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ClinicalTrialsError("ClinicalTrials.gov returned an invalid totalCount.") from exc
        async with self._lock:
            self._cache_put(key, total)
        return total, url

    async def start_year_bounds(self, filters: PlanFilters) -> tuple[int, int] | None:
        """Earliest and latest start year among matching studies that report a start date."""
        years = []
        for order in ("asc", "desc"):
            page = await self._get_page(
                {
                    "format": "json",
                    "pageSize": 1,
                    "fields": "NCTId,StartDate",
                    "sort": f"StartDate:{order}",
                    **filter_params(filters, "AREA[StartDate]RANGE[MIN,MAX]"),
                }
            )
            if not page["studies"]:
                return None
            year = parse_year(value_at(page["studies"][0], START_DATE_PATH))
            if year is None:
                return None
            years.append(year)
        return years[0], years[1]

    async def fetch(
        self, plan: QueryPlan, max_trials: int
    ) -> tuple[list[dict[str, Any]], int, bool, str]:
        params = self.build_params(plan, max_trials)
        # pageSize is capped at 1,000, so it cannot distinguish larger max_trials values.
        key = (
            "fetch",
            max_trials,
            *sorted((k, str(v)) for k, v in params.items() if k != "pageSize"),
        )
        async with self._lock:
            payload = self._cache_get(key)
        if payload is not None:
            return payload["studies"], payload["total"], payload["truncated"], payload["url"]

        request_url = f"{self.base_url}?{urlencode(params)}"
        studies: list[dict[str, Any]] = []
        page_token: str | None = None
        total: int | None = None
        while len(studies) < max_trials:
            page_params = dict(params)
            page_params["pageSize"] = min(1000, max_trials - len(studies))
            if page_token:
                page_params["pageToken"] = page_token
            page = await self._get_page(page_params)
            # countTotal is only reported on the first page.
            if total is None:
                try:
                    total = int(page["totalCount"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ClinicalTrialsError(
                        "ClinicalTrials.gov returned an invalid totalCount."
                    ) from exc
            studies.extend(page["studies"])
            page_token = page.get("nextPageToken")
            if not page_token or not page["studies"]:
                break

        total = total if total is not None else len(studies)
        truncated = total > len(studies) or bool(page_token)
        payload = {
            "studies": studies[:max_trials],
            "total": total,
            "truncated": truncated,
            "url": request_url,
        }
        async with self._lock:
            self._cache_put(key, payload)
        return payload["studies"], total, truncated, request_url
