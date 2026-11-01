import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.planner.openai_planner import OpenAIPlanner, PlannerError
from app.schemas import QueryRequest
from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "planner_cases.json"


def normalize(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def evaluate_case(case: dict[str, Any], plan: dict[str, Any] | None, error: str | None) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if error:
        return False, [error]
    assert plan is not None
    expected_type = case["expected_analysis_type"]
    expected_answerable = case["expected_answerable"]
    if expected_answerable and plan["analysis_type"] != expected_type:
        failures.append(f"type={plan['analysis_type']} (expected {expected_type})")
    if plan["answerable"] is not expected_answerable:
        failures.append(f"answerable={plan['answerable']} (expected {expected_answerable})")
    if not expected_answerable and not plan.get("unsupported_reason"):
        failures.append("unsupported_reason is missing for an unanswerable query")

    actual_filters = plan["filters"]
    for key, expected in case.get("expected_filters", {}).items():
        if normalize(actual_filters.get(key)) != normalize(expected):
            failures.append(f"{key}={actual_filters.get(key)!r} (expected {expected!r})")

    expected_group_by = case.get("expected_group_by")
    if expected_group_by and plan.get("group_by") != expected_group_by:
        failures.append(f"group_by={plan.get('group_by')!r} (expected {expected_group_by!r})")

    for key in ("expected_comparison_groups", "expected_network_entity_types"):
        expected_items = case.get(key, [])
        if expected_items:
            actual_key = "comparison_groups" if key == "expected_comparison_groups" else "network_entity_types"
            actual_items = {normalize(item) for item in plan.get(actual_key, [])}
            missing = [item for item in expected_items if normalize(item) not in actual_items]
            if missing:
                failures.append(f"{actual_key} missing {', '.join(missing)}")
    return not failures, failures


async def run_eval(cases_path: Path, limit: int | None = None) -> int:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run the real planner evaluation.")
    cases = json.loads(cases_path.read_text())
    if limit:
        cases = cases[:limit]
    planner = OpenAIPlanner(settings.openai_api_key, settings.openai_model)
    passed = 0
    try:
        print(f"Planner evaluation — model: {settings.openai_model}")
        print(f"{'CASE':34} {'RESULT':7} DETAILS")
        print("-" * 100)
        for case in cases:
            plan = None
            error = None
            try:
                plan = (await planner.plan(QueryRequest(query=case["query"]))).model_dump(
                    mode="json"
                )
            except PlannerError as exc:
                error = f"{exc.code}: {exc.message}"
            ok, failures = evaluate_case(case, plan, error)
            if ok:
                passed += 1
                details = (
                    f"{plan['analysis_type']}; answerable={plan['answerable']}; "
                    f"filters={json.dumps(plan['filters'], sort_keys=True)}"
                )
                result = "PASS"
            else:
                details = "; ".join(failures)
                result = "FAIL"
            print(f"{case['id'][:34]:34} {result:7} {details}")
    finally:
        await planner.client.close()
    print("-" * 100)
    print(f"Summary: {passed}/{len(cases)} passed, {len(cases) - passed} failed.")
    return 0 if passed == len(cases) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the real structured-output query planner.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--limit", type=int, help="Run only the first N cases.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_eval(args.cases, args.limit)))


if __name__ == "__main__":
    main()
