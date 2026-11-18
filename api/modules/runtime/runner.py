import asyncio
import glob
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from config import settings
from .file_validator import sanitize_filename, verify_file_content
from .sandbox import create_linux_preexec_fn, prepare_sandbox_temp_dir
from .token_registry import run_token_registry

logger = logging.getLogger("runtime.runner")

ALLOWED_AGENT_EVENTS = {"status", "message_delta", "step", "result", "error"}
PLATFORM_ONLY_EVENTS = {"usage", "done"}


def cleanup_stale_run_dirs() -> int:
    """
    Startup sweep: cleans up any leftover asaas_run_* directories in temp storage.
    """
    temp_base = Path(tempfile.gettempdir())
    stale_dirs = list(temp_base.glob("asaas_run_*"))
    count = 0
    for d in stale_dirs:
        if d.is_dir():
            try:
                shutil.rmtree(d, ignore_errors=True)
                count += 1
            except Exception as e:
                logger.warning("Failed to remove stale run dir %s: %s", d, e)
    if count > 0:
        logger.info("Startup sweep cleaned up %d stale run directories", count)
    return count


async def _terminate_process_tree(proc: asyncio.subprocess.Process, timeout: float = 2.0) -> None:
    """
    Safely kills a subprocess and all of its child processes with zero orphans.
    """
    if proc.returncode is not None:
        return

    pid = proc.pid
    try:
        if sys.platform == "win32":
            # On Windows, use taskkill to terminate process and all child processes
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                )
            except Exception:
                proc.kill()
        else:
            # On POSIX, kill process group
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                os.killpg(pgid, signal.SIGKILL)
    except Exception as e:
        logger.debug("Process tree kill encountered: %s", e)
        try:
            proc.kill()
        except Exception:
            pass


class AgentRunner:
    """
    Executes an agent process in isolation using the jsonl-stdio@1 protocol.
    """

    def __init__(
        self,
        manifest_data: dict[str, Any],
        agent_dir: Path,
        provider: str,
        model: str,
        visitor_key: str,
    ) -> None:
        self.manifest = manifest_data
        self.agent_dir = agent_dir
        self.provider = provider
        self.model = model
        self.visitor_key = visitor_key
        self.slug = manifest_data["slug"]

        # Calculate effective limits: min(manifest, platform ceiling)
        manifest_limits = manifest_data.get("limits", {})
        self.max_steps = min(
            manifest_limits.get("max_steps", 8),
            settings.platform_max_steps,
        )
        self.timeout_seconds = min(
            manifest_limits.get("timeout_seconds", 120),
            settings.platform_max_timeout_seconds,
        )
        self.max_input_chars = min(
            manifest_limits.get("max_input_chars", 8000),
            settings.platform_max_input_chars,
        )
        self.max_output_tokens = min(
            manifest_limits.get("max_output_tokens", 2000),
            settings.platform_max_output_tokens,
        )

        uploads_cfg = manifest_limits.get("uploads", {})
        self.max_upload_files = min(
            uploads_cfg.get("max_files", 1),
            settings.platform_max_upload_files,
        )
        self.max_upload_mb = min(
            uploads_cfg.get("max_mb", 5),
            settings.platform_max_upload_mb,
        )
        self.allowed_mime_types = uploads_cfg.get("types", [])

    def _resolve_python_executable(self) -> str:
        """Finds agent's pre-built virtualenv python, or falls back to sys.executable."""
        if sys.platform == "win32":
            venv_python = self.agent_dir / ".venv" / "Scripts" / "python.exe"
        else:
            venv_python = self.agent_dir / ".venv" / "bin" / "python"

        if venv_python.exists() and os.access(str(venv_python), os.X_OK):
            return str(venv_python)
        return sys.executable

    def _resolve_entrypoint(self) -> Path:
        """Resolves the script entrypoint relative to agent directory."""
        entrypoint_rel = self.manifest.get("runtime", {}).get("entrypoint", "src/main.py")
        p = self.agent_dir / entrypoint_rel
        if not p.exists():
            # Check directly in agent_dir
            p2 = self.agent_dir / "main.py"
            if p2.exists():
                return p2
        return p

    def _build_sanitized_env(self, temp_dir: Path) -> dict[str, str]:
        """
        Builds a strictly isolated environment containing ZERO server secrets or platform vars.
        """
        clean_env: dict[str, str] = {
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
        }

        # Pass essential system paths so python can load core DLLs / libc
        if sys.platform == "win32":
            clean_env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
            clean_env["COMSPEC"] = os.environ.get("COMSPEC", r"C:\Windows\system32\cmd.exe")
            # Minimal PATH
            clean_env["PATH"] = f"{temp_dir};{os.environ.get('SYSTEMROOT', r'C:\Windows')}\\system32"
        else:
            clean_env["PATH"] = "/usr/bin:/bin"
            clean_env["HOME"] = str(temp_dir)

        return clean_env

    async def run(
        self,
        run_id: str,
        message: str,
        parameters: dict[str, Any] | None = None,
        uploaded_files: list[tuple[str, str, bytes]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Executes the agent run and yields SSE-ready event dictionaries:
        - {"event": "status", "data": {...}}
        - {"event": "message_delta", "data": {...}}
        - {"event": "step", "data": {...}}
        - {"event": "result", "data": {...}}
        - {"event": "usage", "data": {...}}
        - {"event": "error", "data": {...}}
        - {"event": "done", "data": {}}
        """
        temp_dir = Path(tempfile.mkdtemp(prefix=f"asaas_run_{run_id}_"))
        proc: asyncio.subprocess.Process | None = None
        run_token: str | None = None

        try:
            # 1. Enforce input text limits
            if len(message) > self.max_input_chars:
                yield {
                    "event": "error",
                    "data": {
                        "code": "input_too_long",
                        "message": f"تجاوزت المدخلات الحد الأقصى ({self.max_input_chars} حرف).",
                    },
                }
                return

            # 2. Process and validate file uploads
            prepared_files: list[dict[str, Any]] = []
            if uploaded_files:
                if len(uploaded_files) > self.max_upload_files:
                    yield {
                        "event": "error",
                        "data": {
                            "code": "too_many_files",
                            "message": f"تجاوز عدد الملفات الحد المسموح به ({self.max_upload_files} ملف).",
                        },
                    }
                    return

                total_mb = sum(len(b) for _, _, b in uploaded_files) / (1024 * 1024)
                if total_mb > self.max_upload_mb:
                    yield {
                        "event": "error",
                        "data": {
                            "code": "file_too_large",
                            "message": f"إجمالي حجم الملفات ({total_mb:.1f}MB) تجاوز الحد المسموح ({self.max_upload_mb}MB).",
                        },
                    }
                    return

                uploads_dir = temp_dir / "uploads"
                uploads_dir.mkdir(parents=True, exist_ok=True)

                for original_name, claimed_mime, raw_bytes in uploaded_files:
                    try:
                        verified_mime = verify_file_content(raw_bytes, claimed_mime, self.allowed_mime_types)
                    except Exception as e:
                        err_msg = getattr(e, "message_ar", str(e))
                        yield {
                            "event": "error",
                            "data": {"code": "invalid_file", "message": err_msg},
                        }
                        return

                    safe_name = sanitize_filename(original_name)
                    dest_path = uploads_dir / safe_name
                    dest_path.write_bytes(raw_bytes)

                    prepared_files.append({
                        "filename": safe_name,
                        "path": str(dest_path),
                        "mime_type": verified_mime,
                        "size_bytes": len(raw_bytes),
                    })

            # 3. Register ephemeral run token mapped to visitor key
            run_token = await run_token_registry.create_token(
                run_id=run_id,
                provider=self.provider,
                model=self.model,
                visitor_key=self.visitor_key,
                max_output_tokens=self.max_output_tokens,
            )

            # 4. Resolve python executable & entrypoint
            python_bin = self._resolve_python_executable()
            entrypoint = self._resolve_entrypoint()
            if not entrypoint.exists():
                yield {
                    "event": "error",
                    "data": {
                        "code": "entrypoint_not_found",
                        "message": f"ملف تشغيل الوكيل غير موجود: {entrypoint.name}",
                    },
                }
                return

            # 5. Prepare sanitized environment & launch isolated process
            prepare_sandbox_temp_dir(temp_dir, settings.agent_uid, settings.agent_gid)
            clean_env = self._build_sanitized_env(temp_dir)

            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            start_new_session = (sys.platform != "win32")

            preexec_fn = None
            if sys.platform != "win32":
                preexec_fn = create_linux_preexec_fn(
                    uid=settings.agent_uid,
                    gid=settings.agent_gid,
                    cpu_seconds=min(self.timeout_seconds, settings.agent_rlimit_cpu_seconds),
                    as_bytes=settings.agent_rlimit_as_bytes,
                    nproc=settings.agent_rlimit_nproc,
                    nofile=settings.agent_rlimit_nofile,
                    fsize_bytes=settings.agent_rlimit_fsize_bytes,
                )

            cmd = [python_bin, str(entrypoint)]
            logger.info("Spawning agent process run_id=%s slug=%s", run_id, self.slug)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(temp_dir),
                env=clean_env,
                creationflags=creationflags,
                start_new_session=start_new_session,
                preexec_fn=preexec_fn,
            )

            # 6. Protocol Handshake: Send init & input messages over stdin
            init_msg = {
                "type": "init",
                "run_id": run_id,
                "model": self.model,
                "provider": self.provider,
                "llm_endpoint": settings.agent_loopback_base_url,
                "run_token": run_token,
                "limits": {
                    "max_steps": self.max_steps,
                    "timeout_seconds": self.timeout_seconds,
                    "max_output_tokens": self.max_output_tokens,
                },
            }

            input_msg = {
                "type": "input",
                "message": message,
                "parameters": parameters or {},
                "files": prepared_files,
            }

            init_payload = json.dumps(init_msg, ensure_ascii=False) + "\n"
            input_payload = json.dumps(input_msg, ensure_ascii=False) + "\n"

            if proc.stdin:
                proc.stdin.write(init_payload.encode("utf-8"))
                proc.stdin.write(input_payload.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            # 7. Asynchronous event reading loop
            step_count = 0
            total_output_bytes = 0
            received_terminal_event = False
            stderr_buffer: list[bytes] = []
            stderr_bytes_total = 0

            async def read_stderr():
                nonlocal stderr_bytes_total
                if not proc or not proc.stderr:
                    return
                while not proc.stderr.at_eof():
                    chunk = await proc.stderr.read(1024)
                    if not chunk:
                        break
                    if stderr_bytes_total < settings.agent_stderr_max_bytes:
                        stderr_buffer.append(chunk)
                        stderr_bytes_total += len(chunk)

            stderr_task = asyncio.create_task(read_stderr())

            deadline = time.time() + self.timeout_seconds

            while True:
                # Check for cancellation
                if cancel_event and cancel_event.is_set():
                    logger.info("Run cancelled by client run_id=%s", run_id)
                    yield {
                        "event": "error",
                        "data": {"code": "run_cancelled", "message": "تم إلغاء التجربة بنجاح."},
                    }
                    received_terminal_event = True
                    break

                # Check for timeout
                remaining_time = deadline - time.time()
                if remaining_time <= 0:
                    logger.warning("Run timed out run_id=%s after %ds", run_id, self.timeout_seconds)
                    yield {
                        "event": "error",
                        "data": {
                            "code": "timeout_exceeded",
                            "message": f"تجاوز الوكيل الحد الزمني الأقصى للتنفيذ ({self.timeout_seconds} ثانية).",
                        },
                    }
                    received_terminal_event = True
                    break

                if not proc.stdout:
                    break

                try:
                    read_task = asyncio.create_task(proc.stdout.readline())
                    done, _ = await asyncio.wait(
                        [read_task],
                        timeout=min(remaining_time, 1.0),
                    )
                    if not done:
                        read_task.cancel()
                        continue
                    line_bytes = read_task.result()
                except (ValueError, asyncio.LimitOverrunError):
                    logger.warning("Agent output line exceeded buffer limit run_id=%s", run_id)
                    yield {
                        "event": "error",
                        "data": {
                            "code": "output_size_exceeded",
                            "message": "تجاوزت مخرجات الوكيل الحجم الأقصى المسموح به.",
                        },
                    }
                    received_terminal_event = True
                    break
                except asyncio.CancelledError:
                    break

                if not line_bytes:
                    break  # Process closed stdout

                # Check per-line size limit
                if len(line_bytes) > settings.agent_output_line_max_bytes:
                    logger.warning("Agent output line exceeded max size run_id=%s", run_id)
                    yield {
                        "event": "error",
                        "data": {
                            "code": "output_size_exceeded",
                            "message": "تجاوزت مخرجات الوكيل الحجم الأقصى المسموح به.",
                        },
                    }
                    received_terminal_event = True
                    break

                # Check total output byte cap across the entire run
                total_output_bytes += len(line_bytes)
                if total_output_bytes > settings.agent_total_output_max_bytes:
                    logger.warning(
                        "Agent exceeded total output limit (%d > %d bytes) run_id=%s",
                        total_output_bytes,
                        settings.agent_total_output_max_bytes,
                        run_id,
                    )
                    yield {
                        "event": "error",
                        "data": {
                            "code": "total_output_limit_exceeded",
                            "message": "تجاوز إجمالي مخرجات الوكيل السقف الأقصى المسموح به للجلسة.",
                        },
                    }
                    received_terminal_event = True
                    break

                line_str = line_bytes.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    event_obj = json.loads(line_str)
                except Exception:
                    logger.warning("Malformed JSONL line from agent run_id=%s: %s", run_id, line_str[:100])
                    yield {
                        "event": "error",
                        "data": {
                            "code": "malformed_event",
                            "message": "أصدر الوكيل حدثاً غير صالح هيكلياً.",
                        },
                    }
                    received_terminal_event = True
                    break

                if not isinstance(event_obj, dict) or "event" not in event_obj:
                    yield {
                        "event": "error",
                        "data": {
                            "code": "malformed_event",
                            "message": "بيانات الحدث المرسل من الوكيل غير مطابقة للشكل المتوقع.",
                        },
                    }
                    received_terminal_event = True
                    break

                event_type = event_obj.get("event")
                event_data = event_obj.get("data")
                if not isinstance(event_data, dict):
                    event_data = {}

                # Security check: platform-only reserved events
                if event_type in PLATFORM_ONLY_EVENTS:
                    logger.warning("Agent attempted to emit reserved platform event '%s' run_id=%s", event_type, run_id)
                    yield {
                        "event": "error",
                        "data": {
                            "code": "forbidden_event_type",
                            "message": f"الحدث '{event_type}' محجوز للمنصة ولا يمكن إصداره من قبل الوكيل.",
                        },
                    }
                    received_terminal_event = True
                    break

                # Security check: event allowlist
                if event_type not in ALLOWED_AGENT_EVENTS:
                    logger.warning("Agent emitted unsupported event '%s' run_id=%s", event_type, run_id)
                    yield {
                        "event": "error",
                        "data": {
                            "code": "unsupported_event_type",
                            "message": f"نوع الحدث '{event_type}' غير مدعوم من قبل بروتوكول المنصة.",
                        },
                    }
                    received_terminal_event = True
                    break

                # Per-event payload schema and bounds checks
                if event_type == "status":
                    stage = str(event_data.get("stage", ""))
                    msg = str(event_data.get("message", ""))
                    if len(stage) > 100 or len(msg) > 2000:
                        yield {
                            "event": "error",
                            "data": {"code": "event_payload_too_large", "message": "حجم بيانات حدث الحالة تجاوز الحد المسموح."},
                        }
                        received_terminal_event = True
                        break
                elif event_type == "message_delta":
                    text = event_data.get("text", "")
                    if not isinstance(text, str) or len(text) > 32768:
                        yield {
                            "event": "error",
                            "data": {"code": "event_payload_too_large", "message": "حجم التحديث النصي تجاوز الحد المسموح."},
                        }
                        received_terminal_event = True
                        break
                elif event_type == "step":
                    step_count += 1
                    if step_count > self.max_steps:
                        logger.warning("Step limit exceeded run_id=%s", run_id)
                        yield {
                            "event": "error",
                            "data": {
                                "code": "step_limit_exceeded",
                                "message": f"تجاوز الوكيل عدد الخطوات المسموح به ({self.max_steps} خطوات).",
                            },
                        }
                        received_terminal_event = True
                        break
                    title = str(event_data.get("title", ""))
                    if len(title) > 500:
                        yield {
                            "event": "error",
                            "data": {"code": "event_payload_too_large", "message": "حجم عنوان الخطوة تجاوز الحد المسموح."},
                        }
                        received_terminal_event = True
                        break

                yield {"event": event_type, "data": event_data}

                if event_type in ("result", "error"):
                    received_terminal_event = True
                    break

            # If process terminated without emitting result or error terminal event
            if not received_terminal_event and proc:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    pass
                exit_code = proc.returncode if proc.returncode is not None else -1
                logger.warning("Agent process exited without result or error run_id=%s exit_code=%s", run_id, exit_code)
                yield {
                    "event": "error",
                    "data": {
                        "code": "agent_exited_without_result",
                        "message": f"انتهت عملية الوكيل دون إصدار نتيجة نهائية (رمز الخروج: {exit_code}).",
                        "exit_code": exit_code,
                    },
                }

        finally:
            # 8. Complete Cleanup in finally block:
            # Terminate process tree immediately
            if proc:
                await _terminate_process_tree(proc)

            if stderr_task and not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except (asyncio.CancelledError, Exception):
                    pass

            # Revoke token immediately
            if run_token:
                await run_token_registry.revoke_token(run_token)
            await run_token_registry.revoke_by_run_id(run_id)

            # Emit final usage event
            final_usage = await run_token_registry.get_accumulated_usage(run_id)
            yield {
                "event": "usage",
                "data": final_usage.model_dump(),
            }

            # Emit done event
            yield {"event": "done", "data": {}}

            # Remove private temp directory completely
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug("Removed temp dir for run_id=%s", run_id)
