# TrialScope

ClinicalTrials.gov Query-to-Visualization service: ask a natural-language question about registered studies and receive a renderable visualization specification with record-level citations.

**Live demo:** TODO — add the Railway URL after deployment.

## What it does

TrialScope retrieves studies from the ClinicalTrials.gov v2 Data API and returns chart-ready data for seven query classes: time trends, categorical distributions, comparisons, country counts, entity networks, enrollment histograms, and enrollment-versus-start-year scatter plots.

### Hallucination boundary

The language model is used **only** to interpret a question as a validated `QueryPlan`. It does not retrieve records, calculate counts, create chart data, or write citations. The Python service fetches the source records and deterministically computes every numeric value, visualization datum, and citation from those records. Pydantic validates the plan before it can affect retrieval or aggregation. If no `OPENAI_API_KEY` is configured, a caller must provide `analysis_type` and the service uses an explicitly labeled deterministic fallback instead of guessing the intended chart.

The authoritative source is the [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api).

## Install and run

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
# Add OPENAI_API_KEY to .env to enable natural-language planning.
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/`. For calls without a key, include `analysis_type` in `POST /api/query`; the UI's example chips do this automatically.

### Environment variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `OPENAI_API_KEY` | For LLM planning | unset | OpenAI API key; never put it in source control. |
| `OPENAI_MODEL` | No | `gpt-5.4-mini` | Model used for strict Structured Outputs. Override to another model available to your API project. |
| `CLINICALTRIALS_BASE_URL` | No | `https://clinicaltrials.gov/api/v2` | ClinicalTrials.gov v2 API base URL. |
| `MAX_TRIALS_CAP` | No | `5000` | Server-side hard cap on trials fetched per request (1–5,000). |

The configured OpenAI key was queried through `GET /v1/models` during development. It listed the user-provided allowed models: `gpt-4o-mini`, `gpt-4o-2024-08-06`, `gpt-4.1-nano`, `gpt-4.1-mini`, `gpt-4.1`, `gpt-5-mini`, `gpt-5`, `gpt-5.1`, `gpt-5.2`, `gpt-5.4-nano`, `gpt-5.4-mini`, and `gpt-5.4`. The default is `gpt-5.4-mini`, selected as a cost-efficient current option with Structured Outputs support; `OPENAI_MODEL` keeps that choice configurable.

## API

### `POST /api/query`

Example:

```json
{
  "query": "How many aspirin trials started each year?",
  "drug_name": "aspirin",
  "analysis_type": "time_trend",
  "start_year": 2015,
  "max_trials": 1000
}
```

Request fields (unknown properties are rejected):

| Field | Type | Required | Validation / meaning |
|---|---|---:|---|
| `query` | string | Yes | 1–2,000 characters after trimming; cannot be blank. |
| `drug_name` | string or null | No | Intervention search term, max 200 characters. |
| `condition` | string or null | No | Condition search term, max 200 characters. |
| `sponsor` | string or null | No | Lead-sponsor search term, max 200 characters. |
| `phase` | enum or null | No | `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`. |
| `country` | string or null | No | Location search term, max 100 characters. |
| `recruitment_status` | enum or null | No | `NOT_YET_RECRUITING`, `RECRUITING`, `ENROLLING_BY_INVITATION`, `ACTIVE_NOT_RECRUITING`, `SUSPENDED`, `TERMINATED`, `COMPLETED`, `WITHDRAWN`, `UNKNOWN`. |
| `start_year`, `end_year` | integer or null | No | Inclusive years from 1900 to 2100; start must not exceed end. |
| `max_trials` | integer | No | 1–5,000; defaults to 1,000 and is further capped by `MAX_TRIALS_CAP`. |
| `analysis_type` | enum or null | No | `time_trend`, `distribution`, `comparison`, `geographic`, `network`, `histogram`, `scatter`. Explicit value wins over the planner; required for keyless fallback. |

Explicit structured filter values override planner-extracted filters. When `analysis_type` is supplied, it also overrides the planner's chart choice.

### `GET /api/schema`

Returns JSON Schema documents for the request and successful response. This endpoint is the runtime source of truth for required/nullability details.

### Successful response

```json
{
  "visualization": {
    "type": "time_series",
    "title": "Clinical trials by start year",
    "encoding": {
      "x": {"field": "year_date", "type": "temporal", "timeUnit": "year"},
      "y": {"field": "trial_count", "type": "quantitative", "title": "Trials"},
      "sort": {"field": "year_date", "order": "ascending"},
      "units": {"trial_count": "trials"},
      "time_granularity": "year",
      "tooltip": ["nct_id", "title", "trial_count"]
    },
    "data": [
      {
        "year": 2022,
        "year_date": "2022-01-01",
        "trial_count": 1,
        "nct_ids": ["NCT00000000"],
        "citations": [
          {
            "nct_id": "NCT00000000",
            "field_path": "protocolSection.statusModule.startDateStruct.date",
            "exact_value": "2022-06",
            "title": "Example study"
          }
        ]
      }
    ]
  },
  "meta": {
    "query_interpretation": "Count aspirin trials by calendar year.",
    "plan": {},
    "planner_mode": "llm",
    "filters_applied": {"drug_name": "aspirin"},
    "total_matching": 1,
    "trials_analyzed": 1,
    "truncated": false,
    "assumptions": [],
    "warnings": [],
    "api_query_url": "https://clinicaltrials.gov/api/v2/studies?...",
    "source": "clinicaltrials.gov",
    "generated_at": "2026-01-01T00:00:00Z",
    "total_citations": 1
  }
}
```

The abbreviated `plan` and `api_query_url` above are illustrative; actual responses include the complete validated plan and full URL. Every datum carries `nct_ids` and up to five citation objects. A citation's `field_path` identifies the exact API field and `exact_value` is copied from that response. `total_citations` counts citation objects returned across the visualization (not all references beyond each datum's cap).

Encoding fields use `quantitative`, `temporal`, and `nominal` data types and explicit fields, units, order, and time granularity. `network_graph` responses use `nodes` (`id`, `label`, `type`, `weight`, citations) and `edges` (`source`, `target`, `weight`, citations); the field mapping is in `encoding.nodes` and `encoding.edges`.

### Error response

All service errors use a consistent envelope:

```json
{
  "error": {
    "code": "unsupported_query",
    "message": "This question cannot be answered from ClinicalTrials.gov registry data.",
    "details": null
  }
}
```

Malformed input returns HTTP 422 with `code: "validation_error"`; unsupported questions return 422, provider failures 503, and registry failures 502. When the planner is unavailable due to a provider error, the service reports that failure explicitly rather than quietly using fallback behavior.

### Other endpoints

- `GET /api/health` — deployment health check.
- `GET /` — responsive single-page research UI.

## Architecture and analysis choices

1. **Plan only.** `OpenAIPlanner` uses the OpenAI Responses API with strict JSON Schema generated from the Pydantic `QueryPlan`. The planner is behind a protocol. The response is Pydantic-validated; a validation failure is retried once with validation feedback, then surfaced as a structured error. Explicit user filters override extracted values.
2. **Fetch records.** `ClinicalTrialsClient` requests only the relevant v2 fields, sets `countTotal`, paginates with `pageToken`, limits page sizes, handles timeouts/transient failures/429 with bounded exponential backoff, and caches result pages in a process-local TTL/LRU cache. Date ranges use the API's verified `AREA[StartDate]RANGE[...]` advanced filter. `total_matching` comes from the API; `trials_analyzed` is the count processed after local validation/filters.
3. **Aggregate deterministically.** A dispatch registry selects one independent aggregator by `analysis_type`. No query-text branching produces data. Study IDs and exact source values remain attached through aggregation.
4. **Build a renderable spec.** The spec builder attaches an encoding with explicit channels, field names, types, units, sort and temporal granularity. The no-build frontend renders from those returned types/encodings and supports citation inspection, CSV export of chart rows or graph nodes/edges, and copyable query links that restore query inputs without automatically sending a request.

## Planner evaluation

The real-planner evaluation set is in `evals/planner_cases.json`; it covers all seven analysis types, two comparisons, two network requests, ambiguous prompts, and two questions that the registry cannot answer. Run it with the configured OpenAI key:

```bash
python scripts/eval_planner.py
```

Results from `gpt-5.4-mini` with the current planner prompt:

| Case | Expected plan | Result |
|---|---|---|
| time-trend-drug | time_trend; pembrolizumab; start year 2018 | PASS |
| phase-distribution | distribution by phase; melanoma | PASS |
| comparison-phase-counts | compare pembrolizumab vs nivolumab by phase; melanoma | PASS |
| comparison-drugs | compare pembrolizumab vs nivolumab | PASS |
| geographic-recruiting | recruiting trials; type 2 diabetes | PASS |
| network-sponsor-drug | sponsor-drug network; melanoma | PASS |
| network-combination-drugs | drug co-occurrence network; lung cancer | PASS |
| enrollment-histogram | histogram; breast cancer | PASS |
| enrollment-scatter | scatter enrollment vs start year; melanoma | PASS |
| ambiguous-trial-activity | time_trend; melanoma | PASS |
| ambiguous-trial-characteristics | compare pembrolizumab vs nivolumab | PASS |
| unsupported-best-treatment | structured unanswerable plan | PASS |
| unsupported-survival-benefit | structured unanswerable plan | PASS |
| time-trend-condition | time_trend; rheumatoid arthritis; 2015–2020 | PASS |
| intervention-type-distribution | distribution by intervention type; asthma | PASS |

**15/15 passed.** The first run passed 12/15: two single-population distribution questions were misclassified as comparisons, and one descriptive enrollment/start-year scatter was marked unanswerable. The prompt was adjusted to distinguish grouped distributions from explicit multi-group comparisons and descriptive registry-field plots from clinical effectiveness/causality questions. Unsupported cases are checked for `answerable=false` and a non-empty unsupported reason; their unused analysis-type field is not scored. This is a small, curated evaluation set rather than a broad statistical guarantee; model/provider updates can change results, so rerun it after planner changes.

### Messy-data decisions and limitations

- Start dates use ClinicalTrials.gov `YYYY-MM`/`YYYY-MM-DD` strings and are bucketed by calendar year; records missing a usable date are excluded with a warning. A time-series data point includes an ISO date for unambiguous temporal rendering.
- Phase is an array. A multi-phase study is counted once in every reported phase, not assigned to a fabricated combined phase. Missing phases are grouped as `Not specified`.
- Categorical multi-value records count once per distinct category. Country counts use distinct reported study-location countries; this is **location coverage**, not proof of where all participants live. Missing locations are excluded and warned.
- Intervention matching normalizes case and whitespace. It does not attempt drug identity resolution, so brand and generic names may remain separate.
- Enrollment is the registry's reported enrollment count (target or actual depending on the record); it is not harmonized to a single enrollment status. Histograms use ten equal-width bins across the observed range. Scatter plots exclude missing numeric enrollment or start year.
- Network nodes are stable typed IDs, ranked by trial weight; the default top 30 nodes are retained and edges need at least two co-occurring records. Both thresholds are present in response metadata. Sponsor–drug and condition–drug networks link records containing both entities; a drug-only network captures drug co-occurrence in combination studies.
- The API/cache/rate limiter are in-process. The response cache and simple per-IP query limit reset on restart and do not coordinate across Railway replicas. Use a shared cache and distributed limiter if scaling beyond one instance.
- Citation details include up to five trial references per datum for payload and UI usability; `nct_ids` still identifies all contributing records. Increasing citation payload limits or adding cursor-based citation expansion would be a useful follow-up.
- API search semantics are ClinicalTrials.gov's; a broad query can be truncated at the configured trial cap. Metadata reports the API match total and whether the fetched sample was capped.

## Tests and examples

The repository includes two raw ClinicalTrials.gov records captured before implementation in `tests/fixtures/aspirin_studies.json`; they demonstrate real response structure, date precision, array-valued fields, optional fields, and intervention/location multiplicity.

```bash
pytest -q -m "not live"   # deterministic unit, schema, planner-mock, client, and endpoint tests
pytest -q -m live         # optional live count/date-filter sanity test
ruff check app tests
```

Fixture-backed coverage tests every aggregator, citations, graph thresholds, API pagination/cache, planner validation/retry, keyless fallback, request validation, and API routes. The live test checks that an aspirin query with the 2020–2022 API date range returns records whose actual start dates fall inside that interval. During implementation, the independent API count for `query.intr=aspirin` was checked directly: `totalCount` returned **2,204**. A separate live `AREA[StartDate]RANGE[2020-01-01,2022-12-31]` probe returned **348** aspirin matches; the live integration test checks the same date-filter behavior.

Five actual service responses are stored under `examples/` (time trend, comparison, geography, network, and distribution). To regenerate them, start the service with `uvicorn app.main:app` and run:

```bash
python scripts/generate_examples.py
```

Set `EXAMPLES_BASE_URL` if the server is not at `http://127.0.0.1:8000`. Generation uses the server's configured planner and live ClinicalTrials.gov data.

## Deploying to Railway

1. Push this repository to a Git provider and create a Railway project from that repository.
2. Railway reads `railway.json`; it starts `uvicorn app.main:app --host 0.0.0.0 --port $PORT` and checks `/api/health`.
3. In the Railway service's **Variables** panel, set `OPENAI_API_KEY` and, optionally, `OPENAI_MODEL` and `MAX_TRIALS_CAP`. Do not commit `.env` or paste secrets into source files.
4. Deploy and wait for the `/api/health` check to pass. Use the generated Railway domain as the live demo URL and update the TODO at the top of this README.
5. To run without an OpenAI key, callers must specify `analysis_type`; this mode is useful for service smoke tests, not natural-language chart selection.

## AI tool usage

> TODO — write this section in your own words. Describe the AI tools you used, which parts they helped with, and what you deliberately designed, verified, or adapted yourself.
