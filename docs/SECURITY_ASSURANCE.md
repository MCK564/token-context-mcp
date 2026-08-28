# Security assurance

The reviewed `935511f` tree was below the project's **A1 (tested)** bar: its regression suite could pass only in a working tree containing an ignored package, so a clean clone could not collect it. The remediation branch reaches A1 only after the source suite and clean-room wheel checks pass in CI. It is not A2 because no project can self-enforce Windows firewall, container isolation, signing or an independent review solely from Python code.

The test suite covers path traversal, secret canaries, stale files, resource bounds and a real MCP `stdio` round trip. For an A2 deployment:

1. Run under a dedicated OS account with read access only to registered roots.
2. Enforce outbound network deny with a Windows Firewall rule, container or VM profile and retain the policy/exported test evidence.
3. Verify package and grammar hashes from the lockfile before launch.
4. Keep the index database and config ACL-restricted.
5. Treat all repository content as prompt-injection-capable, and remember MCP host/model routing may send returned snippets to a provider.

Generate local, unsigned starter supply-chain artifacts with:

```powershell
uv run token-context release-materials --output supply-chain
```

Sign the release and attest the build in CI before claiming A3.
