import json
from typing import Any
from fastapi import HTTPException, status

from .repository import CatalogRepository
from .schemas import AgentCardResponse, AgentDetailResponse, CategoryResponse, StatsResponse


class CatalogService:
    """
    Business logic for the catalog module.
    Handles localization projection and response shaping.
    """

    @staticmethod
    async def get_categories(lang: str = "ar") -> list[CategoryResponse]:
        rows = await CatalogRepository.get_categories()
        results: list[CategoryResponse] = []
        is_en = lang.lower().startswith("en")
        for row in rows:
            name = row["name_en"] if is_en and row.get("name_en") else row["name_ar"]
            results.append(
                CategoryResponse(
                    slug=row["slug"],
                    name=name,
                    icon=row["icon"] or "cube",
                )
            )
        return results

    @staticmethod
    async def get_agents(
        query: str | None = None,
        category: str | None = None,
        lang: str = "ar",
    ) -> list[AgentCardResponse]:
        rows = await CatalogRepository.list_agents(query=query, category=category)
        results: list[AgentCardResponse] = []
        is_en = lang.lower().startswith("en")
        for row in rows:
            name = row["name_en"] if is_en and row.get("name_en") else row["name_ar"]
            summary = row["summary_en"] if is_en and row.get("summary_en") else row["summary_ar"]
            results.append(
                AgentCardResponse(
                    slug=row["slug"],
                    name=name,
                    summary=summary,
                    category=row["category"],
                    icon=row["icon"] or "bot",
                    status=row["status"],
                    featured=bool(row["featured"]),
                    github_url=row["github_url"],
                )
            )
        return results

    @staticmethod
    async def get_agent(slug: str, lang: str = "ar") -> AgentDetailResponse:
        row = await CatalogRepository.get_agent_by_slug(slug)
        if not row:
            is_en = lang.lower().startswith("en")
            msg = "Agent not found." if is_en else "الوكيل غير موجود."
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)

        is_en = lang.lower().startswith("en")
        name = row["name_en"] if is_en and row.get("name_en") else row["name_ar"]
        summary = row["summary_en"] if is_en and row.get("summary_en") else row["summary_ar"]
        desc = row["description_en"] if is_en and row.get("description_en") else row["description_ar"]

        # Parse JSON stored fields if string
        model_reqs = row["model_requirements"]
        if isinstance(model_reqs, str):
            model_reqs = json.loads(model_reqs)

        allowed_provs = row["allowed_providers"]
        if isinstance(allowed_provs, str):
            allowed_provs = json.loads(allowed_provs)

        limits = row["limits"]
        if isinstance(limits, str):
            limits = json.loads(limits)

        return AgentDetailResponse(
            slug=row["slug"],
            name=name,
            summary=summary,
            description=desc,
            category=row["category"],
            icon=row["icon"] or "bot",
            status=row["status"],
            featured=bool(row["featured"]),
            github_url=row["github_url"],
            pinned_ref=row["pinned_ref"],
            playground_mode=row["playground_mode"],
            playground_ui=row["playground_ui"],
            model_requirements=model_reqs or {},
            allowed_providers=allowed_provs or [],
            limits=limits or {},
        )

    @staticmethod
    async def get_stats() -> StatsResponse:
        data = await CatalogRepository.get_stats()
        return StatsResponse(**data)
