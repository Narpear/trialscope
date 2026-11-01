import json
import os
import time
from pathlib import Path

import httpx

BASE_URL = os.getenv("EXAMPLES_BASE_URL", "http://127.0.0.1:8000")
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLES = {
    "time_trend": {
        "query": "How many rheumatoid arthritis trials started each year since 2015?",
    },
    "comparison": {
        "query": "Compare phases for trials involving pembrolizumab vs nivolumab.",
    },
    "geographic": {
        "query": "Which countries have the most recruiting trials for melanoma?",
    },
    "network": {
        "query": "Which drugs frequently co-occur in combination studies for pancreatic cancer?",
        "max_trials": 10000,
    },
    "distribution": {
        "query": "How are breast cancer trials distributed across phases?",
    },
}


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with httpx.Client(timeout=300) as client:
        for index, (name, request) in enumerate(EXAMPLES.items()):
            if index:
                time.sleep(10)  # stay well under the service and ClinicalTrials.gov rate limits
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
            meta = output["meta"]
            print(
                f"Wrote {path.name}: {meta['total_matching']} matching, "
                f"{meta['trials_analyzed']} fetched, counts {meta['count_basis']}, "
                f"{meta['total_citations']} citations"
            )


if __name__ == "__main__":
    main()
