from __future__ import annotations

SCHEMA_VERSION = "1.0"
INDEX_SCHEMA_VERSION = "2.0"
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_MAX_REQUEST_BYTES = 1_048_576
DEFAULT_MAX_RESULT_TOKENS = 8_192
DEFAULT_MAX_FILES = 25_000
DEFAULT_MAX_GRAPH_NODES = 500
ENVELOPE_RESERVE_TOKENS = 96
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}
HARD_DENY_DIRECTORIES = {
    ".git", ".hg", ".svn", ".ssh", ".aws", ".gnupg", "__pycache__",
    ".venv", "venv", "env", ".env", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "site-packages", ".tox"
}
HARD_DENY_FILE_NAMES = {"id_rsa", "id_dsa", "credentials", "credentials.json", ".npmrc"}
HARD_DENY_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
