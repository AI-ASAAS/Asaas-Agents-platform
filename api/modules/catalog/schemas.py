from typing import Any
from pydantic import BaseModel


class CategoryResponse(BaseModel):
    slug: str
    name: str
    icon: str


class AgentCardResponse(BaseModel):
    slug: str
    name: str
    summary: str
    category: str
    icon: str
    status: str
    featured: bool
    github_url: str


class AgentDetailResponse(BaseModel):
    slug: str
    name: str
    summary: str
    description: str
    category: str
    icon: str
    status: str
    featured: bool
    github_url: str
    pinned_ref: str
    playground_mode: str
    playground_ui: str
    model_requirements: dict[str, Any]
    allowed_providers: list[str]
    limits: dict[str, Any]


class StatsResponse(BaseModel):
    agent_count: int
    total_runs: int = 0
    successful_runs: int = 0
    total_views: int = 0
    has_real_runs: bool = False
