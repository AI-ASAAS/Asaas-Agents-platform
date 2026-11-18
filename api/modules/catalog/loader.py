import json
import logging
from pathlib import Path
from pydantic import ValidationError

from config import settings
from database import Database
from .manifest_schema import AgentManifest

logger = logging.getLogger("catalog.loader")


class ManifestLoadError(Exception):
    """Raised when one or more agent manifests fail validation."""


async def load_and_seed_agents(agents_dir_path: Path | None = None) -> list[str]:
    """
    Reads agents/*/agent.manifest.json (and fallback manifest.json).
    Validates all manifests strictly before persisting any to guarantee zero half-loads.
    Performs idempotent upsert and marks vanished agents as inactive.
    Returns the list of loaded agent slugs.
    """
    base_dir = agents_dir_path or (Path(__file__).resolve().parent.parent.parent / settings.agents_dir).resolve()
    if not base_dir.exists():
        logger.warning("Agents directory does not exist at %s", base_dir)
        return []

    manifest_files = list(base_dir.glob("*/agent.manifest.json"))
    manifest_files += [f for f in base_dir.glob("*/manifest.json") if f.name != "agent.manifest.json" and f.parent not in [m.parent for m in manifest_files]]

    if not manifest_files:
        logger.info("No agent manifests found in %s", base_dir)
        return []

    parsed_manifests: list[tuple[Path, AgentManifest]] = []

    # PASS 1: Strict validation of ALL manifests. Fail loudly on first error without modifying DB.
    for file_path in manifest_files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            raise ManifestLoadError(f"Cannot read manifest file at {file_path}: {e}") from e

        try:
            manifest = AgentManifest.model_validate_json(content)
            parsed_manifests.append((file_path, manifest))
        except ValidationError as e:
            first_err = e.errors()[0]
            field_path = ".".join(str(p) for p in first_err.get("loc", []))
            msg = first_err.get("msg", "Validation error")
            err_detail = f"Invalid manifest in {file_path}: field '{field_path}' - {msg}"
            logger.error(err_detail)
            raise ManifestLoadError(err_detail) from e
        except Exception as e:
            err_detail = f"Malformed JSON in {file_path}: {e}"
            logger.error(err_detail)
            raise ManifestLoadError(err_detail) from e

    # Filter samples if configured
    eligible_manifests: list[AgentManifest] = []
    for _, manifest in parsed_manifests:
        if manifest.is_sample and not settings.include_sample_agents:
            logger.info("Skipping sample agent %s because include_sample_agents is False", manifest.slug)
            continue
        eligible_manifests.append(manifest)

    # PASS 2: Idempotent upsert into database inside a transaction
    loaded_slugs: list[str] = []
    async with Database.transaction() as conn:
        for m in eligible_manifests:
            await conn.execute(
                """
                INSERT INTO agents (
                    slug, status, category, featured,
                    name_ar, name_en, summary_ar, summary_en, description_ar, description_en,
                    icon, github_url, pinned_ref, playground_mode, playground_ui,
                    model_requirements, allowed_providers, limits, manifest,
                    is_active, is_sample, updated_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    1, ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT(slug) DO UPDATE SET
                    status=excluded.status,
                    category=excluded.category,
                    featured=excluded.featured,
                    name_ar=excluded.name_ar,
                    name_en=excluded.name_en,
                    summary_ar=excluded.summary_ar,
                    summary_en=excluded.summary_en,
                    description_ar=excluded.description_ar,
                    description_en=excluded.description_en,
                    icon=excluded.icon,
                    github_url=excluded.github_url,
                    pinned_ref=excluded.pinned_ref,
                    playground_mode=excluded.playground_mode,
                    playground_ui=excluded.playground_ui,
                    model_requirements=excluded.model_requirements,
                    allowed_providers=excluded.allowed_providers,
                    limits=excluded.limits,
                    manifest=excluded.manifest,
                    is_active=1,
                    is_sample=excluded.is_sample,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    m.slug,
                    m.status,
                    m.category,
                    1 if m.featured else 0,
                    m.name.ar,
                    m.name.en,
                    m.summary.ar,
                    m.summary.en,
                    m.description.ar,
                    m.description.en,
                    m.icon,
                    str(m.github.url),
                    m.github.pinned_ref,
                    m.playground.mode,
                    m.playground.ui,
                    json.dumps(m.model_requirements.model_dump(), ensure_ascii=False),
                    json.dumps(m.providers.allow, ensure_ascii=False),
                    json.dumps(m.limits.model_dump(), ensure_ascii=False),
                    json.dumps(m.model_dump(mode="json"), ensure_ascii=False),
                    1 if m.is_sample else 0,
                ),
            )
            loaded_slugs.append(m.slug)

        # PASS 3: Mark agents whose manifest disappeared as inactive
        if loaded_slugs:
            placeholders = ",".join("?" for _ in loaded_slugs)
            await conn.execute(
                f"UPDATE agents SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE slug NOT IN ({placeholders})",
                tuple(loaded_slugs),
            )

    logger.info("Successfully seeded %d agents: %s", len(loaded_slugs), loaded_slugs)
    return loaded_slugs
