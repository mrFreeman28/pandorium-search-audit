# Verification record

Date: 2026-10-09

Scope: local source and package acceptance for version 0.1.0. These checks do not establish native-host acceptance, a marketplace listing, traffic or client acquisition. The helper has no network call, MCP server, hook or credential dependency.

## Passed local checks

- `python3 -m unittest discover -s tests -v`: 19 tests passed. Cases cover complete and missing evidence, status/directive/canonical/robots blockers, private query-aware comparisons, mixed crawler headers, percent-equivalent robots paths, terminal `$` specificity, wildcard stress, supplied-but-unsupported robots evidence, unsupported-rule unknowns, credentials/query/contact-data suppression, non-regular files, limit+1 reads, deeply nested JSON-LD and JSON-header containment at the CLI boundary without traceback or content disclosure, and deterministic archives.
- `python3 -m py_compile ...`: helper, packager, and verifier compile successfully.
- `python3 scripts/package.py && python3 scripts/verify_package.py`: source and both archives pass the offline format, path, size, allow-list, and deterministic metadata checks.
- Clean extraction smoke test: the helper ran successfully from each ZIP, parsed its bounded JSON, stripped URL credentials/query/fragment from output, and emitted no supplied secret text.
- Root independent acceptance: 22 subprocess checks across freshly extracted copies of both final ZIPs passed under Python 3.9.6. They covered complete/missing evidence, selected-crawler headers, query-aware canonicals and robots, unsupported rules, percent-equivalent paths, deep JSON, oversized files and nonblocking FIFO rejection. All 149 source files in the agency's positive public-site manifest remained byte-identical to the reviewed base; this plugin does not change the agency site.
- Claude Code 2.1.285: `plugin validate --strict .claude-plugin/plugin.json` and `plugin validate --strict .claude-plugin/marketplace.json` passed. A separate temporary `CLAUDE_CONFIG_DIR` and plugin-cache root then added `mrFreeman28/pandorium-search-audit`, installed `pandorium-search-audit@pandorium-search-audit`, and listed version 0.1.0 as enabled. The temporary environment was removed after the test. No persistent user-level installation, provider model session, private-data access or default configuration change was performed. Nonessential traffic and official-marketplace autoinstall were disabled for that isolated test.
- Official Agent Plugins schema fetched from `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`: valid JSON; `$id` matches; required fields are `$schema` and `name`; top-level additional properties are rejected. The source verifier checks this schema identifier and the package's documented OpenAI fields and limits.
- Icon SHA-256 matches the existing source asset exactly: `82b1735ed1aa12521bd3b997ae82ddab34d84fbb09595178c2802800852fcbcd`. The SVG has numeric 512 by 512 dimensions and viewBox.

## Reproducible artifacts

- Claude ZIP: `pandorium-search-audit-claude-0.1.0.zip`, 15,121 bytes, SHA-256 `f0add1e6beb8dea875814d9676f6d7e20960fd9deb5025e736512888b5a375c4`.
- OpenAI ZIP: `pandorium-search-audit-openai-0.1.0.zip`, 15,616 bytes, SHA-256 `527be375b2a0b856a4576efca44b55f0888070dff4bad017a379487612eaf3ee`.
- Each ZIP contains exactly five allow-listed runtime files: its manifest, `LICENSE`, icon, `SKILL.md`, and offline helper. Tests, marketplace catalog, evidence, build scripts, caches, raw snapshots, and repository data are absent.

## Remaining platform checks

- The bundled Skill Creator `quick_validate.py` could not run because its environment lacks PyYAML (`ModuleNotFoundError: yaml`). No dependency was installed. The package's standard-library verifier checks required frontmatter and unfinished-format invariants.
- Native manifest validation and isolated installation are verified. Skill execution inside an authenticated Claude model session has not been tested; the offline helper was independently exercised from both extracted archives. Those checks do not establish Anthropic directory acceptance.
- OpenAI portal validation, skill scans, target-surface Python availability, publisher identity, listing review and Anthropic directory review remain unverified. Public source availability is separate from acceptance or publication in either provider's official directory.
