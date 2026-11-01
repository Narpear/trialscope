# TrialScope

ClinicalTrials.gov Query-to-Visualization service: ask a natural-language question about registered studies and receive a renderable visualization specification with record-level citations.

**Live demo:** https://trialscope.onrender.com/ (free Render instance: after 15 idle minutes the first request takes about a minute while it wakes).

## What it does

TrialScope retrieves studies from the ClinicalTrials.gov v2 Data API and returns chart-ready data for seven query classes: time trends, categorical distributions, comparisons, country counts, entity networks, enrollment histograms, and enrollment-versus-start-year scatter plots.

### Hallucination boundary

The language model is used **only** to interpret a question as a `QueryPlan`. It does not retrieve records, calculate counts, create chart data, or write citations. The Python service fetches the source records (and, where needed, exact registry totals) and deterministically computes every numeric value, visualization datum, and citation. The plan passes two checks before it can affect retrieval: Pydantic validates its shape, then `app/planner/validation.py` checks that its fields fit the chosen analysis (for example, a comparison needs two or more distinct groups). Unused fields are dropped, defaults are filled, and every such change is reported in `meta.plan_adjustments`. Plans that cannot run are rejected with `invalid_plan`. The only model-written text in a response is `meta.query_interpretation` (and `unsupported_reason` on refusals). If no `OPENAI_API_KEY` is configured, a caller must provide `analysis_type` (and, for comparisons, `comparison_groups`), and the service uses an explicitly labeled deterministic fallback instead of guessing the intended chart.

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
| `MAX_TRIALS_CAP` | No | `10000` | Server-side hard cap on trials fetched per query (1–10,000). |
| `EXACT_COUNT_QUERY_BUDGET` | No | `40` | Maximum ClinicalTrials.gov count queries per request when computing exact totals for a truncated sample (see [Count accuracy](#count-accuracy)). |
| `TRUSTED_PROXY_HOPS` | No | `2` on Render, else `0` | Reverse proxies in front of the app. The rate limiter reads the client IP from the `X-Forwarded-For` entry appended by the outermost trusted proxy; `0` uses the socket peer. |
| `NETWORK_EXCLUDED_INTERVENTIONS` | No | `["placebo","standard of care","saline","best supportive care"]` | JSON array of intervention names excluded from network nodes and edges; matched with the same name normalization as drug nodes. |

## API

### `POST /api/query`

Example:

```json
{
  "query": "How many aspirin trials started each year?",
  "drug_name": "aspirin",
  "analysis_type": "time_trend",
  "start_year": 2015
}
```

Request fields (unknown properties are rejected):

| Field | Type | Required | Validation / meaning |
|---|---|---:|---|
| `query` | string | Yes | 1–2,000 characters after trimming; cannot be blank. |
| `drug_name` | string or null | No | Intervention search term, max 200 characters. |
| `condition` | string or null | No | Condition search term, max 200 characters. |
| `sponsor` | string or null | No | Lead-sponsor search term, max 200 characters. |
| `phase` | enum or null | No | `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`. Sent as the Essie expression `AREA[Phase]<value>` (the v2 API has no `filter.phase` parameter). |
| `country` | string or null | No | Location search term, max 100 characters. |
| `recruitment_status` | enum or null | No | `NOT_YET_RECRUITING`, `RECRUITING`, `ENROLLING_BY_INVITATION`, `ACTIVE_NOT_RECRUITING`, `SUSPENDED`, `TERMINATED`, `COMPLETED`, `WITHDRAWN`, `UNKNOWN`. |
| `start_year`, `end_year` | integer or null | No | Inclusive years from 1900 to 2100; start must not exceed end. |
| `max_trials` | integer | No | Records fetched per ClinicalTrials.gov query (per group for comparisons): 1–10,000, default 5,000, further capped by `MAX_TRIALS_CAP`. Fetched records supply citations; see [Count accuracy](#count-accuracy) for how counts stay exact when a query has more matches. |
| `analysis_type` | enum or null | No | `time_trend`, `distribution`, `comparison`, `geographic`, `network`, `histogram`, `scatter`. Explicit value wins over the planner; required for keyless fallback. |
| `group_by` | enum or null | No | Category field for `distribution` and `comparison`: `phase`, `status` (overall recruitment status), `intervention_type`, `sponsor` (lead sponsor name), `sponsor_class` (industry, NIH, other government, …), `condition`. Defaults to `phase`. |
| `comparison_groups` | array of 2–4 strings or null | No | The drugs or conditions to compare, each 1–200 characters. Required for a keyless comparison. |
| `comparison_group_type` | `drug`, `condition`, or null | No | How each comparison group is searched: `drug` uses `query.intr`, `condition` uses `query.cond`. Defaults to `drug`. |

Explicit request values override the planner's: structured filters, `analysis_type`, `group_by`, `comparison_groups`, and `comparison_group_type`. Semantic plan validation runs after this merge.

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
      "tooltip": ["year", "trial_count"]
    },
    "data": [
      {
        "year": 2022,
        "year_date": "2022-01-01",
        "trial_count": 151,
        "sample_trial_count": 1,
        "count_query_url": "https://clinicaltrials.gov/api/v2/studies?...&filter.advanced=AREA%5BStartDate%5DRANGE%5B2022-01-01%2C2022-12-31%5D",
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
    "filters_applied": {"drug_name": "aspirin", "start_year": 2015},
    "total_matching": 1203,
    "trials_analyzed": 1000,
    "truncated": true,
    "counts_exact": true,
    "count_basis": "api_count_queries",
    "plan_adjustments": [],
    "assumptions": [],
    "warnings": [],
    "api_query_url": "https://clinicaltrials.gov/api/v2/studies?...",
    "source": "clinicaltrials.gov",
    "generated_at": "2026-01-01T00:00:00Z",
    "total_citations": 1,
    "group_queries": null
  }
}
```

The abbreviated values above are illustrative; real responses include the complete validated plan and full URLs (see `examples/`).

**Datum fields.** Every datum carries `trial_count`, `nct_ids` (the contributing trials among the fetched records) and up to five `citations`. A citation's `field_path` names the API field and `exact_value` is copied verbatim from that trial's record. When counts come from count queries (below), a datum also has `sample_trial_count` (how many fetched records fall in the bucket, which is what `nct_ids` and `citations` cover) and `count_query_url` (the ClinicalTrials.gov query whose `totalCount` is `trial_count`). Categorical rows have a display `category` and the registry's `category_code` (for example `Not Applicable` / `NA`). Comparison rows add `group`.

**Meta fields.** `total_matching` is the API's match total, `trials_analyzed` is the number of records fetched (the sample size), and `truncated` says whether that is fewer than the total. For comparisons, both are sums over groups (a trial matching two groups counts in each), and `group_queries` lists each group's total, fetched count, truncation and query URL. `counts_exact` and `count_basis` say whether the visualized numbers are registry totals. `plan_adjustments` lists changes made by semantic plan validation. `total_citations` counts citation objects returned across the visualization (not references beyond each datum's cap). Network responses also report `network_top_n`, `network_min_edge_weight`, and the normalized `network_excluded_interventions` list.

### Visualization types

`visualization.type` decides where the marks are and which fields each mark has. Every row or element also carries `trial_count` (or `weight`), `nct_ids` and `citations`, as described above.

| `type` | Analysis | Marks are in | Mark fields | Encoding |
|---|---|---|---|---|
| `time_series` | `time_trend` | `data`, one row per year | `year` (integer), `year_date` (`YYYY-01-01`) | x = `year_date` (temporal, year unit), y = `trial_count`; sorted by year |
| `bar_chart` | `distribution` | `data`, one row per category | `category` (label), `category_code` (registry code) | x = `category`, y = `trial_count`; sorted by count, descending |
| `grouped_bar_chart` | `comparison` | `data`, one row per group × category | `group`, `category`, `category_code` | x = `category`, xOffset and color = `group`, y = `trial_count` |
| `bar_chart` | `geographic` | `data`, one row per country | `country` | x = `country`, y = `trial_count`; sorted by count, descending |
| `histogram` | `histogram` | `data`, one row per non-empty bin | `bin_start`, `bin_end` (participants) | x = `bin_start` (quantitative), y = `trial_count` |
| `scatter_plot` | `scatter` | `data`, one row per trial | `nct_id`, `title`, `start_year`, `enrollment`; `trial_count` is always 1 | x = `start_year`, y = `enrollment` |
| `network_graph` | `network` | `nodes` and `edges`; `data` is empty | nodes: `id` (`<type>:<name>`), `label`, `type` (`sponsor`, `drug` or `condition`), `weight`; edges: `source`, `target` (node ids), `weight` | `encoding.nodes` / `encoding.edges` map these fields; weights are distinct trial counts |

`encoding` uses Vega-Lite-style channel objects (`field`, `type`, optional `title` and `timeUnit`) plus `sort`, `units`, `tooltip` and `time_granularity`, so it can be passed to Vega-Lite almost directly. The bundled frontend does exactly that for every type except networks, which it draws with d3.

### Count accuracy

A ClinicalTrials.gov query can match more trials than are practical to fetch, so `meta.count_basis` states where the numbers come from:

| `count_basis` | When | Numbers are |
|---|---|---|
| `complete_records` | Every matching trial was fetched (`truncated: false`). | Exact. |
| `api_count_queries` | The sample was truncated, but the analysis buckets can be counted: time-trend years, or `phase`/`status`/`intervention_type`/`sponsor_class` for distributions and comparisons. | Exact: one `countTotal` query per bucket (`count_query_url` on each datum). Citations come from the fetched sample. |
| `sample` | The sample was truncated and exact totals are not available (networks, geography, histograms, scatter plots, sponsor- or condition-name groupings) or would exceed `EXACT_COUNT_QUERY_BUDGET`. | Counts within the first `trials_analyzed` records in the API's default order. The first warning says so, gives the sample size, and suggests raising `max_trials` or narrowing filters. |

`counts_exact` is `true` for the first two. ClinicalTrials.gov allows roughly 50 requests per minute per IP after a short burst, so a process-wide pacer spaces registry requests and the count budget bounds the latency of a single response. For example, an unfiltered time trend for lung cancer (59 years) falls back to a sample, while "since 2015" is counted exactly.

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

| HTTP | `code` | Meaning |
|---:|---|---|
| 422 | `validation_error` | The request body failed schema validation. |
| 422 | `unsupported_query` | The planner judged the question unanswerable from registry fields; `details.plan` holds the plan and `message` the reason. |
| 422 | `invalid_plan` | The plan cannot be executed (for example, a comparison with fewer than two groups). |
| 422 | `planner_key_required` | No `OPENAI_API_KEY` and no `analysis_type` in the request. |
| 429 | `rate_limited` | More than 12 queries per minute from one client. |
| 502 | `planner_invalid_plan` | The planner returned a schema-invalid plan twice. |
| 502 | `planner_empty_response` | The planner returned no output. |
| 502 | `clinicaltrials_unavailable` | ClinicalTrials.gov failed or kept rate-limiting after retries. |
| 503 | `planner_unavailable` | The OpenAI request failed. |
| 500 | `internal_error` | Unexpected server error (logged). |

When the planner is unavailable, the service reports that failure explicitly rather than quietly using fallback behavior.

### Other endpoints

- `GET /api/health` — deployment health check.
- `GET /` — responsive single-page research UI.

## Architecture and analysis choices

1. **Plan only.** `OpenAIPlanner` uses the OpenAI Responses API with strict JSON Schema generated from the Pydantic `QueryPlan`, guided by a system prompt of general rules (what is answerable, what each analysis type and field means). A schema-invalid response is retried once with validation feedback, then surfaced as a structured error. Explicit request values override the plan, then `validate_plan` applies the semantic rules described above.
2. **Fetch records.** Each plan becomes one ClinicalTrials.gov query, or one per group for a comparison (drug groups via `query.intr`, condition groups via `query.cond`, each combined with the shared filters). `ClinicalTrialsClient` requests only the fields the analysis needs, paginates with `pageToken`, paces requests under the registry's rate limit, retries timeouts, 5xx and 429 with backoff, and caches fetched results and counts in a process-local TTL/LRU cache. Phase and date filters use Essie `filter.advanced` expressions (`AREA[Phase]…`, `AREA[StartDate]RANGE[…]`), AND-combined.
3. **Count exactly where possible.** `app/exact_counts.py` adds per-bucket `countTotal` queries for truncated samples whose buckets are countable (see [Count accuracy](#count-accuracy)).
4. **Aggregate deterministically.** `app/aggregators/registry.py` dispatches every analysis through one `(scopes, plan, options)` signature: one scope per query (several for a comparison). Each analysis type has its own module; shared citation, category and name-normalization helpers live in `common.py`, and the countable registry codes and their labels live in `dimensions.py`. No query-text branching produces data. Study IDs and exact source values remain attached through aggregation.
5. **Build a renderable spec.** The spec builder attaches an encoding with explicit channels, field names, types, units, sort and temporal granularity. The no-build frontend renders from those returned types/encodings and supports citation inspection, CSV export of chart rows or graph nodes/edges, and copyable query links that restore query inputs without automatically sending a request.

## Design trade-offs

- **The LLM plans; code answers.** The model can only choose among seven analysis types and fill typed filters, so it cannot invent numbers or citations. The cost is flexibility: questions outside those shapes (outcome statistics, eligibility criteria, investigator networks) are refused or answered with the nearest supported chart rather than improvised.
- **Exact counts within a request budget.** Per-bucket `countTotal` queries give registry-exact totals without fetching every record. But ClinicalTrials.gov allows only about 50 requests per minute, so they are bounded by `EXACT_COUNT_QUERY_BUDGET` and add latency (about 15 seconds for 14 years). Analyses without fixed buckets (networks, geography, histograms, scatter) are exact only when every matching trial is fetched; otherwise they are labeled as samples.
- **Registry search defines groups.** Drug and condition groups are ClinicalTrials.gov searches (`query.intr`, `query.cond`), so totals match what a user sees on clinicaltrials.gov, including its synonym expansion. That is broader and less transparent than exact name matching, and the response warns about trials whose cited fields do not contain the term.
- **Faithful multi-value counting.** Multi-phase trials count once in each reported phase, and multi-country trials once per country, instead of creating combined buckets. Every bar can be traced to its records, but bars can sum to more than the trial total.
- **Bounded citations.** Each datum cites up to five records in detail and lists every contributing NCT ID. This keeps responses usable (the largest example is about 0.5 MB) while every count remains traceable.
- **In-process state.** The cache, request pacer and rate limiter live in one process. That is simple and fine for one free instance, but they reset when it sleeps and do not scale across instances.

## Planner evaluation

Two real-planner evaluation sets score the plan after semantic validation, so a plan the service would reject counts as a failure:

- `evals/planner_cases.json` (development set, 15 cases): all seven analysis types, two comparisons, two networks, two ambiguous prompts, and two unanswerable questions.
- `evals/planner_holdout.json` (held-out set, 12 cases): new questions covering status and sponsor-class distributions, a condition-vs-condition comparison, a condition–drug network, a phase-filtered histogram, a sponsor-name distribution, and two more unanswerable questions (efficacy, adverse events). It was written after the current prompt and has never been used to change it.

```bash
python scripts/eval_planner.py            # development set
python scripts/eval_planner.py --holdout  # held-out set
```

Results with `gpt-5.4-mini` and the current prompt: **development 15/15, held-out 12/12**, on each of two runs.

How these numbers came about:
- An earlier prompt reached 15/15 on the development set only after adding hints that quoted phrases from the development questions (for example, "a request to plot numeric enrollment against study start year is a scatter query"). That was tuned to the test set.
- The prompt was then rewritten as general rules with no eval phrasing. The held-out set was written after that rewrite and before either set was run with the new prompt. Both sets passed on the first run, and the prompt has not been changed since.

Caveats:
- 27 cases is a small, curated sample, not a statistical guarantee.
- The same author wrote the prompt and both sets, so the held-out questions are not independent of the prompt's vocabulary.
- The model is non-deterministic and provider updates can change results. Rerun both sets after planner changes.

## Messy-data decisions and limitations

- **Dates.** Start dates are `YYYY`, `YYYY-MM` or `YYYY-MM-DD` strings and are bucketed by calendar year. Every year in the range is listed, with `trial_count` 0 for empty years. Records without a usable date are excluded with a warning. Registries record *anticipated* start dates, so future years are noted as planned starts, and the current year is noted as incomplete.
- **Phases.** Phase is an array. A multi-phase study (Phase 1/Phase 2) is counted once in every reported phase rather than in a fabricated combined phase, so bars can sum to more than the trial total. Missing phases are `Not specified`, and the registry's `NA` is `Not Applicable`.
- **Categories.** Multi-value records count once per distinct category. Country counts use distinct reported study-location countries, which is **location coverage**, not proof of where all participants live. Missing locations are excluded with a warning.
- **Drug names.** Drug nodes use `DRUG` and `BIOLOGICAL` interventions; comparison-membership citations look at interventions of any type. Names are matched after removing case, extra whitespace, trademark symbols (®, ™, ©) and parenthetical or bracketed text, so `Pembrolizumab (Keytruda®)` matches `pembrolizumab`. **Not handled:** brand-only names (`Keytruda`), code names (`MK-3475`), doses and formulation words (`pembrolizumab 200 mg`, `pembrolizumab injection`), spelling and punctuation variants (`nab-paclitaxel` vs `nab paclitaxel`), and combination labels written as one intervention (`nivolumab + ipilimumab`). These stay separate nodes. Removing parentheses can also merge names that differ only in a parenthetical.
- **Comparisons.** Comparison groups use ClinicalTrials.gov's own search (`query.intr` / `query.cond`), which includes the registry's synonym matching. A trial is in a group exactly when the registry search returns it. When a matched record has no intervention or condition field containing the group term, a warning counts those trials; they are still counted and cited by their category value.
- **Enrollment.** Enrollment is the registry's reported count (target or actual depending on the record), not harmonized to one enrollment type. Histograms use ten equal-width bins over the observed range. Scatter plots exclude records missing numeric enrollment or start year.
- **Networks.** Nodes have stable typed IDs and are ranked by trial weight. The top 30 nodes are kept, and edges need at least two co-occurring trials; both thresholds are in response metadata. Sponsor–drug and condition–drug networks link records containing both entities, and a drug-only network captures drugs tested together in the same trials. `NETWORK_EXCLUDED_INTERVENTIONS` removes generic labels (placebo, standard of care, …) from drug nodes and edges. This is a label-based heuristic: it can remove a legitimate intervention with an excluded name and does not identify synonyms. Network weights are exact only when every matching trial is fetched (`count_basis: complete_records`).
- **Sampling.** See [Count accuracy](#count-accuracy). Truncated samples are the first records in the API's default order, which is not a random sample.
- **Single process.** The response cache, request pacer and per-client rate limiter (12 queries/minute) are in-process. They reset on restart and do not coordinate across instances; scaling beyond one instance needs a shared cache and limiter.
- **Citation cap.** Citation details include up to five references per datum for payload and UI usability. `nct_ids` lists every contributing fetched record, and the citation drawer lists every contributing NCT ID below the detailed records when the list exceeds the cap.

## What I would improve with more time

- **Entity resolution.** Map interventions to RxNorm and conditions to MeSH terms (the registry already includes `conditionBrowseModule` and `interventionBrowseModule` MeSH data) so brand names, code names (MK-3475) and spelling variants merge.
- **Exact counts everywhere.** Keep a local mirror of the registry from ClinicalTrials.gov's bulk download, refreshed nightly, so networks, geography and histograms are always exact and responses do not depend on the API rate limit. Short of that, run long count jobs asynchronously with progress polling.
- **More analyses.** Collaborator and investigator/site networks, sponsor-class breakdowns within time trends (stacked series), log-scaled enrollment bins, and phases in natural order.
- **Planner.** A larger, independently written evaluation set run several times per model, clarifying questions for ambiguous requests, and multi-turn refinement ("now only phase 3").
- **Operations.** Redis for the cache and rate limiter, structured request logging, and frontend tests.

## Example runs

Five real responses from the service are stored in `examples/`, produced by `scripts/generate_examples.py` from natural-language questions with default limits. Each is the full JSON response, including the plan, metadata and citations.

| File | Question | Visualization | Matching trials | Counts |
|---|---|---|---:|---|
| [`examples/time_trend.json`](examples/time_trend.json) | How many rheumatoid arthritis trials started each year since 2015? | `time_series`, 14 years | 1,972 | exact (`complete_records`) |
| [`examples/comparison.json`](examples/comparison.json) | Compare phases for trials involving pembrolizumab vs nivolumab. | `grouped_bar_chart`, 2 groups × 7 phases | 2,997 + 2,040 | exact (`complete_records`) |
| [`examples/geographic.json`](examples/geographic.json) | Which countries have the most recruiting trials for melanoma? | `bar_chart`, 53 countries | 485 | exact (`complete_records`) |
| [`examples/network.json`](examples/network.json) | Which drugs frequently co-occur in combination studies for pancreatic cancer? (`max_trials: 10000`) | `network_graph`, 30 nodes, 212 edges | 5,120 | exact (`complete_records`) |
| [`examples/distribution.json`](examples/distribution.json) | How are breast cancer trials distributed across phases? | `bar_chart`, 7 phases | 16,973 | exact (`api_count_queries`, 5,000 records fetched for citations) |

The time trend, comparison and network numbers are among those checked independently against the API (see [Independent verification](#independent-verification-against-clinicaltrialsgov)).

## Tests and examples

The repository includes raw ClinicalTrials.gov fixtures in `tests/fixtures/`: two aspirin records (for date precision, array-valued fields, optional fields, and multiplicity) and 100 records for `query.cond=lung cancer&query.intr=pembrolizumab`. The combination fixture backs a network test that independently reconstructs drug pairs from each raw record and verifies every emitted edge weight and supporting NCT ID.

```bash
pytest -q -m "not live"   # deterministic unit, schema, planner-mock, client, and endpoint tests
pytest -q -m live         # live date-range and phase-filter checks against ClinicalTrials.gov
ruff check app tests scripts
```

Fixture-backed tests cover every aggregator, citations, graph thresholds, intervention-name normalization, pagination and caching (including `totalCount` arriving only on the first page), the three count bases, semantic plan validation, per-group comparison queries, planner validation/retry, keyless fallback, request validation, proxy-aware client IPs, error-status mapping and API routes. The live tests check that a 2020–2022 aspirin date range returns only records starting in that interval, and that the phase filter is accepted and returns only trials with that phase.

### Independent verification against ClinicalTrials.gov

The following were checked by a separate script that queries the API directly and recounts raw records with its own code, not the service's:

| Query | Check | Result |
|---|---|---|
| "How many trials started each year for rheumatoid arthritis since 2015?" | Each year's `trial_count` against a per-year `countTotal` query and against a recount of all 1,972 raw records; run both with the default cap (`complete_records`) and with `max_trials: 1000` (`api_count_queries`) | 14/14 years equal on all four (e.g. 2015: 159, 2021: 182, 2027: 4) |
| "Compare phases for trials involving pembrolizumab vs nivolumab." | Each group × phase count against `query.intr=<drug>&filter.advanced=AREA[Phase]<code>` and against a recount of all 2,997 / 2,040 raw records | 14/14 equal (e.g. pembrolizumab Phase 3: 370; nivolumab Phase 2: 1,169) |
| "Which drugs frequently co-occur in combination studies for pancreatic cancer?" | Top 8 edge weights and NCT ID sets against a recount of all 5,120 raw records using the documented name rule; every edge NCT ID re-checked to contain both drugs | 8/8 equal with `max_trials: 10000` (e.g. gemcitabine — nab-paclitaxel: 164); with the default 5,000 the response is marked `sample` and weights are slightly lower (159) |
| All of the above | Cited `field_path` / `exact_value` re-read from each trial's full API record | 16 citations, 0 mismatches; every time-bucket citation's date is in its year |

To regenerate the [example runs](#example-runs), start the service with `uvicorn app.main:app` and run:

```bash
python scripts/generate_examples.py
```

Set `EXAMPLES_BASE_URL` if the server is not at `http://127.0.0.1:8000`. The examples are natural-language queries, so generation needs `OPENAI_API_KEY` on the server; it uses live ClinicalTrials.gov data.

## Deploying to Render

1. Push this repository to GitHub. In Render, choose **New → Web Service**, connect the repository, and pick the **Free** instance type.
2. Set **Runtime** to Python, **Build Command** to `pip install .`, and **Start Command** to `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Render supplies `PORT`. `.python-version` selects Python 3.12 (a `PYTHON_VERSION` environment variable would override it).
3. Under **Advanced**, set **Health Check Path** to `/api/health`.
4. Under **Environment**, add `OPENAI_API_KEY` and, optionally, `OPENAI_MODEL`, `MAX_TRIALS_CAP`, `EXACT_COUNT_QUERY_BUDGET`, and `NETWORK_EXCLUDED_INTERVENTIONS`. Do not commit `.env` or paste secrets into source files.
5. Deploy. The service is then served at `https://<service>.onrender.com` (this deployment: https://trialscope.onrender.com/).
6. To run without an OpenAI key, callers must specify `analysis_type` (and `comparison_groups` for comparisons); this mode is useful for service smoke tests, not natural-language chart selection.

**Free-tier cold starts.** Render spins a free web service down after 15 minutes without traffic. The next request wakes it, which takes about a minute, and Render shows a loading page meanwhile. After that, responses take their normal time. The in-memory cache and rate-limit counters start empty after each wake.

**Client IPs behind Render.** Requests reach the app through Cloudflare and then Render's proxy. Both append to `X-Forwarded-For` without removing what the client sent, so the header arrives as `<client-supplied entries>, <client IP>, <Cloudflare edge IP>`. The rate limiter therefore reads the second entry from the right: `TRUSTED_PROXY_HOPS` defaults to `2` when Render's `RENDER=true` variable is present. Reading the leftmost entry would let a client choose its own IP, and reading the last would put every visitor behind the same Cloudflare edge into one shared bucket. Render does not document this chain officially (it is based on a [Render staff note](https://feedback.render.com/features/p/send-the-correct-xforwardedfor) and an [observed header trace](https://rohitpaulk.com/articles/render-rails-remote-ip)), so set `TRUSTED_PROXY_HOPS` explicitly if you put another proxy in front or Render changes its edge.

## AI tool usage

> TODO — write this section in your own words. Describe the AI tools you used, which parts they helped with, and what you deliberately designed, verified, or adapted yourself.
