# Security policy and deployment boundary

The package is read-only by design. It deliberately has no tools for shell execution, writes, reindexing, registration or arbitrary filesystem paths.

## Security properties tested by this repository

- relative paths are canonicalized and confined to a registered root;
- symlinks/reparse points are rejected by default;
- hard-denied secret files and secret-like source lines are never emitted;
- malformed inputs and resource-heavy graph requests are bounded;
- results carry source hash, freshness and ambiguity metadata.

## Properties not guaranteed by the package alone

- `stdio` does not sandbox the process;
- a local index does not keep returned snippets out of the MCP host or LLM provider;
- a Tree-sitter/lexical graph is not a complete call graph;
- no-egress must be enforced by the operating system, container or VM profile.

For an A2 deployment, run under a dedicated account, give read access only to registered roots, deny outbound networking at the OS/container boundary, pin and verify all dependencies/grammars, and preserve signed release evidence.

Report vulnerabilities privately through the deployment owner's security process. Do not include secrets, source files or exploit payloads in public issues.

