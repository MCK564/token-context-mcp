# Platforms, remote access, limits and permissions

**Vietnamese:** `PLATFORMS.vi.md` · **Setup walkthrough:** `SETUP.en.md` · **Security policy:** `../SECURITY.md`

Confidence markers used throughout:

- **[verified]** — actually run while writing this document: Windows 11, Python 3.12, on 2026-08-30.
- **[partly verified]** — the mechanism was executed on a real host of that family, but not the whole suite.
- **[documented]** — matches published vendor behaviour but was **not** run here. Do the verification step that follows it.

---

## 1. Operating systems

| OS | Status | Notes |
|---|---|---|
| Windows 10/11 | **[verified]** — full test suite, indexing, `harden --check` and an MCP `stdio` handshake | The reparse-point check uses `st_file_attributes`, which exists only here |
| Linux (x86-64) | **[partly verified]** — permission and path behaviour run on Ubuntu 22.04 under `umask 0022`; the full suite runs on `ubuntu-latest` in CI | The reparse-point check falls back to `is_symlink()` |
| macOS | **[documented]** — same POSIX code path as Linux, not run here | Registry lives under `~/.config`, not `~/Library` |
| WSL | **[partly verified]** | Treat it as Linux. Index the Linux path (`/home/...`), not `/mnt/c/...`: DrvFs does not carry POSIX modes |

Requirements are identical everywhere: **Python ≥ 3.12** (`pyproject.toml` sets `requires-python = ">=3.12"`) and `uv`. No GPU, no API key, no network at run time.

CI runs the source tests and a clean-room wheel install on **`ubuntu-latest` and `windows-latest`** for every push.

### Where state lives

Per machine **and** per account. Registering on your laptop does nothing for a server, and vice versa.

| OS | Registry | Snapshots |
|---|---|---|
| Windows | `%APPDATA%\token-context-mcp\repos.toml` | `%APPDATA%\token-context-mcp\indexes\` |
| Linux | `$XDG_CONFIG_HOME/token-context-mcp/repos.toml`, else `~/.config/token-context-mcp/repos.toml` | `<registry directory>/indexes/` |
| macOS | `~/.config/token-context-mcp/repos.toml` | `<registry directory>/indexes/` |

`TOKEN_CONTEXT_CONFIG` overrides the registry path. On a shared host, read §4 before pointing several accounts at one file.

---

## 2. Remote hosts and SSH

### The rule that decides everything

The transport is **`stdio` only**. The client starts the server as a child process and speaks JSON-RPC over stdin/stdout; the server reads the filesystem of the machine it was started on. There is no network hop, so **source and server must live on the same machine**. A server started on a Windows laptop indexes that laptop, no matter what the editor window is connected to.

### VS Code Remote-SSH

VS Code decides where an MCP server runs by where its configuration lives. **[documented]**

| Configuration location | Server runs on | Works against remote source |
|---|---|---|
| User profile (`MCP: Open User Configuration`) | the local machine | no |
| `.vscode/mcp.json` in a workspace stored on the remote | the remote host | **yes** |
| Remote user settings (`Remote [SSH: host]`) | the remote host | **yes** |

So: run `register`, `index` and `harden` from a **terminal on the server**, and put the configuration in the workspace that lives on the server.

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "/home/you/.local/bin/uv",
      "args": [
        "run", "--no-sync",
        "--directory", "/home/you/token-context-mcp",
        "token-context", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Two details cause most remote failures:

1. **Use `.vscode/mcp.json` with the `"servers"` key**, not a repository-root `.mcp.json`. VS Code before 1.135.0 converts a workspace path with `URI.fsPath`, so `/opt/x` is sent to the Linux host as `\opt\x` and the spawn fails with `ENOENT`.
2. **Give `command` the absolute path to `uv`.** The server is not started through a login shell, so `~/.local/bin` is usually absent from `PATH`. Run `which uv` on the server and paste the result.

### Starting the server over SSH from a local client

`ssh` forwards stdin and stdout unchanged, so a local client can start a remote server directly. **[documented]**

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "ssh",
      "args": ["myserver", "/home/you/.local/bin/uv run --no-sync --directory /home/you/token-context-mcp token-context serve --transport stdio"]
    }
  }
}
```

This also covers **AWS SSM**, where `~/.ssh/config` carries the `ProxyCommand`; the MCP side sees plain SSH either way. Two costs: one SSH session per server start, and **any banner or MOTD printed on stdout corrupts the JSON-RPC stream** — verify with `ssh myserver true` producing no output.

### What does not work

- Cloud or web agents cannot start this server. They need a separately deployed, authenticated HTTP MCP service; this project ships local `stdio` only, deliberately.
- Registering a repository on the client machine does not make it visible to a server process on the host.
- Indexing a Windows drive from WSL (`/mnt/d/...`) works but the snapshot cannot be hardened: DrvFs does not carry POSIX modes.

---

## 3. Limits

### Per repository — set at registration, edited in `repos.toml`

| Limit | Default | What happens at the boundary |
|---|---:|---|
| `max_files` | 25,000 | `index` aborts with `repository exceeds max_files`; nothing is written |
| `max_file_bytes` | 2,000,000 | The file is skipped and counted in `files_skipped` |
| `allow_symlinks` | `false` | Symlinks and Windows reparse points are refused, in the walk and on every lookup |

### Server policy — the `[server]` table, enforced on every request

| Key | Default | Accepted range |
|---|---:|---|
| `max_request_bytes` | 1,048,576 | 1,024 – 1,048,576 |
| `max_result_tokens` | 8,192 | 32 – 8,192 |
| `max_graph_nodes` | 100 | 1 – 500 |
| `max_symbol_results` | 20 | 1 – 100 |

A value outside its range is a configuration error and the server refuses to start. 96 tokens of each budget are reserved for the response envelope, so a 4,096-token request is filled to at most 4,000 tokens of content.

### Coverage

- **Languages parsed:** `.py`, `.pyi` (Python); `.js`, `.jsx` (JavaScript); `.ts` (TypeScript); `.tsx`.
- **Every other extension is recorded but not searchable.** A Markdown, JSON, YAML or TOML file gets an inventory row with `parse_status: unsupported` — it carries a hash and takes part in freshness checks — but it produces no symbols or edges and **its text does not reach `search_source`**. **[verified]** on this repository's own snapshot: 105 files recorded, 48 searchable. Use `rg` for prose.
- **`repo_id` format:** `^[a-z][a-z0-9_-]{0,63}$`. MCP tools accept a `repo_id`, never a filesystem path.
- **Never indexed:** `.git`, `.hg`, `.svn`, `.ssh`, `.aws`, `.gnupg`, `__pycache__`, `.venv`, `venv`, `env`, `.env`, `node_modules`, `site-packages`, and the usual cache directories; files named `id_rsa`, `id_dsa`, `credentials`, `credentials.json`, `.npmrc`; suffixes `.pem`, `.key`, `.p12`, `.pfx`, `.kdbx`. Binary content is detected and skipped. The repository's **root** `.gitignore` is honoured on top of that; nested `.gitignore` files are not read.
- **Edges are lexical**, not a resolved call graph. `get_impact_slice` returns a candidate set with an `ambiguous`/`unresolved` status per edge, not a proof.

---

## 4. Permissions and privacy

### What a snapshot actually contains

A snapshot stores **verbatim source bodies**, because `search_source` and `get_symbol_context` return them. It is a second copy of your repository with its own permissions — treat it as source, not as a cache. An index must never be easier to read than the repository it came from.

### POSIX (Linux, macOS)

The registry, snapshots, manifests and SQLite WAL sidecars are created **owner-only** rather than inheriting the process umask. **[partly verified]** — confirmed on Ubuntu 22.04 under `umask 0022`, which without this would produce mode `0644`.

| Path | Mode |
|---|---|
| `~/.config/token-context-mcp/` and `indexes/` | `0700` |
| `repos.toml`, `*.sqlite`, `*.sqlite-wal`, `*.sqlite-shm`, `*.manifest.json` | `0600` |

Files created by an older version keep their old mode. Repair them:

```bash
uv run token-context harden --check   # report only, changes nothing
uv run token-context harden           # apply
```

If `TOKEN_CONTEXT_CONFIG` points somewhere other than a `token-context-mcp` directory, `harden` restricts only the registry file and the `indexes/` directory — it will not chmod a home or shared directory it does not own.

### Windows

There are no POSIX mode bits. `%APPDATA%` normally inherits an ACL granting only the owner, `SYSTEM` and `Administrators` — but other tooling can add a group to the profile, and that group then reads every snapshot. The same command inspects the ACL instead:

```powershell
uv run token-context harden --check
```

It lists every principal beyond the owner, `SYSTEM` and `Administrators` under `unexpected_principals`. Without `--check` it resets inheritance and re-grants those three. **Check what an unexpected group is for before removing it** — if a sandbox account runs the MCP server, removing its access breaks that client.

### Multi-user hosts

| Situation | Consequence | What to do |
|---|---|---|
| One Linux account per person | Registry and snapshots are already isolated | Run `harden` once |
| Several people sharing one account | One registry: `list_repositories` shows everyone's repos, and concurrent `index` runs contend for the same SQLite file | Give each person their own `TOKEN_CONTEXT_CONFIG` in their MCP configuration |
| `TOKEN_CONTEXT_CONFIG` on a shared path | Deliberately merges registrations and snapshots across users | Only with source everyone may read |

Other users on a default Linux host can see your process **command line** through `/proc`, but not its environment or file descriptors. Never pass a secret to an MCP server as a command-line argument.

**Root, `SYSTEM` and local administrators read these files regardless.** That is a property of the operating system, not something this tool can withhold. On a host you do not control at that level, do not index a repository that must not be disclosed.

Indexing parses the whole tree and is CPU- and I/O-heavy. On a shared machine, schedule it rather than running it during other people's work; `serve` itself is light.

### What the server never does

No file writes inside a repository, no shell execution, no HTTP listener, no outbound network calls, and no acceptance of arbitrary filesystem paths. `stdio` is **not** an OS sandbox: if you need an enforced network boundary, impose it at the OS, container or VM level.

---

## 5. Verification checklist

```bash
# Linux / macOS — run on the machine that holds the source
uv run token-context register --repo-id myproj --root ~/code/myproj
uv run token-context index --repo-id myproj
uv run token-context status --repo-id myproj     # expect "freshness": "fresh"
uv run token-context harden --check              # expect "status": "compliant"
which uv                                         # paste this into mcp.json
```

```powershell
# Windows
uv run token-context register --repo-id myproj --root D:\code\myproj
uv run token-context index --repo-id myproj
uv run token-context status --repo-id myproj
uv run token-context harden --check              # check "unexpected_principals"
```

If a client cannot start the server, run the exact `command` and `args` from your configuration by hand in a terminal first. That separates a broken Python environment from a client that is not loading the configuration.
