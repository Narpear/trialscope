import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.planner.openai_planner import PlannerError
from app.query_service import QueryService
from app.rate_limit import InMemoryRateLimiter, client_ip
from app.schemas import ErrorResponse, QueryRequest
from app.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.query_service = QueryService(settings)
    app.state.rate_limiter = InMemoryRateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    yield
    await app.state.query_service.close()


app = FastAPI(title="ClinicalTrials.gov Query Visualizer", version="0.1.0", lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_response(
        422,
        "validation_error",
        "Request validation failed.",
        {
            "errors": [
                {
                    "type": error["type"],
                    "location": error["loc"],
                    "message": error["msg"],
                }
                for error in exc.errors()
            ]
        },
    )


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "source": "clinicaltrials.gov"}


@app.get("/api/schema")
async def schema():
    from app.schemas import QueryResponse

    return {
        "request": QueryRequest.model_json_schema(),
        "response": QueryResponse.model_json_schema(),
    }


@app.post("/api/query", responses={422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
async def query(payload: QueryRequest, request: Request):
    if not request.app.state.rate_limiter.allow(client_ip(request, settings.trusted_proxy_hops)):
        return error_response(429, "rate_limited", "Too many queries. Please try again later.")
    try:
        result = await request.app.state.query_service.query(payload)
        return result.model_dump(mode="json", by_alias=True)
    except PlannerError as exc:
        status = {
            "unsupported_query": 422,
            "planner_key_required": 422,
            "invalid_plan": 422,
            "planner_invalid_plan": 502,
            "planner_unavailable": 503,
            "clinicaltrials_unavailable": 502,
        }.get(exc.code, 500)
        return error_response(status, exc.code, exc.message, exc.details)
    except Exception:
        logger.exception("Unexpected error while processing a clinical trials query")
        return error_response(
            500,
            "internal_error",
            "The query could not be completed because of an internal service error.",
        )
