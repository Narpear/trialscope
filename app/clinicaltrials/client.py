import asyncio
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode

import httpx

from app.schemas import QueryPlan
from app.settings import Settings

COMMON_FIELDS = {"NCTId", "BriefTitle"}
DIMENSION_FIELD = {
    "phase": "Phase",
    "sponsor": "LeadSponsorName",
    "intervention_type": "InterventionType",
    "condition": "Condition",
}


class ClinicalTrialsError(Exception):
    pass


class ClinicalTrialsClient:
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        cache_ttl: float = 300,
        cache_size: int = 128,
    ):
        self.settings = settings
        self.http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={"Accept": "application/json"},
        )
        self._owns_client = http_client is None
        self.cache_ttl = cache_ttl
        self.cache_size = cache_size
        self._cache: OrderedDict[tuple, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = asyncio.Lock()

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
            fields.update(
                {"InterventionName", "InterventionType", DIMENSION_FIELD[plan.group_by or "phase"]}
            )
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
        params: dict[str, Any] = {
            "format": "json",
            "countTotal": "true",
            "pageSize": min(max_trials, 1000),
            "fields": ",".join(sorted(fields)),
        }
        filters = plan.filters
        if filters.condition:
            params["query.cond"] = filters.condition
        if filters.drug_name:
            params["query.intr"] = filters.drug_name
        if filters.sponsor:
            params["query.spons"] = filters.sponsor
        if filters.country:
            params["query.locn"] = filters.country
        if filters.phase:
            params["filter.phase"] = filters.phase.value
        if filters.recruitment_status:
            params["filter.overallStatus"] = filters.recruitment_status.value
        if filters.start_year is not None or filters.end_year is not None:
            start = f"{filters.start_year or 1900}-01-01"
            end = f"{filters.end_year or 2100}-12-31"
            params["filter.advanced"] = f"AREA[StartDate]RANGE[{start},{end}]"
        return params

    async def fetch(
        self, plan: QueryPlan, max_trials: int
    ) -> tuple[list[dict[str, Any]], int, bool, str]:
        params = self.build_params(plan, max_trials)
        key = tuple(sorted((k, str(v)) for k, v in params.items()))
        async with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self.cache_ttl:
                self._cache.move_to_end(key)
                payload = cached[1]
                return (
                    payload["studies"][:max_trials],
                    payload["total"],
                    payload["total"] > max_trials,
                    payload["url"],
                )
            if cached:
                del self._cache[key]

        base = f"{self.settings.clinicaltrials_base_url.rstrip('/')}/studies"
        request_url = f"{base}?{urlencode(params)}"
        studies: list[dict[str, Any]] = []
        page_token: str | None = None
        total = 0
        while len(studies) < max_trials:
            page_params = dict(params)
            page_params["pageSize"] = min(1000, max_trials - len(studies))
            if page_token:
                page_params["pageToken"] = page_token
            for attempt in range(4):
                try:
                    response = await self.http.get(base, params=page_params)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 3:
                            response.raise_for_status()
                        retry_after = response.headers.get("Retry-After")
                        delay = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else 0.25 * 2**attempt
                        )
                        await asyncio.sleep(min(delay, 4))
                        continue
                    response.raise_for_status()
                    try:
                        page = response.json()
                    except ValueError as exc:
                        raise ClinicalTrialsError(
                            "ClinicalTrials.gov returned invalid JSON."
                        ) from exc
                    break
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == 3:
                        raise ClinicalTrialsError(
                            "ClinicalTrials.gov request failed after retries."
                        ) from exc
                    await asyncio.sleep(0.25 * 2**attempt)
                except httpx.HTTPStatusError as exc:
                    raise ClinicalTrialsError(
                        f"ClinicalTrials.gov returned HTTP {exc.response.status_code}."
                    ) from exc
            else:
                raise ClinicalTrialsError("ClinicalTrials.gov request failed after retries.")
            if not isinstance(page, dict) or not isinstance(page.get("studies"), list):
                raise ClinicalTrialsError("ClinicalTrials.gov response omitted the studies field.")
            try:
                total = int(page.get("totalCount", len(studies)))
            except (TypeError, ValueError) as exc:
                raise ClinicalTrialsError(
                    "ClinicalTrials.gov returned an invalid totalCount."
                ) from exc
            studies.extend(page["studies"])
            page_token = page.get("nextPageToken")
            if not page_token or not page["studies"]:
                break

        truncated = total > len(studies) or bool(page_token)
        payload = {"studies": studies[:max_trials], "total": total, "url": request_url}
        async with self._lock:
            self._cache[key] = (time.monotonic(), payload)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return payload["studies"], total, truncated, request_url
