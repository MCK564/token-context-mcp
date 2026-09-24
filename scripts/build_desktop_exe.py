"""
Build script to package TokenContextDesktop into an executable using PyInstaller.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def create_default_icon(icon_path: Path) -> None:
    """Generate a simple default icon if none exists."""
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    if icon_path.exists():
        return

    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Draw a rounded badge with gradient look
        draw.ellipse([(4, 4), (60, 60)], fill=(30, 30, 46, 255), outline=(137, 180, 250, 255), width=3)
        # Inner symbol 'T'
        draw.rectangle([(20, 16), (44, 22)], fill=(137, 180, 250, 255))
        draw.rectangle([(29, 22), (35, 48)], fill=(137, 180, 250, 255))
        img.save(str(icon_path), format="ICO")
        print(f"Created default icon at: {icon_path}")
    except Exception as e:
        print(f"Could not generate icon with PIL ({e}), building without icon.")


def build_executable(onefile: bool = False, clean: bool = False, output_name: str = "TokenContextDesktop") -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    main_script = repo_root / "src" / "token_context_mcp" / "gui" / "main.py"
    icon_file = repo_root / "assets" / "icon.ico"
    dist_dir = repo_root / "dist" / "desktop"
    build_dir = repo_root / "build" / "desktop"

    if clean:
        print("Cleaning previous build artifacts...")
        shutil.rmtree(dist_dir, ignore_errors=True)
        shutil.rmtree(build_dir, ignore_errors=True)

    create_default_icon(icon_file)

    # Path separator for PyInstaller --add-data
    sep = ";" if sys.platform == "win32" else ":"
    src_data = f"{repo_root / 'src' / 'token_context_mcp'}{sep}token_context_mcp"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        output_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--add-data",
        src_data,
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    if icon_file.exists():
        cmd.extend(["--icon", str(icon_file)])

    # Essential hidden imports for AST tree-sitter & dynamic modules
    hidden_imports = [
        "tree_sitter",
        "tree_sitter_python",
        "tree_sitter_javascript",
        "tree_sitter_typescript",
        "tree_sitter_java",
        "tree_sitter_c_sharp",
        "tree_sitter_html",
        "tree_sitter_css",
        "pydantic",
        "pydantic_core",
        "psutil",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "token_context_mcp",
        "token_context_mcp.server",
        "token_context_mcp.gui",
        "token_context_mcp.gui.bridge",
        "token_context_mcp.gui.main_window",
        "token_context_mcp.gui.theme",
        "token_context_mcp.gui.widgets",
        "token_context_mcp.gui.widgets.loading_overlay",
        "token_context_mcp.gui.widgets.dashboard_tab",
        "token_context_mcp.gui.widgets.repositories_tab",
        "token_context_mcp.gui.widgets.tasks_tab",
        "token_context_mcp.gui.widgets.cache_tab",
        "token_context_mcp.gui.widgets.agents_tab",
        "token_context_mcp.gui.widgets.settings_tab",
        "token_context_mcp.security",
        "token_context_mcp.security.access_control",
        "token_context_mcp.security.audit",
        "token_context_mcp.security.path_policy",
        "token_context_mcp.security.content_policy",
        "token_context_mcp.security.local_privacy",
        "token_context_mcp.retrieve.service",
        "token_context_mcp.index.runner",
    ]

    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    cmd.append(str(main_script))

    print(f"\n=======================================================")
    print(f"  Building {output_name} ({'Single-File' if onefile else 'Directory Bundle'})...")
    print(f"=======================================================")
    print("Running command:", " ".join(cmd[:8]), "...")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    res = subprocess.run(cmd, cwd=str(repo_root), env=env)

    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}")

    if onefile:
        exe_path = dist_dir / (f"{output_name}.exe" if sys.platform == "win32" else output_name)
    else:
        exe_path = dist_dir / output_name / (f"{output_name}.exe" if sys.platform == "win32" else output_name)

    print(f"\nBuild successful! Output executable: {exe_path}")
    return exe_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Package token-context-mcp desktop controller into executable.")
    parser.add_argument("--onefile", action="store_true", help="Build single standalone executable file")
    parser.add_argument("--clean", action="store_true", help="Clean build directories before packaging")
    parser.add_argument("--name", default="TokenContextDesktop", help="Executable name")
    args = parser.parse_args()

    build_executable(onefile=args.onefile, clean=args.clean, output_name=args.name)


if __name__ == "__main__":
    main()
