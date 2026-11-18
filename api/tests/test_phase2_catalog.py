import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

from config import settings
from database import Database
from main import app
from migrations import run_migrations
from modules.catalog.loader import ManifestLoadError, load_and_seed_agents
from modules.catalog.manifest_schema import AgentManifest


def test_manifest_validation_loud_failure():
    """Verify that an invalid manifest fails loudly, naming file and field, without half-loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        bad_agent_dir = tmp_path / "bad-agent"
        bad_agent_dir.mkdir()
        bad_manifest = bad_agent_dir / "agent.manifest.json"

        # Missing required field 'status' and bad slug
        bad_manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "slug": "Bad_Slug!",  # invalid regex
                    "name": {"ar": "تجربة"},
                    # missing name.en, status, etc.
                }
            ),
            encoding="utf-8",
        )

        try:
            asyncio.run(load_and_seed_agents(agents_dir_path=tmp_path))
            raise AssertionError("Expected ManifestLoadError was not raised for invalid manifest")
        except ManifestLoadError as e:
            err_str = str(e)
            assert "bad-agent" in err_str or "agent.manifest.json" in err_str
            assert "slug" in err_str or "field" in err_str
            print("✓ Manifest validation failed loudly as expected:", err_str)


def test_catalog_endpoints():
    with TestClient(app) as client:
        # 1. Health check
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["database"] == "connected"
        print("✓ Health check OK")

        # 2. Categories
        res = client.get("/api/categories")
        assert res.status_code == 200
        cats = res.json()
        assert len(cats) >= 4
        assert any(c["slug"] == "customer-service" for c in cats)
        print("✓ Categories list OK (count:", len(cats), ")")

        # Categories English
        res_en = client.get("/api/categories", headers={"x-lang": "en"})
        assert res_en.status_code == 200
        cs_cat = next(c for c in res_en.json() if c["slug"] == "customer-service")
        assert cs_cat["name"] == "Customer Service"
        print("✓ Categories English translation OK")

        # 3. Agents list
        res = client.get("/api/agents")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) >= 2
        slugs = [a["slug"] for a in agents]
        assert "support-agent" in slugs
        assert "document-analyzer" in slugs
        print("✓ Agents list OK (count:", len(agents), ", slugs:", slugs, ")")

        # 4. Search query
        res = client.get("/api/agents?q=خدمة")
        assert res.status_code == 200
        results = res.json()
        assert len(results) >= 1
        assert results[0]["slug"] == "support-agent"
        print("✓ Agent search by Arabic keyword OK")

        # Non-matching search query -> 200 with empty list
        res = client.get("/api/agents?q=nonexistent_query_xyz_123")
        assert res.status_code == 200
        assert res.json() == []
        print("✓ Empty search query returns [] OK")

        # 5. Category filter
        res = client.get("/api/agents?category=customer-service")
        assert res.status_code == 200
        cs_agents = res.json()
        assert all(a["category"] == "customer-service" for a in cs_agents)
        assert any(a["slug"] == "support-agent" for a in cs_agents)
        print("✓ Agent category filter OK")

        # Non-matching category -> 200 with empty list
        res = client.get("/api/agents?category=nonexistent-category")
        assert res.status_code == 200
        assert res.json() == []
        print("✓ Empty category filter returns [] OK")

        # 6. Agent detail
        res = client.get("/api/agents/support-agent")
        assert res.status_code == 200
        detail = res.json()
        assert detail["slug"] == "support-agent"
        assert detail["status"] == "ready"
        assert detail["pinned_ref"] == "4a5c68b72e1289dfc98124ef5a1b32d098765432"
        assert "model_requirements" in detail
        assert detail["model_requirements"]["tool_calling"] is True
        assert "gemini" in detail["allowed_providers"]
        assert "openai" in detail["allowed_providers"]
        # Ensure no runtime internal details leaked (like command line or local directory paths)
        assert "command" not in detail
        assert "manifest" not in detail
        print("✓ Agent detail OK (safe schema, no runtime leaks)")

        # 7. Agent 404
        res = client.get("/api/agents/nonexistent-slug")
        assert res.status_code == 404
        err_body = res.json()
        assert err_body["code"] == "NOT_FOUND"
        assert err_body["message"] == "الوكيل غير موجود."
        print("✓ Agent 404 returns standard Arabic error payload OK")

        # Agent 404 with English header
        res = client.get("/api/agents/nonexistent-slug", headers={"x-lang": "en"})
        assert res.status_code == 404
        err_body = res.json()
        assert err_body["code"] == "NOT_FOUND"
        assert err_body["message"] == "Agent not found."
        print("✓ Agent 404 with English header returns standard English error payload OK")

        # 8. Stats
        res = client.get("/api/stats")
        assert res.status_code == 200
        stats = res.json()
        assert stats["agent_count"] >= 2
        print("✓ Stats endpoint OK (agent_count:", stats["agent_count"], ")")


if __name__ == "__main__":
    print("--- Running Phase 2 Backend Tests ---")
    test_manifest_validation_loud_failure()
    test_catalog_endpoints()
    print("--- All Phase 2 Backend Tests Passed Successfully! ---")
