# Pandorium Search Audit

Pandorium Search Audit reviews sanitized HTML, HTTP headers, and robots.txt text pasted into the current Claude request. It explains which parts of the supplied evidence indicate a search eligibility or on-page issue, what remains unverified, and which fixes to check first. Use it to diagnose directives, canonical tags, crawler restrictions, and visible page metadata.

## Run an audit

Start an audit request with a public page URL and paste the relevant excerpt as text. Label each block `HTML`, `HTTP headers`, or `robots.txt`. A partial excerpt can show a visible issue. To verify that a tag or rule is missing, paste the complete relevant section. Keep personal information and credentials out of the request.

The skill works in the conversation and returns the report there. It has no script, browser, connector, data service, or separate login. If Claude asks for an excerpt, paste it into the current request. The report distinguishes issues visible in the evidence from checks that require more context.

## Reviewer examples

Use Claude with the plugin enabled. In Claude Code, load this folder as a local plugin and invoke the `pandorium-search-audit` skill. No separate test account or credentials are needed to exercise its features. Each example below is a complete prompt with synthetic input.

### An HTTP directive blocks indexing

```text
Audit this pasted evidence for https://example.com/services.
HTML:
<html><head><title>Example Services</title><link rel="canonical" href="https://example.com/services"></head><body><h1>Services</h1></body></html>
HTTP headers:
HTTP/1.1 200 OK
X-Robots-Tag: noindex
```

Expected: flag the `noindex` header as a priority issue, report HTTP 200 and the matching canonical separately, and leave robots access unverified.

### A crawler rule blocks a page path

```text
Audit this pasted robots.txt for Googlebot at https://example.com/private/report.
robots.txt (complete):
User-agent: *
Disallow: /private/
Allow: /private/help/
```

Expected: report that the supplied rule disallows crawling this path. Mark indexing directives and canonical evidence as unverified.

### A title is absent from a complete head

```text
Audit this pasted HTML for https://example.com/about.
HTML (complete head):
<head><meta name="description" content="About this example"><link rel="canonical" href="/about"></head>
```

Expected: flag the missing title, resolve the matching canonical, and leave the response status and H1 unverified.

## Privacy and support

[Privacy](https://github.com/mrFreeman28/pandorium-search-audit/blob/codex/claude-directory-014-20261106/claude-directory/PRIVACY.md) · hello@pandoriumagency.com

MIT license.
