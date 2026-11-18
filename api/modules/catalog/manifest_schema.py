import re
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator


class LocalizedString(BaseModel):
    ar: str = Field(min_length=1, max_length=5000)
    en: str | None = None


class AgentGithub(BaseModel):
    url: HttpUrl
    pinned_ref: str = Field(min_length=40, max_length=40)

    @field_validator("pinned_ref")
    @classmethod
    def validate_pinned_ref(cls, v: str) -> str:
        if not re.match(r"^[0-9a-f]{40}$", v.lower()):
            raise ValueError("pinned_ref must be a valid 40-character hexadecimal Git commit SHA, not a branch name")
        return v.lower()


class ServiceSpec(BaseModel):
    command: str = Field(min_length=1, max_length=500)
    host: str = Field(default="127.0.0.1", min_length=1, max_length=100)
    port: int = Field(default=8001, ge=1024, le=65535)
    health_check_path: str = Field(default="/api/v1/health", min_length=1, max_length=200)
    route_allowlist: list[str] = Field(default_factory=list)


class AgentRuntime(BaseModel):
    kind: Literal["python", "service"] = "python"
    python: str = Field(min_length=1, max_length=10, default="3.12")
    entrypoint: str | None = None
    protocol: str | None = None
    service_spec: ServiceSpec | None = None
    egress_policy: Literal["loopback_only", "public_http"] = "loopback_only"


class AgentPlayground(BaseModel):
    mode: Literal["chat", "form", "file-analysis", "custom", "standalone"]
    ui: str = Field(min_length=1, max_length=100)
    mount_path: str | None = None
    api_base: str | None = None


class AgentModelRequirements(BaseModel):
    tool_calling: bool = False
    json_schema: bool = False
    vision: bool = False
    min_context_tokens: int = Field(default=32000, ge=1000)


class AgentProviders(BaseModel):
    allow: list[Literal["gemini", "openai", "anthropic", "openrouter"]] = Field(min_length=1)


class AgentUploadLimits(BaseModel):
    max_files: int = Field(default=1, ge=1, le=10)
    max_mb: int = Field(default=5, ge=1, le=50)
    types: list[str] = Field(default_factory=lambda: ["application/pdf"])


class AgentLimits(BaseModel):
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_seconds: int = Field(default=120, ge=10, le=300)
    max_input_chars: int = Field(default=8000, ge=100, le=50000)
    max_output_tokens: int = Field(default=2000, ge=100, le=16000)
    uploads: AgentUploadLimits | None = None
    # Service tier limits
    max_wall_clock_seconds: int = Field(default=1200, ge=60, le=3600)
    platform_concurrent_runs: int = Field(default=2, ge=1, le=10)
    session_concurrent_runs: int = Field(default=1, ge=1, le=5)
    session_daily_runs: int = Field(default=3, ge=1, le=50)
    max_pages_per_run: int = Field(default=8, ge=1, le=20)


CategoryLiteral = Literal[
    "customer-service",
    "data-analysis",
    "automation",
    "coding",
    "finance",
    "research",
    "marketing-analytics",
    "other",
]

StatusLiteral = Literal["ready", "coming_soon", "github_only"]


class AgentManifest(BaseModel):
    schema_version: Literal[1] = 1
    slug: str = Field(min_length=1, max_length=100)
    name: LocalizedString
    summary: LocalizedString
    description: LocalizedString
    category: CategoryLiteral
    icon: str = Field(min_length=1, max_length=50)
    status: StatusLiteral
    featured: bool = False
    is_sample: bool = False
    github: AgentGithub
    runtime: AgentRuntime
    playground: AgentPlayground
    model_requirements: AgentModelRequirements
    providers: AgentProviders
    limits: AgentLimits

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", v):
            raise ValueError("slug must be lowercase kebab-case (letters, numbers, and single hyphens)")
        return v
