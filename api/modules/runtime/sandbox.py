import logging
import os
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger("runtime.sandbox")


def is_linux_sandbox_available() -> bool:
    """Returns True if running on Linux where kernel sandbox controls are supported."""
    return sys.platform == "linux"


def get_sandbox_mode() -> str:
    """Returns 'enforced' on Linux, or 'emulated' on Windows/macOS development environments."""
    return "enforced" if is_linux_sandbox_available() else "emulated"


def prepare_sandbox_temp_dir(
    temp_dir: Path,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    """
    Sets private permissions (0700) on the run temp directory.
    On Linux, if uid/gid are configured and running as root, changes ownership so the
    unprivileged agent user can access its private scratch directory.
    """
    try:
        # Enforce private directory permissions (owner-only rwx)
        os.chmod(temp_dir, 0o700)
    except Exception as e:
        logger.debug("Failed to set chmod 0700 on %s: %s", temp_dir, e)

    if sys.platform != "win32" and uid is not None and gid is not None:
        try:
            if os.geteuid() == 0:
                os.chown(temp_dir, uid, gid)
        except Exception as e:
            logger.warning("Failed to chown sandbox temp dir %s to %d:%d: %s", temp_dir, uid, gid, e)


def create_linux_preexec_fn(
    uid: int | None = None,
    gid: int | None = None,
    cpu_seconds: int = 120,
    as_bytes: int = 512 * 1024 * 1024,
    nproc: int = 32,
    nofile: int = 64,
    fsize_bytes: int = 10 * 1024 * 1024,
) -> Callable[[], None] | None:
    """
    Builds the preexec function executed in the child process on Linux before exec.
    Enforces POSIX rlimits (CPU, memory, max processes, open files, file size)
    and drops privileges to the unprivileged agent user (asaas-worker).
    """
    if sys.platform == "win32":
        return None

    def _preexec() -> None:
        try:
            import resource

            # 1. CPU Time Limit (seconds)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))

            # 2. Virtual Memory / Address Space Limit (bytes)
            if hasattr(resource, "RLIMIT_AS"):
                resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))

            # 3. Process count limit (prevent fork bombs)
            if hasattr(resource, "RLIMIT_NPROC"):
                resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))

            # 4. Open file descriptors limit
            if hasattr(resource, "RLIMIT_NOFILE"):
                resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))

            # 5. File size creation limit
            if hasattr(resource, "RLIMIT_FSIZE"):
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
        except Exception:
            pass

        # 6. Drop privileges to unprivileged agent user if running as root
        if uid is not None and gid is not None:
            try:
                if os.geteuid() == 0:
                    os.setgroups([])
                    os.setgid(gid)
                    os.setuid(uid)
            except Exception:
                pass

    return _preexec
