import asyncio
import collections
import logging
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from config import settings
from modules.runtime.runner import _terminate_process_tree

logger = logging.getLogger("runtime.service_supervisor")


def _is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _find_available_port(host: str, preferred_start: int) -> int:
    for candidate in range(preferred_start, preferred_start + 50):
        if _is_port_available(host, candidate):
            return candidate
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class ServiceSupervisor:
    """
    Supervises background daemon processes for Tier-2 Service Agents (e.g. Site DNA).
    - Spawns daemon bound strictly to 127.0.0.1 on configured private port.
    - Uses shell=False (argv list) and a minimal sanitized environment (zero platform secrets).
    - Drops privileges to settings.service_agent_uid on Linux when running as root/privileged.
    - Enforces --workers 1 so in-process run state and SSE queues remain consistent.
    - Monitors health endpoint until ready and terminates full process tree on shutdown.
    """

    def __init__(
        self,
        slug: str = "site-dna",
        host: str = "127.0.0.1",
        port: int | None = None,
        health_check_path: str = "/api/v1/health",
        command: list[str] | str | None = None,
        working_dir: Path | None = None,
    ) -> None:
        self.slug = slug
        self.host = host
        self.port = port or settings.site_dna_port
        self.health_check_path = health_check_path
        self.command = command
        self.working_dir = working_dir
        self._process: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._is_healthy: bool = False
        self._lock = asyncio.Lock()
        self._recent_output: collections.deque[str] = collections.deque(maxlen=40)

    def _drain_stream(self, stream: Any) -> None:
        """Continuously drain child stdout/stderr so OS pipe buffers never fill and deadlock."""
        try:
            for raw_line in iter(stream.readline, b""):
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._recent_output.append(line[:400])
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _resolve_agent_dir(self) -> Path:
        if self.working_dir:
            return self.working_dir
        return settings.resolved_agents_dir / self.slug

    def resolve_data_dir(self) -> Path:
        if settings.site_dna_data_dir:
            p = Path(settings.site_dna_data_dir).resolve()
        else:
            p = (self._resolve_agent_dir() / "runs").resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _build_argv(self, agent_dir: Path) -> list[str]:
        if isinstance(self.command, list):
            argv = list(self.command)
        elif isinstance(self.command, str) and self.command.strip():
            argv = shlex.split(self.command, posix=(sys.platform != "win32"))
            # If command uses `uv run uvicorn ...` and pre-built .venv exists, invoke .venv python directly
            if len(argv) >= 3 and argv[0] == "uv" and argv[1] == "run" and argv[2] == "uvicorn":
                venv_python = (
                    agent_dir / ".venv" / "Scripts" / "python.exe"
                    if sys.platform == "win32"
                    else agent_dir / ".venv" / "bin" / "python"
                )
                if venv_python.exists():
                    argv = [str(venv_python), "-m", *argv[2:]]
        else:
            # Prefer pre-built per-agent virtualenv python (never install at runtime)
            if sys.platform == "win32":
                venv_python = agent_dir / ".venv" / "Scripts" / "python.exe"
            else:
                venv_python = agent_dir / ".venv" / "bin" / "python"
            py_exe = str(venv_python) if venv_python.exists() else sys.executable
            argv = [
                py_exe,
                "-m",
                "uvicorn",
                "site_dna.api.main:app",
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--workers",
                "1",
            ]

        # Enforce single-worker invariant (F1 / O1)
        if "--workers" in argv:
            idx = argv.index("--workers")
            if idx + 1 < len(argv):
                try:
                    w_count = int(argv[idx + 1])
                    if w_count > 1:
                        logger.warning(
                            "Service agent %s configured with %d workers; clamping to 1 worker.",
                            self.slug,
                            w_count,
                        )
                        argv[idx + 1] = "1"
                except ValueError:
                    argv[idx + 1] = "1"
        return argv

    def _build_sanitized_env(self, agent_dir: Path) -> dict[str, str]:
        """Constructs minimal sanitized environment with ZERO platform or visitor secrets."""
        data_dir = self.resolve_data_dir()
        browsers_dir = agent_dir / ".playwright-browsers"

        env: dict[str, str] = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "APP_ENV": "production",
            "APP_HOST": self.host,
            "APP_PORT": str(self.port),
            "PLATFORM_MANAGED_SERVICE": "1",
            "SITE_DNA_SERVICE_MODE": "true",
            "SITE_DNA_DATA_DIR": str(data_dir),
            "SITE_DNA_PORT": str(self.port),
            "PLATFORM_LLM_BASE_URL": settings.agent_loopback_base_url,
            "CRAWLER_RESPECT_ROBOTS": "true",
            "VISUAL_RESPECT_ROBOTS": "true",
            "VISUAL_ANALYSIS_CACHE_ENABLED": "false",
            "UX_ANALYSIS_CACHE_ENABLED": "false",
            "CONTENT_ANALYSIS_CACHE_ENABLED": "false",
            "TECHNICAL_SEO_CACHE_ENABLED": "false",
            "COMPETITOR_ANALYSIS_CACHE_ENABLED": "false",
            "SECURITY_ANALYSIS_CACHE_ENABLED": "false",
            "ACCESSIBILITY_CACHE_ENABLED": "false",
            "STRATEGIC_CACHE_ENABLED": "false",
            "COMPETITOR_DISCOVERY_ENABLED": "false",
            "DISCOVERY_API_ENABLED": "false",
            "VISUAL_API_ENABLED": "false",
            "VISUAL_ANALYSIS_API_ENABLED": "false",
            "UX_ANALYSIS_API_ENABLED": "false",
            "CONTENT_ANALYSIS_API_ENABLED": "false",
            "TECHNICAL_SEO_API_ENABLED": "false",
            "CREWAI_TELEMETRY_OPT_OUT": "true",
            "OTEL_SDK_DISABLED": "true",
            "VISUAL_CAPTURE_ENABLED": "true",
        }
        if browsers_dir.exists():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
        if os.environ.get("SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN"):
            env["SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN"] = os.environ["SITE_DNA_ALLOW_TEST_FIXTURE_ORIGIN"]

        # Preserve only OS-required runtime variables (never API keys or DB secrets)
        if sys.platform == "win32":
            for win_var in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "COMSPEC"):
                if win_var in os.environ:
                    env[win_var] = os.environ[win_var]
        else:
            for posix_var in ("HOME", "TMPDIR", "LANG", "LC_ALL"):
                if posix_var in os.environ:
                    env[posix_var] = os.environ[posix_var]

        return env

    @staticmethod
    def _is_valid_health_response(resp: httpx.Response) -> bool:
        if resp.status_code == 204:
            return True
        if resp.status_code != 200:
            return False
        ctype = (resp.headers.get("content-type") or "").lower()
        if "application/json" not in ctype:
            return False
        try:
            data = resp.json()
            return isinstance(data, dict)
        except Exception:
            return False

    async def ensure_running(self) -> bool:
        if self._process and self._process.poll() is None and self._is_healthy:
            return True
        return await self.start()

    async def start(self) -> bool:
        async with self._lock:
            if self._process and self._process.poll() is None:
                if self._is_healthy:
                    logger.info("Service %s is already running (PID %d)", self.slug, self._process.pid)
                    return True
                return await self._wait_for_health(timeout_seconds=15.0)

            # Avoid port collision with unrelated local services on the configured loopback port
            if not _is_port_available(self.host, self.port):
                fallback_port = _find_available_port(self.host, self.port + 1)
                logger.warning(
                    "Configured port %d for service %s is already in use by another process; "
                    "rebinding supervised service to %s:%d.",
                    self.port,
                    self.slug,
                    self.host,
                    fallback_port,
                )
                self.port = fallback_port

            agent_dir = self._resolve_agent_dir()
            src_root = agent_dir / "src"
            cwd = agent_dir if (agent_dir / "pyproject.toml").exists() else (src_root if src_root.exists() else agent_dir)
            argv = self._build_argv(agent_dir)
            env = self._build_sanitized_env(agent_dir)

            # Ensure src/ is importable if not installed editable
            if (agent_dir / "src" / "site_dna").exists():
                env["PYTHONPATH"] = str(agent_dir / "src")
            elif (agent_dir / "src" / "src" / "site_dna").exists():
                env["PYTHONPATH"] = str(agent_dir / "src" / "src")

            popen_kwargs: dict[str, Any] = {
                "cwd": str(cwd) if cwd.exists() else None,
                "env": env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform != "win32":
                popen_kwargs["start_new_session"] = True
                if settings.service_agent_uid is not None and os.geteuid() == 0:
                    uid = settings.service_agent_uid
                    gid = settings.service_agent_gid if settings.service_agent_gid is not None else uid

                    def _drop_privs():
                        os.setgid(gid)
                        os.setuid(uid)

                    popen_kwargs["preexec_fn"] = _drop_privs
            else:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            logger.info("Starting supervised service %s on %s:%d...", self.slug, self.host, self.port)
            try:
                self._recent_output.clear()
                self._process = subprocess.Popen(argv, **popen_kwargs)
                self._started_at = time.time()
                if self._process.stdout is not None:
                    threading.Thread(
                        target=self._drain_stream,
                        args=(self._process.stdout,),
                        name=f"drain-{self.slug}",
                        daemon=True,
                    ).start()
                logger.info("Spawned service process %s with PID %d", self.slug, self._process.pid)
            except Exception as e:
                logger.error("Failed to spawn service %s: %s", self.slug, e)
                return False

            return await self._wait_for_health(timeout_seconds=25.0)

    async def _wait_for_health(self, timeout_seconds: float = 25.0) -> bool:
        start_time = time.time()
        url = f"{self.base_url}{self.health_check_path}"
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.time() - start_time < timeout_seconds:
                if self._process and self._process.poll() is not None:
                    code = self._process.poll()
                    tail = " | ".join(list(self._recent_output)[-10:])
                    logger.error("Service process %s exited prematurely with code %s: %s", self.slug, code, tail[:500])
                    self._is_healthy = False
                    return False

                try:
                    resp = await client.get(url)
                    if self._is_valid_health_response(resp):
                        self._is_healthy = True
                        logger.info("Service %s is healthy on %s (took %.2fs)", self.slug, url, time.time() - start_time)
                        return True
                except Exception:
                    pass

                await asyncio.sleep(0.5)

        logger.warning("Service %s health check timed out after %.1fs", self.slug, timeout_seconds)
        self._is_healthy = False
        return False

    async def stop(self) -> None:
        async with self._lock:
            if not self._process or self._process.poll() is not None:
                self._process = None
                self._is_healthy = False
                return

            pid = self._process.pid
            logger.info("Stopping supervised service %s (PID %d)...", self.slug, pid)
            try:
                await _terminate_process_tree(self._process)
            except Exception as e:
                logger.warning("Error terminating process tree for %s: %s", self.slug, e)

            self._process = None
            self._is_healthy = False

    async def check_health(self) -> bool:
        if not self._process or self._process.poll() is not None:
            self._is_healthy = False
            return False

        url = f"{self.base_url}{self.health_check_path}"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
                self._is_healthy = self._is_valid_health_response(resp)
        except Exception:
            self._is_healthy = False

        return self._is_healthy

    def get_status(self) -> dict[str, Any]:
        is_running = self._process is not None and self._process.poll() is None
        pid = self._process.pid if is_running else None
        uptime = time.time() - self._started_at if (is_running and self._started_at) else 0.0
        return {
            "slug": self.slug,
            "is_running": is_running,
            "healthy": self._is_healthy,
            "pid": pid,
            "port": self.port,
            "uptime_seconds": round(uptime, 1),
        }


# Singleton supervisor for site-dna
site_dna_supervisor = ServiceSupervisor(slug="site-dna", port=settings.site_dna_port)
