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
        return asdict(self)


def symbol_as_dict(symbol: SymbolRecord) -> dict[str, Any]:
    return asdict(symbol)


def edge_as_dict(edge: EdgeRecord) -> dict[str, Any]:
    return asdict(edge)
