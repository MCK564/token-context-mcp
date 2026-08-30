# Security policy and deployment boundary

The package is read-only by design. It deliberately has no tools for shell execution, writes, reindexing, registration or arbitrary filesystem paths.

## Security properties tested by this repository

- relative paths are canonicalized and confined to a registered root;
- symlinks/reparse points are rejected by default;
- hard-denied secret files and secret-like source lines are never emitted;
- malformed inputs and resource-heavy graph requests are bounded;
- results carry source hash, freshness and ambiguity metadata.

## Shared and multi-user hosts

A snapshot stores verbatim source bodies, so it is a second copy of the repository with its own permissions. Treat it as source, not as a cache.

- Registry, snapshots and manifests are created owner-only (`0700` directories, `0600` files) instead of inheriting the process umask, which on a common `0022` default would publish them to every account on the host. `token-context harden --check` reports the current state; `token-context harden` repairs files created before this behaviour existed.
- On Windows the same command inspects the ACL and lists every principal beyond the owner, `SYSTEM` and `Administrators`; a group added to the user profile by other tooling can otherwise read every snapshot.
- One registry per account. `TOKEN_CONTEXT_CONFIG` pointed at a shared path merges registrations and snapshots across users: `list_repositories` then shows everyone's `repo_id` values, and concurrent `index` runs contend for the same SQLite file.
- Where several people share one Linux account, give each a separate `TOKEN_CONTEXT_CONFIG` in their own MCP configuration; the registry is the isolation boundary, and there is no other one.
- The default `/proc` on Linux exposes a process command line to every user, but not its environment or file descriptors. Never pass a secret to an MCP server as a command-line argument.
- Root, `SYSTEM` and local administrators read these files regardless. On a host without control at that level, do not index a repository that must not be disclosed.
- Indexing parses the whole tree and is CPU- and I/O-heavy; on a shared box, schedule it rather than running it during other people's work.

## Properties not guaranteed by the package alone

- `stdio` does not sandbox the process;
- a local index does not keep returned snippets out of the MCP host or LLM provider;
- a Tree-sitter/lexical graph is not a complete call graph;
- no-egress must be enforced by the operating system, container or VM profile.

For an A2 deployment, run under a dedicated account, give read access only to registered roots, deny outbound networking at the OS/container boundary, pin and verify all dependencies/grammars, and preserve signed release evidence.

Report vulnerabilities privately through the deployment owner's security process. Do not include secrets, source files or exploit payloads in public issues.

