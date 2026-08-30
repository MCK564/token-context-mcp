"""Keep the local registry and index snapshots readable by their owner only.

An index stores verbatim source bodies, so it must never be easier to read
than the repository it was built from. Two platform defaults break that on
their own:

- on POSIX the process umask decides the mode of a freshly created file, and
  the common default (0022) publishes every snapshot to all accounts on the
  host;
- on Windows the config directory inherits whatever ACL the user profile
  carries, which on a shared or tooling-managed machine can include extra
  groups.

Write-time hardening therefore sets the POSIX mode explicitly instead of
trusting the umask. Resetting a Windows ACL needs an external tool and is a
deliberate admin action, so it lives in ``harden_tree`` behind the
``token-context harden`` command rather than in the indexing hot path.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

# The directory this tool creates for itself, and therefore the only one it
# will restrict wholesale.
OWNED_DIRECTORY_NAME = "token-context-mcp"

SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

# Well-known SIDs kept alongside the owner: the machine itself and local
# administrators. Both can read the file regardless of the ACL, so denying
# them buys nothing and breaks backup and repair tooling.
_WINDOWS_ALLOWED_SIDS = ("S-1-5-18", "S-1-5-32-544")


def uses_posix_modes() -> bool:
    return os.name == "posix"


def describe_mode(path: Path) -> str | None:
    """Return the POSIX mode as ``0644``, or None where modes do not apply."""
    if not uses_posix_modes():
        return None
    try:
        return format(stat.S_IMODE(path.stat().st_mode), "04o")
    except OSError:
        return None


def secure_directory(path: Path) -> Path:
    """Create ``path`` if needed and make it owner-only.

    Parents are created with the default mode: ``~/.config`` is shared with
    every other tool on the machine and is not ours to restrict.
    """
    path.mkdir(parents=True, exist_ok=True)
    _chmod(path, PRIVATE_DIR_MODE)
    return path


def secure_file(path: Path) -> Path:
    """Make a single file owner-only, ignoring one that is already gone."""
    _chmod(path, PRIVATE_FILE_MODE)
    return path


def secure_sqlite_artifacts(database: Path) -> None:
    """Harden a snapshot and the WAL sidecars SQLite creates next to it."""
    secure_file(database)
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        secure_file(database.parent / f"{database.name}{suffix}")


def harden_registry(config_path: Path, *, check_only: bool = False) -> dict[str, object]:
    """Restrict the registry and every snapshot built from it to their owner.

    ``TOKEN_CONTEXT_CONFIG`` can point the registry at a path chosen for other
    reasons, so the parent directory is only restricted when it is the one
    this tool creates. A home directory is not ours to chmod.
    """
    parent = config_path.parent
    report: dict[str, object] = {"platform": _platform(), "config": str(config_path)}
    if parent.name == OWNED_DIRECTORY_NAME:
        report["scope"] = str(parent)
        report["result"] = harden_tree(parent, check_only=check_only)
        return report
    report["scope"] = "registry file and index directory only"
    report["parent_directory"] = {"path": str(parent), "mode": describe_mode(parent), "status": "not_owned"}
    report["result"] = {
        "registry": _harden_single_file(config_path, check_only=check_only),
        "indexes": harden_tree(parent / "indexes", check_only=check_only),
    }
    return report


def harden_tree(directory: Path, *, check_only: bool = False) -> dict[str, object]:
    """Report, and optionally repair, the permissions of an existing tree."""
    if not directory.exists():
        return {"platform": _platform(), "path": str(directory), "status": "missing"}
    if uses_posix_modes():
        return _harden_posix_tree(directory, check_only=check_only)
    return _harden_windows_tree(directory, check_only=check_only)


def _platform() -> str:
    return "posix" if uses_posix_modes() else "windows"


def _harden_posix_tree(directory: Path, *, check_only: bool) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    compliant = 0
    for path, wanted in _walk_with_intent(directory):
        current = describe_mode(path)
        if current == format(wanted, "04o"):
            compliant += 1
            continue
        if not check_only:
            _chmod(path, wanted)
        findings.append(
            {
                "path": str(path),
                "mode": current or "unknown",
                "expected": format(wanted, "04o"),
                "action": "reported" if check_only else "changed",
            }
        )
    return {
        "platform": "posix",
        "path": str(directory),
        "status": "compliant" if not findings else ("needs_repair" if check_only else "repaired"),
        "already_compliant": compliant,
        "findings": findings,
    }


def _harden_windows_tree(directory: Path, *, check_only: bool) -> dict[str, object]:
    owner_sid = _current_user_sid()
    allowed = {sid.upper() for sid in (owner_sid, *_WINDOWS_ALLOWED_SIDS) if sid}
    before = _windows_principals(directory)
    extra = [name for name, sid in before if sid.upper() not in allowed]
    report: dict[str, object] = {
        "platform": "windows",
        "path": str(directory),
        "principals": [name for name, _ in before],
        "unexpected_principals": extra,
    }
    if not extra:
        report["status"] = "compliant"
        return report
    if check_only:
        report["status"] = "needs_repair"
        return report
    if not owner_sid:
        report["status"] = "needs_repair"
        report["error"] = "could not resolve the current account SID; run icacls manually"
        return report
    grants = [f"*{sid}:(OI)(CI)(F)" for sid in (owner_sid, *_WINDOWS_ALLOWED_SIDS)]
    _run(["icacls", str(directory), "/inheritance:r", "/grant:r", *grants])
    # Children keep their own inherited copies of the old ACL until they are
    # told to re-inherit from the directory we just rewrote.
    _run(["icacls", str(directory), "/reset", "/T", "/C", "/Q"])
    report["status"] = "repaired"
    report["principals_after"] = [name for name, _ in _windows_principals(directory)]
    return report


def _harden_single_file(path: Path, *, check_only: bool) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    if not uses_posix_modes():
        # A lone file inherits the ACL of whatever directory the operator
        # pointed the registry at; rewriting that ACL is their call.
        return {"path": str(path), "status": "inherits_directory_acl"}
    current = describe_mode(path)
    expected = format(PRIVATE_FILE_MODE, "04o")
    if current == expected:
        return {"path": str(path), "mode": current, "status": "compliant"}
    if not check_only:
        _chmod(path, PRIVATE_FILE_MODE)
    return {
        "path": str(path),
        "mode": current or "unknown",
        "expected": expected,
        "status": "needs_repair" if check_only else "repaired",
    }


def _walk_with_intent(directory: Path) -> Iterator[tuple[Path, int]]:
    yield directory, PRIVATE_DIR_MODE
    for current_root, directories, filenames in os.walk(directory):
        root = Path(current_root)
        for name in directories:
            yield root / name, PRIVATE_DIR_MODE
        for name in filenames:
            yield root / name, PRIVATE_FILE_MODE


def _chmod(path: Path, mode: int) -> None:
    if not uses_posix_modes():
        return
    try:
        os.chmod(path, mode)
    except OSError:
        # A snapshot that cannot be hardened is still a usable snapshot; the
        # harden command reports the mode so the operator can see the gap.
        return


def _current_user_sid() -> str:
    result = _run(["whoami", "/user", "/fo", "csv", "/nh"])
    if not result:
        return ""
    fields = [field.strip().strip('"') for field in result.strip().splitlines()[-1].split(",")]
    for field in fields:
        if field.upper().startswith("S-1-"):
            return field
    return ""


def _windows_principals(directory: Path) -> list[tuple[str, str]]:
    """Return (display name, SID) for every principal in the directory ACL."""
    listing = _run(["icacls", str(directory)])
    if not listing:
        return []
    principals: list[tuple[str, str]] = []
    prefix = str(directory)
    for line in listing.splitlines():
        entry = line[len(prefix) :] if line.startswith(prefix) else line
        entry = entry.strip()
        if not entry or ":" not in entry or entry.lower().startswith("successfully processed"):
            continue
        name = entry.rsplit(":", 1)[0].strip()
        if name:
            principals.append((name, _resolve_sid(name)))
    return principals


def _resolve_sid(account: str) -> str:
    if account.startswith("*S-1-"):
        return account[1:]
    script = (
        f'([System.Security.Principal.NTAccount]"{account}")'
        ".Translate([System.Security.Principal.SecurityIdentifier]).Value"
    )
    resolved = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    return (resolved or "").strip()


def _run(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 and not completed.stdout:
        return None
    return completed.stdout
