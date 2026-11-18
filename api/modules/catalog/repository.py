from typing import Any
from database import Database


class CatalogRepository:
    """
    Persistence layer for categories and agent catalog.
    Uses parameterized raw SQL through Database wrapper.
    """

    @staticmethod
    async def get_categories() -> list[dict[str, Any]]:
        return await Database.fetch_all(
            "SELECT slug, name_ar, name_en, icon, display_order FROM categories ORDER BY display_order ASC"
        )

    @staticmethod
    async def list_agents(
        query: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
                a.slug, a.status, a.category, a.featured,
                a.name_ar, a.name_en, a.summary_ar, a.summary_en,
                a.icon, a.github_url
            FROM agents a
            WHERE a.is_active = 1
        """
        params: list[Any] = []

        if category and category.strip():
            sql += " AND a.category = ?"
            params.append(category.strip())

        if query and query.strip():
            term = f"%{query.strip()}%"
            sql += """
                AND (
                    a.name_ar LIKE ? OR
                    a.name_en LIKE ? OR
                    a.summary_ar LIKE ? OR
                    a.summary_en LIKE ? OR
                    a.slug LIKE ?
                )
            """
            params.extend([term, term, term, term, term])

        sql += " ORDER BY a.featured DESC, a.created_at DESC"
        return await Database.fetch_all(sql, tuple(params))

    @staticmethod
    async def get_agent_by_slug(slug: str) -> dict[str, Any] | None:
        return await Database.fetch_one(
            """
            SELECT
                a.slug, a.status, a.category, a.featured,
                a.name_ar, a.name_en, a.summary_ar, a.summary_en,
                a.description_ar, a.description_en,
                a.icon, a.github_url, a.pinned_ref,
                a.playground_mode, a.playground_ui,
                a.model_requirements, a.allowed_providers, a.limits
            FROM agents a
            WHERE a.slug = ? AND a.is_active = 1
            """,
            (slug,),
        )

    @staticmethod
    async def get_agent_count() -> int:
        row = await Database.fetch_one("SELECT COUNT(*) as count FROM agents WHERE is_active = 1")
        return int(row["count"]) if row else 0

    @staticmethod
    async def record_view(slug: str) -> None:
        """Atomically increments anonymous agent view counter with zero user info."""
        sql = """
            INSERT INTO agent_stats (agent_slug, views_count, updated_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_slug) DO UPDATE SET
                views_count = views_count + 1,
                updated_at = CURRENT_TIMESTAMP
        """
        try:
            await Database.execute(sql, (slug,))
        except Exception:
            pass

    @staticmethod
    async def record_run_started(slug: str) -> None:
        """Atomically increments anonymous run start counter."""
        sql = """
            INSERT INTO agent_stats (agent_slug, runs_started, last_run_at, updated_at)
            VALUES (?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_slug) DO UPDATE SET
                runs_started = runs_started + 1,
                last_run_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        """
        try:
            await Database.execute(sql, (slug,))
        except Exception:
            pass

    @staticmethod
    async def record_run_outcome(slug: str, success: bool) -> None:
        """Atomically records anonymous run outcome without user info."""
        col = "runs_succeeded" if success else "runs_failed"
        sql = f"""
            INSERT INTO agent_stats (agent_slug, {col}, updated_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_slug) DO UPDATE SET
                {col} = {col} + 1,
                updated_at = CURRENT_TIMESTAMP
        """
        try:
            await Database.execute(sql, (slug,))
        except Exception:
            pass

    @staticmethod
    async def get_stats() -> dict[str, Any]:
        """Calculates global catalog statistics."""
        agent_row = await Database.fetch_one("SELECT COUNT(*) as count FROM agents WHERE is_active = 1")
        stats_row = await Database.fetch_one(
            """
            SELECT
                COALESCE(SUM(runs_started), 0) as total_runs,
                COALESCE(SUM(runs_succeeded), 0) as successful_runs,
                COALESCE(SUM(views_count), 0) as total_views
            FROM agent_stats
            """
        )
        agent_count = int(agent_row["count"]) if agent_row else 0
        total_runs = int(stats_row["total_runs"]) if stats_row else 0
        successful_runs = int(stats_row["successful_runs"]) if stats_row else 0
        total_views = int(stats_row["total_views"]) if stats_row else 0

        return {
            "agent_count": agent_count,
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "total_views": total_views,
            "has_real_runs": total_runs > 0,
        }
