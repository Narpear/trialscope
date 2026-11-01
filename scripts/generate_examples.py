import json
import os
from pathlib import Path

import httpx

BASE_URL = os.getenv("EXAMPLES_BASE_URL", "http://127.0.0.1:8000")
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLES = {
    "time_trend": {
        "query": "How have clinical trials for aspirin changed by start year?",
        "analysis_type": "time_trend",
        "drug_name": "aspirin",
        "max_trials": 150,
    },
    "comparison": {
        "query": "Compare trial phases for pembrolizumab versus nivolumab in melanoma studies.",
        "analysis_type": "comparison",
        "condition": "melanoma",
        "max_trials": 500,
    },
    "geographic": {
        "query": "Which countries have the most recruiting melanoma trials?",
        "analysis_type": "geographic",
        "condition": "melanoma",
        "recruitment_status": "RECRUITING",
        "max_trials": 500,
    },
    "network": {
        "query": "Show sponsor and drug relationships in melanoma trials.",
        "analysis_type": "network",
        "condition": "melanoma",
        "max_trials": 500,
    },
    "distribution": {
        "query": "How are melanoma trials distributed across phases?",
        "analysis_type": "distribution",
        "condition": "melanoma",
        "max_trials": 500,
    },
}


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with httpx.Client(timeout=180) as client:
        for name, request in EXAMPLES.items():
            response = client.post(f"{BASE_URL.rstrip('/')}/api/query", json=request)
            if response.is_error:
                raise RuntimeError(
                    f"{name} example failed ({response.status_code}): {response.text}"
                )
            output = response.json()
            if "visualization" not in output or "meta" not in output:
                raise RuntimeError(f"{name} response did not match the query response schema.")
            path = OUTPUT_DIR / f"{name}.json"
            path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
            print(
                f"Wrote {path.name}: {output['meta']['trials_analyzed']} trials, "
                f"{output['meta']['total_citations']} citations"
            )


if __name__ == "__main__":
    main()
