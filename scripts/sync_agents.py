#!/usr/bin/env python3
"""
Agent Code Sync Script (scripts/sync_agents.py)
Synchronizes both Tier-1 (job) and Tier-2 (service) agent repositories at pinned
40-character commit SHAs, installs locked dependencies at sync-time only, installs
Playwright Chromium into an agent-owned directory when needed, and builds standalone
sub-app frontends with the manifest's mount_path and api_base.
Conforms strictly to Decisions D6 and D8.
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_agents")


def find_agent_manifests(agents_base: Path) -> list[tuple[Path, dict]]:
    """Discovers all agent manifests under the agents base directory."""
    manifests = []
    for p in list(agents_base.glob("*/agent.manifest.json")) + list(agents_base.glob("*/manifest.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            manifests.append((p.parent, data))
        except Exception as e:
            logger.error("Failed to read manifest at %s: %s", p, e)
    return manifests


def _find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    for cand in (
        Path.home() / ".local" / "bin" / "uv.exe",
        Path.home() / ".local" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
    ):
        if cand.exists():
            return str(cand)
    return None


def _sync_git_checkout(slug: str, repo_url: str, pinned_ref: str, target_dir: Path) -> bool:
    if not repo_url:
        logger.error("Agent '%s' is missing github.url in manifest", slug)
        return False

    try:
        git_marker = target_dir / ".git"
        if git_marker.exists():
            logger.info("Fetching latest objects for '%s' in %s", slug, target_dir)
            try:
                subprocess.check_call(
                    ["git", "-C", str(target_dir), "fetch", "--all", "--tags"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            subprocess.check_call(
                ["git", "-C", str(target_dir), "checkout", pinned_ref],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            target_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cloning '%s' from %s into %s", slug, repo_url, target_dir)
            subprocess.check_call(
                ["git", "clone", repo_url, str(target_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.check_call(
                ["git", "-C", str(target_dir), "checkout", pinned_ref],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        head_sha = subprocess.check_output(
            ["git", "-C", str(target_dir), "rev-parse", "HEAD"],
            text=True,
        ).strip().lower()

        if head_sha != pinned_ref:
            logger.error(
                "SHA Mismatch for '%s': HEAD (%s) != pinned_ref (%s). Failing sync strictly.",
                slug,
                head_sha,
                pinned_ref,
            )
            return False
        logger.info("Verified commit SHA match for '%s': %s", slug, head_sha)
        return True
    except Exception as e:
        logger.error("Git operation failed for agent '%s': %s", slug, e)
        return False


def _sync_service_agent(agent_dir: Path, manifest: dict, skip_git: bool) -> bool:
    """Sync a Tier-2 managed service agent (uv.lock + Playwright + standalone frontend)."""
    slug = manifest.get("slug", agent_dir.name)
    github_cfg = manifest.get("github", {})
    pinned_ref = str(github_cfg.get("pinned_ref", "")).strip().lower()
    repo_url = str(github_cfg.get("url", "")).strip()
    runtime_cfg = manifest.get("runtime", {})
    py_ver = str(runtime_cfg.get("python", "3.11")).strip()
    playground_cfg = manifest.get("playground", {})

    # Determine project root: either agents/<slug>/repo (cloned) or agents/<slug> (local integrated tree)
    project_root = agent_dir
    if not skip_git:
        repo_dir = agent_dir / "repo"
        if not _sync_git_checkout(slug, repo_url, pinned_ref, repo_dir):
            return False
        project_root = repo_dir
    else:
        logger.info("Skipping remote git operations for service agent '%s' (--skip-git enabled)", slug)

    uv_lock = project_root / "uv.lock"
    if not uv_lock.exists():
        logger.error("Service agent '%s' is missing uv.lock at %s", slug, uv_lock)
        return False

    uv_bin = _find_uv()
    if not uv_bin:
        logger.error("uv executable not found on PATH; required to sync service agent '%s'", slug)
        return False

    venv_dir = project_root / ".venv"
    try:
        logger.info("Running uv sync --frozen --python %s for '%s'...", py_ver, slug)
        subprocess.check_call(
            [uv_bin, "sync", "--frozen", "--python", py_ver],
            cwd=str(project_root),
        )

        # Install Playwright Chromium into an agent-owned directory if playwright is in lockfile
        lock_text = uv_lock.read_text(encoding="utf-8", errors="ignore")
        if 'name = "playwright"' in lock_text:
            browsers_dir = project_root / ".playwright-browsers"
            browsers_dir.mkdir(parents=True, exist_ok=True)
            pw_env = os.environ.copy()
            pw_env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
            logger.info("Installing Playwright Chromium into %s for '%s'...", browsers_dir, slug)
            subprocess.check_call(
                [uv_bin, "run", "playwright", "install", "chromium"],
                cwd=str(project_root),
                env=pw_env,
            )
    except Exception as e:
        logger.error("Failed to sync Python/Playwright environment for service agent '%s': %s", slug, e)
        if venv_dir.exists():
            shutil.rmtree(venv_dir, ignore_errors=True)
        return False

    # Build standalone frontend sub-app if present
    frontend_dir = project_root / "frontend"
    if (frontend_dir / "package.json").exists():
        npm_bin = shutil.which("npm") or ("npm.cmd" if sys.platform == "win32" else "npm")
        mount_path = str(playground_cfg.get("mount_path") or f"/agents/{slug}/app/")
        api_base = str(playground_cfg.get("api_base") or f"/agents-api/{slug}/api/v1")
        build_env = os.environ.copy()
        build_env["VITE_BASE_PATH"] = mount_path
        build_env["VITE_API_BASE"] = api_base
        try:
            logger.info(
                "Building frontend for '%s' (base=%s, api=%s)...",
                slug,
                mount_path,
                api_base,
            )
            subprocess.check_call([npm_bin, "ci"], cwd=str(frontend_dir), env=build_env)
            subprocess.check_call([npm_bin, "run", "build"], cwd=str(frontend_dir), env=build_env)
        except Exception as e:
            logger.error("Failed to build frontend for service agent '%s': %s", slug, e)
            return False

    logger.info("Successfully synced service agent '%s' at %s", slug, pinned_ref)
    return True


def sync_agent(agent_dir: Path, manifest: dict, skip_git: bool = False) -> bool:
    """
    Syncs a single agent repository (Tier-1 job or Tier-2 service):
    1. Verifies 40-char pinned_ref SHA and git checkout (unless --skip-git).
    2. Verifies dependency lockfile presence.
    3. Builds per-agent virtualenv (and Playwright/frontend for service agents) at sync-time only.
    4. Cleans up on failure so a half-installed agent is never left in a ready state.
    """
    slug = manifest.get("slug", agent_dir.name)
    logger.info("Starting sync for agent '%s' in %s", slug, agent_dir)

    github_cfg = manifest.get("github", {})
    pinned_ref = str(github_cfg.get("pinned_ref", "")).strip().lower()
    repo_url = str(github_cfg.get("url", "")).strip()

    if not pinned_ref or len(pinned_ref) != 40:
        logger.error("Agent '%s' has invalid or missing 40-char pinned_ref SHA: '%s'", slug, pinned_ref)
        return False

    runtime_kind = str(manifest.get("runtime", {}).get("kind", "job")).strip().lower()
    if runtime_kind == "service":
        return _sync_service_agent(agent_dir, manifest, skip_git=skip_git)

    src_dir = agent_dir / "src"

    # 1. Git checkout / clone verification
    if not skip_git:
        if not _sync_git_checkout(slug, repo_url, pinned_ref, src_dir):
            return False
    else:
        logger.info("Skipping remote git operations for '%s' (--skip-git enabled)", slug)
        if not src_dir.exists():
            src_dir.mkdir(parents=True, exist_ok=True)

    # 2. Check lockfile presence in pinned src/ directory (or fallback to agent_dir)
    lockfile_candidates = ["requirements.lock", "requirements.txt", "uv.lock"]
    found_lockfile: Path | None = None
    for cand in lockfile_candidates:
        cand_path = src_dir / cand
        if cand_path.exists():
            found_lockfile = cand_path
            break
        cand_fallback = agent_dir / cand
        if cand_fallback.exists():
            found_lockfile = cand_fallback
            break

    if not found_lockfile:
        logger.error(
            "Agent '%s' is missing a dependency lockfile (checked %s). Failing sync strictly.",
            slug,
            lockfile_candidates,
        )
        return False

    logger.info("Found lockfile for '%s': %s", slug, found_lockfile.name)

    # 3. Build per-agent virtualenv (at sync-time only)
    venv_dir = agent_dir / ".venv"
    try:
        if not venv_dir.exists():
            logger.info("Creating isolated virtualenv for '%s' at %s", slug, venv_dir)
            subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])

        if sys.platform == "win32":
            pip_bin = venv_dir / "Scripts" / "pip.exe"
            py_bin = venv_dir / "Scripts" / "python.exe"
        else:
            pip_bin = venv_dir / "bin" / "pip"
            py_bin = venv_dir / "bin" / "python"

        if not pip_bin.exists():
            logger.error("pip not found in venv for '%s' at %s", slug, pip_bin)
            shutil.rmtree(venv_dir, ignore_errors=True)
            return False

        pip_cmd = [str(py_bin), "-m", "pip", "install", "-r", str(found_lockfile)]
        try:
            lockfile_content = found_lockfile.read_text(encoding="utf-8", errors="ignore")
            if "--hash=" in lockfile_content:
                pip_cmd.append("--require-hashes")
                logger.info("Enforcing --require-hashes for '%s'", slug)
        except Exception:
            pass

        logger.info("Installing lockfile dependencies for '%s'...", slug)
        subprocess.check_call(pip_cmd, stdout=subprocess.DEVNULL)

    except Exception as e:
        logger.error("Failed to build virtualenv or install dependencies for '%s': %s", slug, e)
        if venv_dir.exists():
            shutil.rmtree(venv_dir, ignore_errors=True)
        return False

    logger.info("Successfully synced agent '%s' at %s", slug, pinned_ref)
    return True


def main():
    parser = argparse.ArgumentParser(description="Synchronize ASAAS agent repositories and build virtualenvs.")
    parser.add_argument("--agents-dir", default="../agents", help="Path to agents directory")
    parser.add_argument("--skip-git", action="store_true", help="Skip remote git operations for local samples")
    parser.add_argument("--slug", default=None, help="Optional single agent slug to sync")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent / args.agents_dir
    if not base.exists():
        base = Path(args.agents_dir).resolve()

    if not base.exists():
        logger.error("Agents directory not found: %s", base)
        sys.exit(1)

    manifests = find_agent_manifests(base)
    if args.slug:
        manifests = [(d, m) for d, m in manifests if m.get("slug") == args.slug]
    if not manifests:
        logger.warning("No matching agent manifests found in %s", base)
        sys.exit(0)

    success_count = 0
    fail_count = 0

    for agent_dir, manifest in manifests:
        is_sample = manifest.get("is_sample", False)
        skip = args.skip_git or is_sample
        ok = sync_agent(agent_dir, manifest, skip_git=skip)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    logger.info("Agent sync finished: %d succeeded, %d failed", success_count, fail_count)
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
