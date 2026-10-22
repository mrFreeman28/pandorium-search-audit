# Install Pandorium Search Audit from a Git marketplace

This branch supplies `.agents/plugins/marketplace.json` for the existing Pandorium Search Audit plugin. It uses the accepted 0.1.3 canonical-Terms metadata and unchanged offline runtime. It creates no new OpenAI listing. The existing Claude marketplace catalog is retained unchanged.

OpenAI documents Git-backed and local marketplaces for supported Codex/ChatGPT desktop clients, separately from its universal public directory. The separate OpenAI-format catalog supplies the explicit installation/authentication policy metadata in the documented shape without changing Claude's catalog. `ON_INSTALL` is the host catalog policy value, not a request for account credentials: this offline plugin has no service authentication or MCP server.

With a Codex CLI version that supports plugin marketplaces, add this Git source:

```sh
codex plugin marketplace add mrFreeman28/pandorium-search-audit --ref codex/direct-marketplace-terms-013-2026-10-22
```

Then select **Pandorium Search Audit** as the marketplace source and install the same plugin in a supported desktop client's Plugins Directory. For a reproducible pin, replace the branch name with the full reviewed Git commit SHA; `--ref` accepts a Git ref. Refresh the desktop source list if the newly added marketplace is not yet visible. This route uses local desktop execution. Public Directory listing and web/mobile hosted execution remain separate and unverified. The existing manual fallback still applies. This source change has not been installation-tested. No account connection, model session or execution test was run for it. The existing Python/local-execution requirements and previous runtime verification limits still apply.

People can reach this installation source from the existing website, audit guide or GitHub. The source is not a claim of discovery traffic or Directory placement.

Official source: https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli and its marketplace metadata section.

Plugin-specific software terms: https://pandoriumagency.com/plugins/search-audit/terms/ . Snapshot/host privacy boundaries: [PRIVACY.md](PRIVACY.md). The metadata update changes no helper data-processing behavior.
