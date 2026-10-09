# Pandorium Search Audit — Privacy notice

Effective date: 2026-10-09.
Publisher: Pandorium Agency.
This notice describes Pandorium Search Audit version 0.1.1.

## What the plugin processes and why

Pandorium Search Audit checks a supplied public-page HTML snapshot and source URL for search directives, canonical resolution, metadata, headings, JSON-LD, links and CTA evidence. Optional inputs are response-header and robots.txt snapshots, a crawler token, expected links and relevant CTA terms. The bundled helper reads only the explicit input-file paths supplied for the audit. It does not request an account, credentials, payment data, health information or government identifiers. Supply only authorized public-page evidence; remove secrets and personal information that are unnecessary for the audit.

Snapshots and URLs can contain page text, embedded personal information or identifiers. The helper uses them to perform the requested checks. Its report summarizes text values as counts/lengths or safe type names and removes URL credentials, query strings and fragments. URL paths and other permitted audit evidence can still identify a page or person; this suppression is not a guarantee of complete anonymization. Review inputs and reports before sharing them.

## Recipients and network activity

The bundled helper has no network client, server, analytics, cookies, form submission or credential integration. It does not transmit snapshots or reports to Pandorium Agency or another service. It emits a bounded report in the environment where it runs. The model host may process the conversation and uploaded files under its own terms, privacy controls and retention practices; those provider practices are outside this helper's control.

If the user authorizes an available read-only route to obtain a public-page snapshot, that route and its provider have their own data practices. The plugin does not add a network dependency or authorize a new connector. Visiting a linked guide or contacting support is a separate interaction under the relevant website or support policy.

## Storage and retention

The helper processes input during each invocation and has no persistent server-side input store or application telemetry. It does not copy raw snapshots into a plugin database. User-supplied input files remain in the user's or host's environment until removed through that environment's controls. If the user supplies JSON/Markdown output paths, report files remain there until the user deletes them. Without those paths, the report is written to stdout; the host may retain stdout/conversation output according to its own settings. The helper does not control provider retention, backups or local file deletion.

## User controls and contact

Choose the evidence and file paths used for each audit, omit optional inputs, review the report before sharing, and remove saved inputs/reports using the host's normal controls. Use the model provider's controls for conversation or uploaded-file retention. Do not send confidential snapshots or credentials with a support request.

Questions about the plugin can be directed to **hello@pandoriumagency.com**. Voluntary support correspondence and visits to the agency website are covered separately by the [Pandorium Agency privacy policy](https://pandoriumagency.com/privacy-policy). The plugin does not subscribe users to marketing or send messages.
