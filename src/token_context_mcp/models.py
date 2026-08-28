from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Freshness = Literal["fresh", "pending", "stale", "unknown"]
EdgeStatus = Literal["resolved", "ambiguous", "unresolved"]


@dataclass(frozen=True)
class RepositoryConfig:
    repo_id: str
    root: Path
    allow_symlinks: bool = False
    max_file_bytes: int = 2_000_000
    max_files: int = 25_000


@dataclass(frozen=True)
class ServerConfig:
    max_request_bytes: int = 1_048_576
    max_result_tokens: int = 8_192
    max_graph_nodes: int = 100
    max_symbol_results: int = 20
    network_policy: str = "declared-deny-not-enforced"


@dataclass(frozen=True)
class AppConfig:
    repositories: dict[str, RepositoryConfig]
    server: ServerConfig = field(default_factory=ServerConfig)
    budget_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class FileRecord:
    path: str
    sha256: str
    size: int
    mtime_ns: int
    language: str | None
    parse_status: str
    warnings: list[str]


@dataclass(frozen=True)
class SymbolRecord:
    symbol_id: str
    path: str
    name: str
    qualified_name: str
    kind: str
    signature: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    body_start_byte: int | None
    body_end_byte: int | None
    is_private: bool
    roles: list[str] = field(default_factory=list)
    role_evidence: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeRecord:
    source_symbol_id: str
    target_symbol_id: str | None
    target_name: str
    edge_kind: str
    status: EdgeStatus
    backend: str
    confidence: float | None
    source_path: str
    source_line: int
    evidence: list[str]


@dataclass(frozen=True)
class Evidence:
    path: str
    start_line: int
    end_line: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        # The full digest remains in the index and is used for local freshness
        # checks.  The wire contract only needs a compact change-detection
        # fingerprint, which keeps repeated evidence affordable in context.
        value["sha256"] = self.sha256[:12]
        return value


def symbol_as_dict(symbol: SymbolRecord) -> dict[str, Any]:
    value = asdict(symbol)
    # Byte offsets are internal source-slicing coordinates.  Line spans are
    # sufficient for callers and avoid leaking implementation-only fields into
    # every symbol packet.
    for field_name in ("start_byte", "end_byte", "body_start_byte", "body_end_byte"):
        value.pop(field_name, None)
    return value


def edge_as_dict(edge: EdgeRecord) -> dict[str, Any]:
    return asdict(edge)
