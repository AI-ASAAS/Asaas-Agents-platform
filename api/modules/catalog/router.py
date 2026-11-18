from fastapi import APIRouter, Header, Query, Request

from .repository import CatalogRepository
from .schemas import AgentCardResponse, AgentDetailResponse, CategoryResponse, StatsResponse
from .service import CatalogService

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    x_lang: str = Header(default="ar", alias="x-lang"),
) -> list[CategoryResponse]:
    """Retrieve all available agent categories."""
    return await CatalogService.get_categories(lang=x_lang)


@router.get("/agents", response_model=list[AgentCardResponse])
async def list_agents(
    q: str | None = Query(default=None, description="Search term for agent name or summary"),
    category: str | None = Query(default=None, description="Filter by category slug"),
    x_lang: str = Header(default="ar", alias="x-lang"),
) -> list[AgentCardResponse]:
    """List all active agents matching optional search and category filters."""
    return await CatalogService.get_agents(query=q, category=category, lang=x_lang)


@router.get("/agents/{slug}", response_model=AgentDetailResponse)
async def get_agent(
    slug: str,
    x_lang: str = Header(default="ar", alias="x-lang"),
) -> AgentDetailResponse:
    """Retrieve full details of an active agent by its slug."""
    return await CatalogService.get_agent(slug=slug, lang=x_lang)


@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """Retrieve real aggregated platform statistics."""
    return await CatalogService.get_stats()


@router.post("/agents/{slug}/view")
async def record_agent_view(slug: str, request: Request) -> dict[str, bool]:
    """
    Privacy-friendly anonymous view counter (Decision D7).
    No cookies, no IP address storage, no user agents.
    Strictly honors Do-Not-Track (DNT: 1) and Global Privacy Control (Sec-GPC: 1).
    Never blocks rendering, never raises errors to visitors.
    """
    dnt = request.headers.get("dnt")
    sec_gpc = request.headers.get("sec-gpc")

    if dnt == "1" or sec_gpc == "1":
        # Respect visitor privacy preferences: drop view counting
        return {"ok": True}

    await CatalogRepository.record_view(slug)
    return {"ok": True}
