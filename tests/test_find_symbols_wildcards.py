from __future__ import annotations

from pathlib import Path
import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.service import RetrievalError, RetrievalService


@pytest.fixture()
def symbols_repo_config(tmp_path: Path) -> Path:
    root = tmp_path / "symbols-repo"
    root.mkdir()
    (root / "classes.py").write_text(
        """
class AuthService:
    def login(self, user: str) -> bool:
        return True

    def logout(self) -> None:
        pass

class PaymentService:
    def process_payment(self) -> None:
        pass

def auth_service_helper() -> str:
    return "helper"

def Service() -> None:
    pass
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-repo", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-repo": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def _service(config_path: Path) -> RetrievalService:
    return RetrievalService(load_config(config_path), config_path)


def test_find_symbols_wildcards(symbols_repo_config: Path) -> None:
    service = _service(symbols_repo_config)

    # Wildcard *
    res = service.find_symbols("test-repo", pattern="*Service*")
    names = [s["name"] for s in res["data"]["symbols"]]
    assert "AuthService" in names
    assert "PaymentService" in names
    assert "auth_service_helper" in names
    assert "Service" in names

    # Wildcard ?
    res_q = service.find_symbols("test-repo", pattern="log??")
    names_q = [s["name"] for s in res_q["data"]["symbols"]]
    assert names_q == ["login"]

    # Star matching all
    res_all = service.find_symbols("test-repo", pattern="*")
    assert len(res_all["data"]["symbols"]) >= 6


def test_find_symbols_priority_sorting(symbols_repo_config: Path) -> None:
    service = _service(symbols_repo_config)
    res = service.find_symbols("test-repo", pattern="Service")
    names = [s["name"] for s in res["data"]["symbols"]]
    # Exact match "Service" must be first
    assert names[0] == "Service"
    # Followed by other matches
    assert "AuthService" in names
    assert "PaymentService" in names


def test_find_symbols_kind_filtering(symbols_repo_config: Path) -> None:
    service = _service(symbols_repo_config)

    # kind="class"
    classes = service.find_symbols("test-repo", pattern="*Service*", kind="class")
    class_names = [s["name"] for s in classes["data"]["symbols"]]
    assert set(class_names) == {"AuthService", "PaymentService"}

    # kind="method"
    methods = service.find_symbols("test-repo", pattern="*", kind="method")
    method_names = [s["name"] for s in methods["data"]["symbols"]]
    assert "login" in method_names
    assert "logout" in method_names
    assert "process_payment" in method_names
    assert "auth_service_helper" not in method_names
    assert "AuthService" not in method_names

    # kind="function"
    funcs = service.find_symbols("test-repo", pattern="*", kind="function")
    func_names = [s["name"] for s in funcs["data"]["symbols"]]
    assert "auth_service_helper" in func_names
    assert "Service" in func_names
    assert "AuthService" not in func_names

    # invalid kind
    with pytest.raises(RetrievalError, match="kind must be function, class, method, or interface"):
        service.find_symbols("test-repo", pattern="Service", kind="unknown_kind")


def test_find_symbols_truncation_and_more_matches(tmp_path: Path) -> None:
    root = tmp_path / "trunc-repo"
    root.mkdir()
    (root / "models.py").write_text(
        """
class Alpha: pass
class Beta: pass
class Gamma: pass
class Delta: pass
class Epsilon: pass
""",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_models.py").write_text(
        """
class TestAlpha: pass
class TestBeta: pass
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-repo", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-repo": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    service = _service(config_path)

    res = service.find_symbols("test-repo", pattern="*", kind="class", limit=3)
    data = res["data"]
    assert len(data["symbols"]) == 3
    assert data["total_matches"] == 7
    assert data["omitted_count"] == 4
    assert res["truncated"] is True
    assert "more_matches_available" in res["warnings"]
    assert "symbol_limit_capped_by_server" not in res["warnings"]


def test_find_symbols_tie_breaking_order(tmp_path: Path) -> None:
    root = tmp_path / "sort-repo"
    root.mkdir()
    (root / "service.py").write_text(
        """
class service: pass
class Service: pass
class ServiceManager: pass
""",
        encoding="utf-8",
    )
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_service.py").write_text(
        """
class ServiceInTest: pass
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-repo", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-repo": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    service = _service(config_path)

    res = service.find_symbols("test-repo", pattern="Service*")
    names = [s["name"] for s in res["data"]["symbols"]]
    # Exact case-sensitive "Service" before case-insensitive "service"
    assert names.index("Service") < names.index("service")
    # Non-test paths before test paths
    assert names.index("ServiceManager") < names.index("ServiceInTest")

