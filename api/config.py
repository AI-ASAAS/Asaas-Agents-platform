from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ASAAS Agents API"
    environment: str = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    database_path: str = "./data/app.db"
    max_request_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    allowed_origins: list[str] = []  # Empty by default = same-origin only
    web_dist_path: str = "../web/dist"
    agents_dir: str = "../agents"
    include_sample_agents: bool = True

    # LLM Gateway & Provider Configuration
    llm_timeout_seconds: float = 90.0  # Allows multimodal vision payloads (up to 8 screenshots)
    llm_connect_timeout_seconds: float = 5.0
    llm_max_retries: int = 1
    llm_backoff_seconds: float = 0.5

    # Strict Provider Base URL Allowlist (SSRF Protection)
    provider_base_urls: dict[str, str] = {
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini_native": "https://generativelanguage.googleapis.com/v1beta",
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }

    # Strict IP Rate Limiting for Key Validation & Connection Test (Legacy)
    ip_rate_limit_max_requests: int = 20
    ip_rate_limit_window_seconds: int = 60

    # Phase 5: Abuse Protection, Trusted Proxies & Rate Limits (Tune after one week of real use)
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]
    rate_limit_validate_key_per_min: int = 10       # Tune after one week of real use
    rate_limit_test_connection_per_min: int = 6     # Tune after one week of real use
    rate_limit_run_starts_per_min: int = 10         # Tune after one week of real use
    rate_limit_daily_runs_per_ip: int = 50          # Tune after one week of real use

    # Phase 4: Runtime, Isolation & Platform Ceilings
    platform_max_timeout_seconds: int = 180
    platform_max_steps: int = 15
    platform_max_input_chars: int = 16000
    platform_max_output_tokens: int = 4096
    platform_max_upload_mb: int = 10
    platform_max_upload_files: int = 3

    # Concurrency Caps
    max_concurrent_runs_global: int = 10
    max_concurrent_runs_per_ip: int = 2

    # Stream & Buffer Bounding
    agent_output_line_max_bytes: int = 65536  # 64 KB
    agent_total_output_max_bytes: int = 524288  # 512 KB total output limit per run
    agent_stderr_max_bytes: int = 65536  # 64 KB
    agent_loopback_base_url: str = "http://127.0.0.1:8088/v1"

    # Linux Production Sandbox & Resource Limits (D3)
    agent_uid: int | None = None
    agent_gid: int | None = None
    agent_rlimit_cpu_seconds: int = 120
    agent_rlimit_as_bytes: int = 512 * 1024 * 1024  # 512 MB virtual memory
    agent_rlimit_nproc: int = 32  # Prevent fork bombs
    agent_rlimit_nofile: int = 64  # Max open file descriptors
    agent_rlimit_fsize_bytes: int = 10 * 1024 * 1024  # Max 10 MB per written file

    # Tier-2 Service Agents Ceilings & Policies (Assumptions to tune after 1 week of real use)
    service_session_sliding_ttl_seconds: int = 2700      # 45 minutes
    service_session_max_ttl_seconds: int = 7200          # 2 hours absolute cap
    service_max_wall_clock_seconds: int = 1200           # 20 minutes per analysis run
    service_max_concurrent_global: int = 2               # Platform-wide active service runs
    service_max_concurrent_per_ip: int = 1               # Per-IP active service runs
    service_daily_runs_per_ip: int = 3                   # Per-IP daily service runs
    service_max_pages_per_run: int = 8                   # Public demo crawl ceiling
    service_run_retention_minutes: int = 60              # Purge finished run artifacts after 60m
    service_disk_quota_session_mb: int = 150             # Per-session disk cap
    service_disk_quota_global_mb: int = 1024             # Global service runs disk cap (1 GB)
    service_sse_orphan_cancel_seconds: int = 120         # Cancel run 2m after last SSE disconnect
    service_agent_uid: int | None = None                 # Dedicated OS user UID on Linux (asaas-service-sitedna)
    service_agent_gid: int | None = None
    site_dna_port: int = 8001
    site_dna_auto_start: bool = True
    site_dna_data_dir: str | None = None                 # Private data dir for Site DNA runs
    platform_own_hosts: list[str] = [
        "localhost",
        "127.0.0.1",
        "::1",
        "agents.ai-asaas.com",
        "site-dna.asaas.ai",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_database_path(self) -> Path:
        p = Path(self.database_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p

    @property
    def resolved_web_dist_path(self) -> Path:
        p = Path(self.web_dist_path)
        if not p.is_absolute():
            p = (Path(__file__).resolve().parent / p).resolve()
        return p

    @property
    def resolved_agents_dir(self) -> Path:
        p = Path(self.agents_dir)
        if not p.is_absolute():
            p = (Path(__file__).resolve().parent / p).resolve()
        return p

    @property
    def model_capabilities_path(self) -> Path:
        return Path(__file__).resolve().parent / "config" / "model_capabilities.json"

    @property
    def provider_limits_path(self) -> Path:
        return Path(__file__).resolve().parent / "config" / "provider_limits.json"


settings = Settings()
