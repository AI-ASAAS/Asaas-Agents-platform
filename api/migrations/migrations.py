import logging
from database import Database

logger = logging.getLogger(__name__)


class Migration:
    version: int
    name: str

    @staticmethod
    async def up(conn) -> None:
        raise NotImplementedError


class Migration001_Baseline(Migration):
    version = 1
    name = "0001_baseline"

    @staticmethod
    async def up(conn) -> None:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _system_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.execute(
            "INSERT OR IGNORE INTO _system_meta (key, value) VALUES ('platform_version', '1.0.0')"
        )


class Migration002_CreateAgentsAndCategories(Migration):
    version = 2
    name = "0002_create_agents_and_categories"

    @staticmethod
    async def up(conn) -> None:
        # 1. Categories table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                slug TEXT PRIMARY KEY,
                name_ar TEXT NOT NULL,
                name_en TEXT,
                icon TEXT,
                display_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Seed standard categories
        categories_data = [
            ("customer-service", "خدمة العملاء", "Customer Service", "headset", 1),
            ("data-analysis", "تحليل البيانات", "Data Analysis", "receipt", 2),
            ("automation", "الأتمتة وتدفق العمل", "Automation", "collect", 3),
            ("coding", "البرمجة والتطوير", "Coding & Dev", "briefcase", 4),
            ("finance", "المالية والمحاسبة", "Finance", "vault", 5),
            ("research", "البحث والاستقصاء", "Research", "dashboard", 6),
            ("other", "أخرى", "Other", "plus", 7),
        ]
        for c in categories_data:
            await conn.execute(
                """
                INSERT OR IGNORE INTO categories (slug, name_ar, name_en, icon, display_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                c,
            )

        # 2. Agents table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                slug TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                category TEXT NOT NULL,
                featured INTEGER NOT NULL DEFAULT 0,
                name_ar TEXT NOT NULL,
                name_en TEXT,
                summary_ar TEXT NOT NULL,
                summary_en TEXT,
                description_ar TEXT NOT NULL,
                description_en TEXT,
                icon TEXT NOT NULL,
                github_url TEXT NOT NULL,
                pinned_ref TEXT NOT NULL,
                playground_mode TEXT NOT NULL,
                playground_ui TEXT NOT NULL,
                model_requirements TEXT NOT NULL,
                allowed_providers TEXT NOT NULL,
                limits TEXT NOT NULL,
                manifest TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_sample INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category) REFERENCES categories(slug)
            )
            """
        )

        # Indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_category ON agents(category)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_featured ON agents(featured)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(is_active)")


class Migration003_CreateAnonymousStats(Migration):
    version = 3
    name = "0003_create_anonymous_stats"

    @staticmethod
    async def up(conn) -> None:
        """
        Decision D7: Privacy-preserving aggregate statistics.
        Zero IP addresses, zero cookies, zero device fingerprints.
        Stores only purely aggregate counts per agent.
        """
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_stats (
                agent_slug TEXT PRIMARY KEY,
                views_count INTEGER NOT NULL DEFAULT 0,
                runs_started INTEGER NOT NULL DEFAULT 0,
                runs_succeeded INTEGER NOT NULL DEFAULT 0,
                runs_failed INTEGER NOT NULL DEFAULT 0,
                last_run_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_slug) REFERENCES agents(slug) ON DELETE CASCADE
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_stats_views ON agent_stats(views_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_stats_runs ON agent_stats(runs_started)")


class Migration004_AddMarketingAnalyticsCategory(Migration):
    version = 4
    name = "0004_add_marketing_analytics_category"

    @staticmethod
    async def up(conn) -> None:
        await conn.execute(
            """
            INSERT OR IGNORE INTO categories (slug, name_ar, name_en, icon, display_order)
            VALUES ('marketing-analytics', 'التسويق والتحليلات', 'Marketing & Analytics', 'globe', 4)
            """
        )


ALL_MIGRATIONS: list[type[Migration]] = [
    Migration001_Baseline,
    Migration002_CreateAgentsAndCategories,
    Migration003_CreateAnonymousStats,
    Migration004_AddMarketingAnalyticsCategory,
]


async def run_migrations() -> None:
    """
    Applies all pending migrations in ascending order.
    Ensures _schema_migrations tracking table exists.
    """
    await Database.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    applied_rows = await Database.fetch_all("SELECT version FROM _schema_migrations")
    applied_versions = {row["version"] for row in applied_rows}

    for migration_cls in sorted(ALL_MIGRATIONS, key=lambda m: m.version):
        if migration_cls.version not in applied_versions:
            logger.info("Applying migration %03d: %s", migration_cls.version, migration_cls.name)
            async with Database.transaction() as conn:
                await migration_cls.up(conn)
                await conn.execute(
                    "INSERT INTO _schema_migrations (version, name) VALUES (?, ?)",
                    (migration_cls.version, migration_cls.name),
                )
            logger.info("Migration %03d applied successfully", migration_cls.version)
