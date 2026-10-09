# Pandorium Search Audit

Review an HTML snapshot for search blockers and practical next fixes. This free, skills-only plugin includes an offline Python helper and instructions for Claude Code and OpenAI's ChatGPT/Codex plugin formats.

It checks supplied HTTP status, indexing and snippet directives, canonical URLs, title/description/H1 structure, JSON-LD parsing, selected-crawler robots rules, internal links and CTA evidence. Each finding includes evidence, priority and a next step. Missing evidence stays unknown. There is no universal SEO/GEO score or ranking guarantee.

The helper uses the Python standard library. It makes no network requests, executes no page JavaScript, submits no forms and sends no snapshot data to an external service. Displayed URLs omit credentials, queries and fragments; embedded page text, scripts, contact details and header values are not copied into the report.

## Run an audit

Use Python 3.9 or newer. Save raw HTML and any optional response headers or robots.txt through your existing read-only workflow. Extracted article text alone cannot prove that tags in the document head are missing.

```sh
python3 skills/pandorium-search-audit/scripts/search_audit.py \
  --html page.html \
  --url https://example.com/ \
  --headers headers.txt \
  --robots robots.txt \
  --crawler googlebot \
  --expected-link /contact/ \
  --cta-term book \
  --json-out audit.json \
  --report-out audit.md
```

Only `--html` and `--url` are required. Without output paths, the helper prints bounded JSON. It rejects non-regular files, invalid input and oversized snapshots. Input limits: HTML 2 MiB, headers 64 KiB, robots 512 KiB; each output is limited to 256 KiB.

Results describe supplied snapshots. They do not verify current indexing, rankings, AI citations, search demand, JavaScript behavior, leads or revenue. Robots interpretation is bounded; unsupported or oversized rules remain unverified. Review any proposed live-site change in your normal release process.

## Claude Code

The repository provides a marketplace catalog with one skills-only plugin. With a current Claude Code installation:

```text
claude plugin marketplace add mrFreeman28/pandorium-search-audit
claude plugin install pandorium-search-audit@pandorium-search-audit
```

Ask Claude to audit your saved page snapshot using Pandorium Search Audit. The skill resolves its bundled helper within the installed skill directory. Both manifests passed strict validation in Claude Code 2.1.285; marketplace add, installation and enabled-plugin listing from this public repository passed in an isolated temporary configuration. No model session was invoked. Python execution still depends on the host environment. See [VERIFICATION.md](VERIFICATION.md). Older Claude versions may reject newer listing metadata fields.

## ChatGPT / Codex

Build the OpenAI ZIP below for a skills-only upload in the publisher workflow. It contains portable `plugin.json`, this skill's runtime, the license and icon. This repository is not an accepted OpenAI directory listing.

Before submission, confirm Apps Management Write access, verified publishing identity, the target surface's Python execution capability and portal scan results. If local script execution is unavailable, the skill provides a clearly labelled manual review and must not claim the deterministic helper ran. OpenAI's Claude-plugin conversion guidance advises contacting an OpenAI partner when core value requires local execution, arbitrary file access or offline operation.

Skills-only submissions do not require MCP review cases or a demo recording. OpenAI imported version 0.1.0 as a draft under verified Business — Pandorium Agency on 9 October 2026. Version 0.1.1 adds the published privacy-notice and support URLs; the replacement draft passed the platform's metadata and skill checks. The local/offline-execution review route, target-surface execution, formal review and publication remain separate checks. The plugin has not been submitted for review or published in the OpenAI directory.

## Verify and build

```sh
python3 -m unittest discover -s tests -v
python3 scripts/package.py
python3 scripts/verify_package.py
```

Builds produce reproducible ignored archives:

- `dist/pandorium-search-audit-openai-0.1.1.zip`
- `dist/pandorium-search-audit-claude-0.1.1.zip`

Each archive contains exactly five runtime files. Tests, marketplace catalog, build scripts, caches, raw snapshots and repository data are excluded. For native Claude validation, when already installed:

```text
claude plugin validate --strict .
```

The original helper and packaging code are available under the included [MIT License](LICENSE). The icon is the existing Pandorium brand asset. The public repository contains no client code, private agency memory, credentials or client data.

## Support and privacy

The [plugin privacy notice](PRIVACY.md) describes snapshot processing, recipients, retention and user controls. For help, contact **hello@pandoriumagency.com**; do not include credentials or confidential snapshots in a support request.

## Further reading

[Pandorium's AI search audit guide](https://pandoriumagency.com/guides/ai-search-optimization-audit/) explains the wider audit process, including evidence that a snapshot cannot establish.

Format requirements were checked on 9 October 2026 against primary documentation:

- [OpenAI: Package your plugin](https://developers.openai.com/plugins/build/plugins)
- [OpenAI: Upload and submit your plugin](https://developers.openai.com/plugins/deploy/submission)
- [OpenAI: Submit your Claude Code plugin](https://developers.openai.com/plugins/guides/submit-claude-plugin)
- [OpenAI: Build skills](https://developers.openai.com/plugins/build/skills)
- [Agent Plugins 1.0.0 schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)
- [Anthropic: Plugin manifest reference](https://code.claude.com/docs/en/plugins-reference)
- [Anthropic: Create a marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- [Anthropic: Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference)
