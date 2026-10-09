#!/usr/bin/env python3
"""Deterministic, offline audit of user-supplied search snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


VERSION = "0.1.0"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_HEADERS_BYTES = 64 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
MAX_URL_CHARS = 2048
MAX_JSONLD_BLOCKS = 32
MAX_JSONLD_BLOCK_CHARS = 256 * 1024
MAX_LINKS_TRACKED = 5000
MAX_TERMS = 32
SAFE_TYPE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
DEFAULT_CTA_TERMS = (
    "book",
    "buy",
    "call",
    "contact",
    "download",
    "get started",
    "request",
    "shop",
    "start",
    "subscribe",
    "quote",
    "demo",
    "apply",
)


class AuditInputError(ValueError):
    pass


def _read_bounded(path: Path, limit: int, label: str) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AuditInputError(f"Cannot open {label} snapshot") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AuditInputError(f"{label} snapshot must be a regular file")
        if metadata.st_size > limit:
            raise AuditInputError(f"{label} snapshot exceeds {limit} bytes")
        chunks: List[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > limit:
            raise AuditInputError(f"{label} snapshot exceeds {limit} bytes")
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditInputError(f"{label} snapshot must be UTF-8 text") from exc
    except OSError as exc:
        raise AuditInputError(f"Cannot read {label} snapshot") from exc
    finally:
        os.close(descriptor)


def normalize_url(value: str, base: Optional[str] = None, keep_query: bool = False) -> Optional[str]:
    """Resolve HTTP(S), remove credentials/fragments, and optionally retain a private query."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_URL_CHARS:
        return None
    candidate = urljoin(base, value.strip()) if base else value.strip()
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parts.port
        default_port = (parts.scheme.lower() == "http" and port == 80) or (
            parts.scheme.lower() == "https" and port == 443
        )
        netloc = host if port is None or default_port else f"{host}:{port}"
        path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
        query = parts.query if keep_query else ""
        return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    except (UnicodeError, ValueError):
        return None


def sanitize_url(value: str, base: Optional[str] = None) -> Optional[str]:
    """Resolve an HTTP(S) URL and remove credentials, query, and fragment for output."""
    return normalize_url(value, base, keep_query=False)


def _origin(url: str) -> Tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def _clean_space(value: str) -> str:
    return " ".join(value.split())


class SnapshotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: List[str] = []
        self.h1s: List[str] = []
        self.descriptions: List[str] = []
        self.meta_directives: List[Tuple[str, str]] = []
        self.canonical_hrefs: List[str] = []
        self.base_href: Optional[str] = None
        self.jsonld_blocks: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self.button_texts: List[str] = []
        self._title_depth = 0
        self._title_parts: List[str] = []
        self._h1_depth = 0
        self._h1_parts: List[str] = []
        self._anchor_depth = 0
        self._anchor_href: Optional[str] = None
        self._anchor_parts: List[str] = []
        self._button_depth = 0
        self._button_parts: List[str] = []
        self._jsonld_active = False
        self._jsonld_parts: List[str] = []
        self._jsonld_chars = 0
        self.jsonld_block_truncated = False
        self.jsonld_overflow = 0
        self.link_overflow = 0

    @staticmethod
    def _attrs(attrs: Sequence[Tuple[str, Optional[str]]]) -> Dict[str, str]:
        return {str(key).lower(): value or "" for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        values = self._attrs(attrs)
        if tag == "title":
            self._title_depth += 1
            if self._title_depth == 1:
                self._title_parts = []
        elif tag == "h1":
            self._h1_depth += 1
            if self._h1_depth == 1:
                self._h1_parts = []
        elif tag == "meta":
            name = values.get("name", "").strip().lower()
            content = values.get("content", "")
            if name == "description":
                self.descriptions.append(_clean_space(content))
            if name:
                self.meta_directives.append((name, content))
        elif tag == "link":
            rel = {part.lower() for part in values.get("rel", "").split()}
            if "canonical" in rel:
                self.canonical_hrefs.append(values.get("href", "").strip())
        elif tag == "base" and self.base_href is None:
            self.base_href = values.get("href", "").strip() or None
        elif tag == "script" and values.get("type", "").split(";", 1)[0].strip().lower() == "application/ld+json":
            if len(self.jsonld_blocks) >= MAX_JSONLD_BLOCKS:
                self.jsonld_overflow += 1
            else:
                self._jsonld_active = True
                self._jsonld_parts = []
                self._jsonld_chars = 0
        elif tag == "a":
            self._anchor_depth += 1
            if self._anchor_depth == 1:
                self._anchor_href = values.get("href", "").strip() or None
                self._anchor_parts = []
        elif tag == "button" or values.get("role", "").strip().lower() == "button":
            self._button_depth += 1
            if self._button_depth == 1:
                self._button_parts = []
        elif tag == "input" and values.get("type", "").strip().lower() in {"submit", "button"}:
            self.button_texts.append(_clean_space(values.get("value", ""))[:200])

    def handle_startendtag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._title_parts.append(data)
        if self._h1_depth:
            self._h1_parts.append(data)
        if self._anchor_depth:
            self._anchor_parts.append(data)
        if self._button_depth:
            self._button_parts.append(data)
        if self._jsonld_active:
            remaining = MAX_JSONLD_BLOCK_CHARS - self._jsonld_chars
            if remaining > 0:
                accepted = data[:remaining]
                self._jsonld_parts.append(accepted)
                self._jsonld_chars += len(accepted)
            if len(data) > max(remaining, 0):
                self.jsonld_block_truncated = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
            if self._title_depth == 0:
                self.titles.append(_clean_space("".join(self._title_parts)))
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                self.h1s.append(_clean_space("".join(self._h1_parts)))
        elif tag == "a" and self._anchor_depth:
            self._anchor_depth -= 1
            if self._anchor_depth == 0:
                if len(self.links) < MAX_LINKS_TRACKED:
                    self.links.append((self._anchor_href or "", _clean_space("".join(self._anchor_parts))[:200]))
                else:
                    self.link_overflow += 1
                self._anchor_href = None
        elif tag == "button" and self._button_depth:
            self._button_depth -= 1
            if self._button_depth == 0:
                self.button_texts.append(_clean_space("".join(self._button_parts))[:200])
        elif tag == "script" and self._jsonld_active:
            self._jsonld_active = False
            self.jsonld_blocks.append("".join(self._jsonld_parts))
            self._jsonld_parts = []


def parse_headers(snapshot: Optional[str]) -> Tuple[Optional[int], Dict[str, List[str]]]:
    if snapshot is None:
        return None, {}
    status: Optional[int] = None
    headers: Dict[str, List[str]] = {}
    stripped = snapshot.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(snapshot)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise AuditInputError("Header snapshot is not valid JSON or raw HTTP headers") from exc
        if not isinstance(payload, dict):
            raise AuditInputError("JSON header snapshot must be an object")
        raw_status = payload.get("status", payload.get("status_code"))
        source = payload.get("headers", payload)
        if raw_status is not None:
            try:
                status = int(raw_status)
            except (TypeError, ValueError) as exc:
                raise AuditInputError("Header snapshot status must be an integer") from exc
        if not isinstance(source, dict):
            raise AuditInputError("JSON headers field must be an object")
        for key, value in list(source.items())[:256]:
            name = str(key).strip().lower()
            if name in {"status", "status_code", "headers"}:
                continue
            values = value if isinstance(value, list) else [value]
            headers[name] = [str(item)[:8192] for item in values]
    else:
        for index, line in enumerate(snapshot.splitlines()[:1024]):
            line = line.strip("\r")
            if line.lower().startswith(":status:"):
                try:
                    status = int(line.split(":", 2)[2].strip())
                except (IndexError, ValueError):
                    pass
                continue
            if index == 0:
                match = re.match(r"^HTTP/\S+\s+(\d{3})(?:\s|$)", line, re.I)
                if match:
                    status = int(match.group(1))
                    continue
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            name = name.strip().lower()
            if name == "" or len(name) > 128:
                continue
            headers.setdefault(name, []).append(value.strip()[:8192])
    if status is not None and not 100 <= status <= 599:
        raise AuditInputError("Header snapshot status must be between 100 and 599")
    return status, headers


def parse_directives(items: Iterable[Tuple[str, str]], crawler: str) -> List[str]:
    directives: List[str] = []
    crawler = crawler.lower()
    for agent, content in items:
        agent = agent.lower().strip()
        if agent not in {"robots", crawler}:
            continue
        for raw in content.lower().split(","):
            token = _clean_space(raw)
            if not token:
                continue
            if token == "none":
                directives.extend(["noindex", "nofollow"])
            elif token in {"index", "noindex", "follow", "nofollow", "nosnippet", "noarchive"}:
                directives.append(token)
            elif re.fullmatch(r"max-snippet\s*:\s*-?\d+", token):
                directives.append(token.replace(" ", ""))
    return sorted(set(directives))


def parse_x_robots(values: Iterable[str], crawler: str) -> List[str]:
    pairs: List[Tuple[str, str]] = []
    directive_prefixes = {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}
    for value in values:
        current_agent = "robots"
        for raw in value.split(","):
            stripped = raw.strip()
            first, sep, rest = stripped.partition(":")
            prefix = first.strip().lower()
            if sep and prefix not in directive_prefixes and re.fullmatch(r"[a-z0-9*._-]{1,80}", prefix):
                current_agent = prefix
                pairs.append((current_agent, rest))
            else:
                pairs.append((current_agent, stripped))
    return parse_directives(pairs, crawler)


ROBOTS_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
MAX_ROBOTS_PATTERN_CHARS = 4096


def _normalize_robots_octets(value: str) -> Optional[str]:
    """Normalize unreserved percent escapes without equating escaped reserved bytes."""
    result: List[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "%":
            if index + 2 >= len(value) or not re.fullmatch(r"[0-9A-Fa-f]{2}", value[index + 1:index + 3]):
                return None
            byte = int(value[index + 1:index + 3], 16)
            decoded = chr(byte)
            result.append(decoded if decoded in ROBOTS_UNRESERVED else f"%{byte:02X}")
            index += 3
            continue
        codepoint = ord(char)
        if codepoint < 32 or codepoint == 127:
            return None
        if codepoint > 127:
            result.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
        else:
            result.append(char)
        index += 1
    return "".join(result)


def _bounded_robots_match(pattern: str, target: str) -> Optional[Tuple[bool, int]]:
    """Match robots * and terminal $ using bounded ordered substring scans."""
    if len(pattern) > MAX_ROBOTS_PATTERN_CHARS:
        return None
    end_anchored = pattern.endswith("$")
    core = pattern[:-1] if end_anchored else pattern
    normalized_pattern = _normalize_robots_octets(core)
    normalized_target = _normalize_robots_octets(target)
    if normalized_pattern is None or normalized_target is None:
        return None
    specificity = len(normalized_pattern.replace("*", ""))
    leading_star = normalized_pattern.startswith("*")
    trailing_star = normalized_pattern.endswith("*")
    segments = [segment for segment in normalized_pattern.split("*") if segment]
    if not segments:
        return ((not end_anchored) or normalized_target == "", specificity)

    position = 0
    segment_index = 0
    if not leading_star:
        first = segments[0]
        if not normalized_target.startswith(first):
            return False, specificity
        position = len(first)
        segment_index = 1

    for index in range(segment_index, len(segments)):
        segment = segments[index]
        is_last = index == len(segments) - 1
        if end_anchored and is_last and not trailing_star:
            start = len(normalized_target) - len(segment)
            if start < position or not normalized_target.startswith(segment, start):
                return False, specificity
            position = len(normalized_target)
        else:
            found = normalized_target.find(segment, position)
            if found < 0:
                return False, specificity
            position = found + len(segment)

    if end_anchored and not trailing_star and position != len(normalized_target):
        return False, specificity
    return True, specificity


def evaluate_robots(snapshot: Optional[str], crawler: str, source_url: str) -> Dict[str, Any]:
    if snapshot is None:
        return {"status": "unknown", "reason": "robots.txt snapshot was not supplied"}
    groups: List[Dict[str, Any]] = []
    agents: List[str] = []
    rules: List[Tuple[str, str]] = []
    has_rules = False
    for original in snapshot.splitlines()[:20000]:
        line = original.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = line.split(":", 1)
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if has_rules:
                groups.append({"agents": agents, "rules": rules})
                agents, rules, has_rules = [], [], False
            agents.append(value.lower())
        elif field in {"allow", "disallow"} and agents:
            rules.append((field, value))
            has_rules = True
    if agents:
        groups.append({"agents": agents, "rules": rules})

    crawler_lower = crawler.lower()
    candidates: List[Tuple[int, List[Tuple[str, str]]]] = []
    for group in groups:
        best = -1
        for agent in group["agents"]:
            if agent == "*":
                best = max(best, 0)
            elif crawler_lower.startswith(agent) or agent in crawler_lower:
                best = max(best, len(agent))
        if best >= 0:
            candidates.append((best, group["rules"]))
    if not candidates:
        return {"status": "allowed", "matched_rule": None, "reason": "no matching user-agent group"}
    max_specificity = max(item[0] for item in candidates)
    selected_rules = [rule for specificity, group_rules in candidates if specificity == max_specificity for rule in group_rules]
    parts = urlsplit(source_url)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    matches: List[Tuple[int, bool, str]] = []
    unsupported_rule = False
    for kind, pattern in selected_rules:
        if kind == "disallow" and pattern == "":
            continue
        outcome = _bounded_robots_match(pattern, target)
        if outcome is None:
            unsupported_rule = True
            continue
        matched, specificity = outcome
        if matched:
            matches.append((specificity, kind == "allow", kind))
    if unsupported_rule:
        return {
            "status": "unknown",
            "matched_rule": None,
            "reason": "a selected rule exceeded matcher limits or used malformed percent encoding",
        }
    if not matches:
        return {"status": "allowed", "matched_rule": None, "reason": "no selected rule matched the path"}
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    length, allowed, kind = matches[0]
    return {
        "status": "allowed" if allowed else "blocked",
        "matched_rule": kind,
        "matched_rule_length": length,
        "reason": "longest matching selected-crawler rule",
    }


def extract_jsonld_types(value: Any, limit: int = 1000) -> Tuple[List[str], bool]:
    types: set[str] = set()
    stack = [value]
    visited = 0
    while stack and visited < limit:
        current = stack.pop()
        visited += 1
        if isinstance(current, dict):
            raw_type = current.get("@type")
            values = raw_type if isinstance(raw_type, list) else [raw_type]
            for item in values:
                if isinstance(item, str) and SAFE_TYPE.fullmatch(item):
                    types.add(item)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return sorted(types), bool(stack)


def _finding(identifier: str, severity: str, status: str, evidence: str, next_step: str) -> Dict[str, str]:
    return {
        "id": identifier,
        "severity": severity,
        "status": status,
        "evidence": evidence,
        "next_step": next_step,
    }


def audit(
    html: str,
    source_url: str,
    headers_snapshot: Optional[str] = None,
    robots_snapshot: Optional[str] = None,
    crawler: str = "googlebot",
    expected_links: Sequence[str] = (),
    cta_terms: Sequence[str] = (),
) -> Dict[str, Any]:
    private_source = normalize_url(source_url, keep_query=True)
    safe_source = sanitize_url(source_url)
    if private_source is None or safe_source is None:
        raise AuditInputError("Source URL must be an absolute HTTP(S) URL of at most 2048 characters")
    if not re.fullmatch(r"[A-Za-z0-9*._-]{1,80}", crawler):
        raise AuditInputError("Crawler token must use 1-80 letters, numbers, period, underscore, hyphen, or *")
    if len(expected_links) > MAX_TERMS or len(cta_terms) > MAX_TERMS:
        raise AuditInputError(f"At most {MAX_TERMS} expected links and CTA terms are allowed")
    if any(len(item) > MAX_URL_CHARS for item in expected_links):
        raise AuditInputError("Expected links must be at most 2048 characters")
    if any(not item.strip() or len(item) > 100 for item in cta_terms):
        raise AuditInputError("CTA terms must be 1-100 non-whitespace characters")

    parser = SnapshotParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise AuditInputError(f"HTML snapshot could not be parsed: {type(exc).__name__}") from exc

    status_code, headers = parse_headers(headers_snapshot)
    findings: List[Dict[str, str]] = []

    if status_code is None:
        findings.append(_finding("response-status", "info", "unknown", "No response status snapshot was supplied.", "Capture the final HTTP response status if live eligibility matters."))
    elif 200 <= status_code < 300:
        findings.append(_finding("response-status", "info", "pass", f"Supplied response status is {status_code}.", "No status remediation indicated by this snapshot."))
    elif 300 <= status_code < 400:
        findings.append(_finding("response-status", "medium", "fail", f"Supplied response status is {status_code}, so this is not a final 2xx page response.", "Audit the final redirect destination and keep the redirect chain intentional."))
    else:
        findings.append(_finding("response-status", "high", "fail", f"Supplied response status is {status_code}.", "Restore an intentional indexable 2xx response or document why this URL should stay unavailable."))

    content_types = headers.get("content-type", [])
    if headers_snapshot is None:
        findings.append(_finding("content-type", "info", "unknown", "No response-header snapshot was supplied.", "Capture response headers to verify the served media type."))
    elif not content_types:
        findings.append(_finding("content-type", "low", "unknown", "The supplied header snapshot has no Content-Type field.", "Capture complete response headers and verify an HTML media type."))
    elif any("text/html" in item.lower() or "application/xhtml+xml" in item.lower() for item in content_types):
        findings.append(_finding("content-type", "info", "pass", "The supplied Content-Type identifies an HTML document.", "No media-type remediation indicated by this snapshot."))
    else:
        findings.append(_finding("content-type", "high", "fail", "The supplied Content-Type does not identify an HTML document.", "Serve the page with an appropriate HTML media type if it is intended as a search landing page."))

    meta_directives = parse_directives(parser.meta_directives, crawler)
    header_directives = parse_x_robots(headers.get("x-robots-tag", []), crawler)
    combined_directives = sorted(set(meta_directives + header_directives))
    noindex = "noindex" in combined_directives
    snippet_blocked = "nosnippet" in combined_directives or "max-snippet:0" in combined_directives
    if noindex:
        findings.append(_finding("index-directives", "high", "fail", "A supplied robots directive contains noindex.", "Remove noindex only if this page is intentionally eligible for indexing, then verify the live response."))
    elif headers_snapshot is None:
        findings.append(_finding("index-directives", "info", "unknown", "The HTML snapshot has no observed noindex directive, but response headers were not supplied.", "Capture X-Robots-Tag response headers before concluding directive eligibility."))
    else:
        findings.append(_finding("index-directives", "info", "pass", "No recognized noindex directive appears in the supplied HTML or response headers.", "Treat this as directive evidence only; actual indexing remains unverified."))
    if snippet_blocked:
        findings.append(_finding("snippet-directives", "medium", "fail", "A supplied robots directive blocks text snippets.", "Remove nosnippet or max-snippet:0 only if snippets are intended, then verify the live response."))
    elif headers_snapshot is None:
        findings.append(_finding("snippet-directives", "info", "unknown", "No snippet-blocking meta directive was observed, but response headers were not supplied.", "Capture X-Robots-Tag headers to complete the snippet-directive check."))
    else:
        findings.append(_finding("snippet-directives", "info", "pass", "No recognized snippet-blocking directive appears in the supplied HTML or response headers.", "Treat this as directive evidence only, not proof of a rendered search snippet."))

    private_resolution_base = private_source
    if parser.base_href:
        candidate_base = normalize_url(parser.base_href, private_source, keep_query=True)
        if candidate_base:
            private_resolution_base = candidate_base
    canonical_private_urls = [normalize_url(item, private_resolution_base, keep_query=True) for item in parser.canonical_hrefs]
    valid_private_canonicals = [item for item in canonical_private_urls if item]
    valid_canonicals = [sanitize_url(item) for item in valid_private_canonicals]
    valid_canonicals = [item for item in valid_canonicals if item]
    if not parser.canonical_hrefs:
        findings.append(_finding("canonical", "medium", "fail", "No canonical link element was observed in the HTML snapshot.", "Add one intentional canonical URL when appropriate for this page."))
    elif len(parser.canonical_hrefs) > 1:
        findings.append(_finding("canonical", "high", "fail", f"{len(parser.canonical_hrefs)} canonical link elements were observed.", "Keep one unambiguous canonical link and remove conflicting duplicates."))
    elif not valid_private_canonicals:
        findings.append(_finding("canonical", "high", "fail", "The observed canonical href could not be resolved to an absolute HTTP(S) URL.", "Use a valid absolute HTTP(S) canonical URL."))
    else:
        private_canonical = valid_private_canonicals[0]
        safe_canonical = sanitize_url(private_canonical) or "[invalid]"
        if _origin(private_canonical) != _origin(private_source):
            findings.append(_finding("canonical", "high", "fail", f"The canonical resolves to a different origin: {safe_canonical}", "Confirm the cross-origin canonical is intentional; otherwise point it to the preferred same-origin URL."))
        elif private_canonical != private_source:
            findings.append(_finding("canonical", "medium", "fail", f"A private query-aware comparison found that the canonical differs from the supplied source URL; sanitized canonical: {safe_canonical}", "Confirm the preferred URL and align internal links, redirects, and canonical markup."))
        else:
            findings.append(_finding("canonical", "info", "pass", f"One self-referencing canonical resolves to {safe_canonical} under a private query-aware comparison.", "Verify the same value in the live rendered response before release."))

    nonempty_titles = [item for item in parser.titles if item]
    if not nonempty_titles:
        findings.append(_finding("title", "high", "fail", "No non-empty title was observed.", "Add one concise, page-specific title element."))
    elif len(parser.titles) > 1:
        findings.append(_finding("title", "medium", "fail", f"{len(parser.titles)} title elements were observed.", "Keep one non-empty title element."))
    else:
        length = len(nonempty_titles[0])
        severity = "low" if length < 15 or length > 70 else "info"
        status = "fail" if severity == "low" else "pass"
        findings.append(_finding("title", severity, status, f"One non-empty title was observed ({length} characters).", "Review clarity and likely truncation in context; length is a heuristic, not a ranking rule."))

    nonempty_descriptions = [item for item in parser.descriptions if item]
    if not nonempty_descriptions:
        findings.append(_finding("meta-description", "medium", "fail", "No non-empty meta description was observed.", "Add a page-specific description if a controlled summary is useful."))
    elif len(parser.descriptions) > 1:
        findings.append(_finding("meta-description", "medium", "fail", f"{len(parser.descriptions)} meta descriptions were observed.", "Keep one non-empty meta description."))
    else:
        length = len(nonempty_descriptions[0])
        severity = "low" if length < 50 or length > 180 else "info"
        status = "fail" if severity == "low" else "pass"
        findings.append(_finding("meta-description", severity, status, f"One non-empty meta description was observed ({length} characters).", "Review relevance and likely truncation in context; length is a heuristic, not a ranking rule."))

    nonempty_h1s = [item for item in parser.h1s if item]
    if not nonempty_h1s:
        findings.append(_finding("h1", "medium", "fail", "No non-empty H1 was observed.", "Add a visible primary heading that states the page topic."))
    elif len(nonempty_h1s) > 1:
        findings.append(_finding("h1", "low", "fail", f"{len(nonempty_h1s)} non-empty H1 elements were observed.", "Review heading hierarchy and keep the primary page topic unambiguous."))
    else:
        findings.append(_finding("h1", "info", "pass", f"One non-empty H1 was observed ({len(nonempty_h1s[0])} characters).", "Confirm that its wording accurately represents the page."))

    jsonld_types: set[str] = set()
    jsonld_invalid = 0
    jsonld_truncated = parser.jsonld_block_truncated
    for block in parser.jsonld_blocks:
        try:
            parsed = json.loads(block)
        except (json.JSONDecodeError, ValueError, RecursionError):
            jsonld_invalid += 1
            continue
        types, truncated = extract_jsonld_types(parsed)
        jsonld_types.update(types)
        jsonld_truncated = jsonld_truncated or truncated
    if jsonld_invalid:
        findings.append(_finding("jsonld-parse", "medium", "fail", f"{jsonld_invalid} of {len(parser.jsonld_blocks)} inspected JSON-LD blocks could not be parsed.", "Repair invalid JSON-LD syntax and validate the intended structured data."))
    elif parser.jsonld_blocks:
        findings.append(_finding("jsonld-parse", "info", "pass", f"{len(parser.jsonld_blocks)} JSON-LD blocks parsed; {len(jsonld_types)} safe @type values were observed.", "Validate required properties for the intended schema types with an appropriate current validator."))
    else:
        findings.append(_finding("jsonld-parse", "info", "unknown", "No JSON-LD block was observed in the HTML snapshot.", "Add structured data only when it accurately represents visible page content and has a supported use case."))
    if parser.jsonld_overflow or jsonld_truncated:
        findings.append(_finding("jsonld-limits", "low", "unknown", "JSON-LD inspection reached a configured block, block-size, or node limit.", "Review the oversized structured data separately or reduce it before rerunning."))

    robots = evaluate_robots(robots_snapshot, crawler, private_source)
    if robots["status"] == "blocked":
        findings.append(_finding("robots-access", "high", "fail", f"The supplied robots snapshot blocks the source path for {crawler} by its longest matching rule.", "Change the selected-crawler rule only if crawling should be allowed, then verify the live robots response."))
    elif robots["status"] == "allowed":
        findings.append(_finding("robots-access", "info", "pass", f"The supplied robots snapshot allows the source path for {crawler} under the implemented rule selection.", "Treat this as snapshot evidence; verify the live robots response and crawler behavior separately."))
    elif robots_snapshot is None:
        findings.append(_finding("robots-access", "info", "unknown", "No robots.txt snapshot was supplied.", "Supply the relevant robots.txt response to evaluate the selected crawler."))
    else:
        findings.append(_finding("robots-access", "info", "unknown", f"The supplied robots snapshot could not be conclusively evaluated: {robots['reason']}.", "Review the selected crawler rules within the documented limits, correct malformed percent encoding when present, and rerun the snapshot audit."))

    same_origin_links: set[str] = set()
    cta_texts: List[str] = []
    for href, text in parser.links:
        resolved = normalize_url(href, private_resolution_base, keep_query=True)
        if resolved and _origin(resolved) == _origin(private_source):
            same_origin_links.add(resolved)
        if text:
            cta_texts.append(text.lower())
    cta_texts.extend(item.lower() for item in parser.button_texts if item)
    if same_origin_links:
        findings.append(_finding("internal-links", "info", "pass", f"{len(same_origin_links)} unique same-origin HTTP(S) links were observed.", "Review whether the links support discovery of the page's important next steps."))
    else:
        findings.append(_finding("internal-links", "low", "fail", "No same-origin HTTP(S) links were observed.", "Add relevant internal links if this page should connect users and crawlers to other site content."))
    if parser.link_overflow:
        findings.append(_finding("link-limits", "low", "unknown", "Link inspection reached the configured tracking limit.", "Review the unusually large link set separately or reduce the snapshot before rerunning."))

    expected_private = [normalize_url(item, private_source, keep_query=True) for item in expected_links]
    expected_private = [item for item in expected_private if item and _origin(item) == _origin(private_source)]
    if expected_links and len(expected_private) != len(expected_links):
        raise AuditInputError("Every expected link must resolve to a same-origin HTTP(S) URL")
    missing_expected = [item for item in expected_private if item not in same_origin_links]
    if expected_private and missing_expected:
        findings.append(_finding("expected-links", "medium", "fail", f"{len(missing_expected)} of {len(expected_private)} supplied expected same-origin links were not observed under private query-aware comparison.", "Add the missing relevant links or revise the expected-link list to match the page goal."))
    elif expected_private:
        findings.append(_finding("expected-links", "info", "pass", f"All {len(expected_private)} supplied expected same-origin links were observed under private query-aware comparison.", "Confirm the destinations and anchor context in the live rendered page."))
    else:
        findings.append(_finding("expected-links", "info", "unknown", "No page-specific expected links were supplied.", "Supply expected paths when a page goal depends on particular internal destinations."))

    terms = [item.strip().lower() for item in cta_terms] if cta_terms else list(DEFAULT_CTA_TERMS)
    cta_hits = sum(1 for text in cta_texts if any(term in text for term in terms))
    if cta_hits:
        basis = "supplied" if cta_terms else "built-in generic"
        findings.append(_finding("cta-presence", "info", "pass", f"{cta_hits} CTA-like controls matched the {basis} term set.", "Confirm that the visible action and destination fit the page's actual user goal."))
    elif cta_terms:
        findings.append(_finding("cta-presence", "low", "fail", "No control text matched the supplied CTA terms.", "Add a relevant visible action or revise the term set if the page has a different goal."))
    else:
        findings.append(_finding("cta-presence", "info", "unknown", "No control matched the built-in generic CTA terms; page-specific CTA terms were not supplied.", "Supply terms aligned with the page goal before treating CTA presence as a requirement."))

    unknowns = [
        "Actual indexing or index coverage in any search engine",
        "Search rankings or search-result appearance",
        "AI-system citations or answer inclusion",
        "Keyword volume, demand, or competitiveness",
        "Live rendering, JavaScript behavior, and production runtime",
        "Analytics, conversions, leads, sales, and revenue impact",
    ]
    severity_counts = Counter(item["severity"] for item in findings if item["status"] == "fail")
    status_counts = Counter(item["status"] for item in findings)
    if severity_counts.get("high"):
        conclusion = "high-priority snapshot blockers observed"
    elif severity_counts.get("medium"):
        conclusion = "snapshot remediation recommended"
    elif status_counts.get("unknown"):
        conclusion = "no high-priority blocker observed; evidence remains incomplete"
    else:
        conclusion = "no high-priority blocker observed in supplied snapshots"

    return {
        "schema_version": "1.0",
        "tool": {"name": "pandorium-search-audit", "version": VERSION, "network_access": False},
        "input": {
            "source_url": safe_source,
            "crawler": crawler.lower(),
            "html_bytes": len(html.encode("utf-8")),
            "headers_supplied": headers_snapshot is not None,
            "robots_supplied": robots_snapshot is not None,
            "expected_link_count": len(expected_links),
            "cta_term_count": len(cta_terms),
        },
        "summary": {
            "conclusion": conclusion,
            "finding_count": len(findings),
            "status_counts": dict(sorted(status_counts.items())),
            "failed_severity_counts": dict(sorted(severity_counts.items())),
        },
        "observations": {
            "response_status": status_code,
            "recognized_meta_directives": meta_directives,
            "recognized_header_directives": header_directives,
            "canonical_urls": valid_canonicals[:2],
            "title_count": len(parser.titles),
            "meta_description_count": len(parser.descriptions),
            "h1_count": len(parser.h1s),
            "jsonld_block_count": len(parser.jsonld_blocks),
            "jsonld_types": sorted(jsonld_types)[:64],
            "same_origin_link_count": len(same_origin_links),
            "robots": robots,
        },
        "findings": findings,
        "explicit_unknowns": unknowns,
        "limits": {
            "html_bytes": MAX_HTML_BYTES,
            "headers_bytes": MAX_HEADERS_BYTES,
            "robots_bytes": MAX_ROBOTS_BYTES,
            "jsonld_blocks": MAX_JSONLD_BLOCKS,
            "tracked_links": MAX_LINKS_TRACKED,
            "output_bytes": MAX_OUTPUT_BYTES,
        },
    }


def render_markdown(result: Dict[str, Any]) -> str:
    def safe(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = [
        "# Search snapshot audit",
        "",
        f"Source: `{safe(result['input']['source_url'])}`",
        f"Conclusion: {safe(result['summary']['conclusion'])}",
        "",
        "This report covers supplied snapshots only. It made no network requests and did not execute JavaScript or forms.",
        "",
        "## Findings",
        "",
        "| Severity | Status | Check | Evidence | Next step |",
        "| --- | --- | --- | --- | --- |",
    ]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings = sorted(result["findings"], key=lambda item: (order[item["severity"]], item["id"]))
    for item in findings:
        lines.append(
            f"| {safe(item['severity'])} | {safe(item['status'])} | {safe(item['id'])} | "
            f"{safe(item['evidence'])} | {safe(item['next_step'])} |"
        )
    lines.extend(["", "## Explicit unknowns", ""])
    lines.extend(f"- {safe(item)}" for item in result["explicit_unknowns"])
    lines.extend(["", "No universal SEO/GEO score or ranking guarantee is implied.", ""])
    return "\n".join(lines)


def _bounded_serializations(result: Dict[str, Any]) -> Tuple[str, str]:
    json_text = json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    report_text = render_markdown(result)
    if len(json_text.encode("utf-8")) > MAX_OUTPUT_BYTES or len(report_text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise AuditInputError("Rendered output exceeded the configured size limit")
    return json_text, report_text


def _write_output(path: str, content: str) -> None:
    target = Path(path)
    target.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, help="UTF-8 HTML snapshot path")
    parser.add_argument("--url", required=True, help="Canonical source URL; credentials, query, and fragment are removed from output")
    parser.add_argument("--headers", help="Optional UTF-8 raw or JSON response-header snapshot")
    parser.add_argument("--robots", help="Optional UTF-8 robots.txt snapshot")
    parser.add_argument("--crawler", default="googlebot", help="Selected crawler token (default: googlebot)")
    parser.add_argument("--expected-link", action="append", default=[], help="Expected same-origin path or URL; repeatable")
    parser.add_argument("--cta-term", action="append", default=[], help="Page-relevant CTA term; repeatable")
    parser.add_argument("--json-out", help="Write JSON to this path instead of standard output")
    parser.add_argument("--report-out", help="Write the Markdown report to this path")
    parser.add_argument("--version", action="version", version=VERSION)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        html = _read_bounded(Path(args.html), MAX_HTML_BYTES, "HTML")
        headers = _read_bounded(Path(args.headers), MAX_HEADERS_BYTES, "Header") if args.headers else None
        robots = _read_bounded(Path(args.robots), MAX_ROBOTS_BYTES, "Robots") if args.robots else None
        result = audit(html, args.url, headers, robots, args.crawler, args.expected_link, args.cta_term)
        json_text, report_text = _bounded_serializations(result)
        if args.json_out:
            _write_output(args.json_out, json_text)
        else:
            sys.stdout.write(json_text)
        if args.report_out:
            _write_output(args.report_out, report_text)
        return 0
    except (AuditInputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
