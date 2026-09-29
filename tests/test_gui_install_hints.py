"""Missing optional GUI dependencies must produce a clear message, not a bare traceback."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gui_main_without_pyside6_prints_install_hint() -> None:
    code = (
        "import sys; sys.modules['PySide6'] = None; "
        "from token_context_mcp.gui.main import main; raise SystemExit(main([]))"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
        timeout=60,
    )
    assert res.returncode == 1
    assert "uv sync --all-extras" in res.stderr
    assert "Traceback" not in res.stderr


def _load_build_script():
    spec = importlib.util.spec_from_file_location("build_desktop_exe", ROOT / "scripts" / "build_desktop_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_script_reports_missing_packages(monkeypatch) -> None:
    build = _load_build_script()
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: None if name == "PyInstaller" else real(name, *a, **k)
    )
    assert "pyinstaller" in build.missing_build_dependencies()
    try:
        build.build_executable()
    except SystemExit as exc:
        assert "uv sync --all-extras" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("build_executable must stop when PyInstaller is missing")


def test_build_script_bundles_every_grammar() -> None:
    text = (ROOT / "scripts" / "build_desktop_exe.py").read_text(encoding="utf-8")
    for grammar in ("python", "javascript", "typescript", "java", "c_sharp", "html", "css", "go"):
        assert f'"tree_sitter_{grammar}"' in text
