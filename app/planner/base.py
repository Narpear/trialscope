from typing import Protocol

from app.schemas import QueryPlan, QueryRequest


class Planner(Protocol):
    async def plan(self, request: QueryRequest) -> QueryPlan: ...
