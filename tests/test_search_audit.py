from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "skills" / "pandorium-search-audit" / "scripts" / "search_audit.py"
PACK_PATH = ROOT / "scripts" / "package.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = load_module("pandorium_search_audit", HELPER_PATH)
PACK = load_module("pandorium_search_audit_pack_test", PACK_PATH)


GOOD_HTML = """<!doctype html>
<html><head>
<title>Practical Search Snapshot Review</title>
<meta name="description" content="A focused explanation of a public page, its search controls, and the next steps available to readers.">
<meta name="robots" content="index,follow,max-snippet:-1">
<link rel="canonical" href="/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":["WebPage","Organization"],"name":"Example"}</script>
</head><body><h1>Practical Search Snapshot Review</h1><a href="/contact/">Book a consultation</a></body></html>"""


class AuditTests(unittest.TestCase):
    def test_complete_snapshot_passes_core_checks(self):
        headers = "HTTP/1.1 200 OK\nContent-Type: text/html; charset=utf-8\nX-Robots-Tag: index, max-snippet:-1\n"
        robots = "User-agent: *\nDisallow:\n"
        result = AUDIT.audit(
            GOOD_HTML,
            "https://example.com/",
            headers,
            robots,
            expected_links=["/contact/"],
            cta_terms=["book"],
        )
        by_id = {item["id"]: item for item in result["findings"]}
        for check in ("response-status", "index-directives", "canonical", "title", "h1", "jsonld-parse", "robots-access", "expected-links", "cta-presence"):
            self.assertEqual(by_id[check]["status"], "pass", check)
        self.assertEqual(result["observations"]["jsonld_types"], ["Organization", "WebPage"])
        self.assertFalse(result["tool"]["network_access"])

    def test_blockers_are_evidence_labelled(self):
        html = """<html><head><meta name="robots" content="noindex,nosnippet"><link rel="canonical" href="https://other.example/page"><script type="application/ld+json">{bad</script></head><body></body></html>"""
        result = AUDIT.audit(
            html,
            "https://example.com/private",
            "HTTP/1.1 404 Not Found\nContent-Type: text/html\n",
            "User-agent: googlebot\nDisallow: /private\n",
        )
        by_id = {item["id"]: item for item in result["findings"]}
        for check in ("response-status", "index-directives", "canonical", "robots-access"):
            self.assertEqual(by_id[check]["status"], "fail", check)
            self.assertEqual(by_id[check]["severity"], "high", check)
        self.assertEqual(by_id["jsonld-parse"]["status"], "fail")

    def test_missing_optional_snapshots_remain_unknown(self):
        result = AUDIT.audit(GOOD_HTML, "https://example.com/")
        by_id = {item["id"]: item for item in result["findings"]}
        self.assertEqual(by_id["response-status"]["status"], "unknown")
        self.assertEqual(by_id["robots-access"]["status"], "unknown")
        self.assertEqual(by_id["snippet-directives"]["status"], "unknown")
        self.assertIn("Actual indexing", result["explicit_unknowns"][0])

    def test_output_redacts_credentials_queries_and_embedded_personal_data(self):
        html = """<html><head><title>Owner person@example.com +1 202 555 0199</title><meta name="description" content="Contact person@example.com"><link rel="canonical" href="/?token=secret#part"><script type="application/ld+json">{"@type":"Person","email":"person@example.com","secret":"do-not-print"}</script></head><body><h1>Contact</h1><a href="mailto:person@example.com">Email person@example.com</a></body></html>"""
        result = AUDIT.audit(html, "https://user:password@example.com/?api_key=hidden#fragment", "HTTP/1.1 200 OK\nContent-Type: text/html\nX-Private: do-not-print\n")
        rendered = json.dumps(result, sort_keys=True)
        self.assertEqual(result["input"]["source_url"], "https://example.com/")
        for secret in ("user:password", "api_key", "hidden", "person@example.com", "202 555", "do-not-print"):
            self.assertNotIn(secret, rendered)

    def test_robots_longest_matching_allow_wins(self):
        robots = "User-agent: googlebot\nDisallow: /private\nAllow: /private/public\n"
        decision = AUDIT.evaluate_robots(robots, "googlebot", "https://example.com/private/public")
        self.assertEqual(decision["status"], "allowed")
        self.assertEqual(decision["matched_rule"], "allow")

    def test_robots_rules_can_match_query_without_exposing_it(self):
        robots = "User-agent: *\nDisallow: /*?preview=*\n"
        decision = AUDIT.evaluate_robots(robots, "googlebot", "https://example.com/page?preview=secret")
        self.assertEqual(decision["status"], "blocked")
        result = AUDIT.audit(GOOD_HTML, "https://example.com/?preview=secret", robots_snapshot=robots)
        self.assertNotIn("preview", json.dumps(result, sort_keys=True))

    def test_http2_pseudo_status_is_parsed(self):
        status, headers = AUDIT.parse_headers(":status: 200\ncontent-type: text/html\n")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], ["text/html"])

    def test_other_crawler_header_does_not_apply(self):
        directives = AUDIT.parse_x_robots(["facebookexternalhit: noindex", "max-snippet: 0"], "googlebot")
        self.assertEqual(directives, ["max-snippet:0"])

    def test_mixed_crawler_header_keeps_each_scope(self):
        value = "googlebot: index, bingbot: noindex, nosnippet"
        self.assertEqual(AUDIT.parse_x_robots([value], "googlebot"), ["index"])
        self.assertEqual(AUDIT.parse_x_robots([value], "bingbot"), ["noindex", "nosnippet"])

    def test_canonical_query_difference_cannot_pass_as_self_reference(self):
        html = GOOD_HTML.replace('href="/"', 'href="/?variant=canonical"')
        result = AUDIT.audit(html, "https://example.com/?variant=source")
        finding = next(item for item in result["findings"] if item["id"] == "canonical")
        self.assertEqual(finding["status"], "fail")
        self.assertNotIn("variant", json.dumps(result, sort_keys=True))

    def test_robots_percent_equivalence_and_dollar_specificity(self):
        encoded = AUDIT.evaluate_robots("User-agent: *\nDisallow: /%7Eprivate\n", "googlebot", "https://example.com/~private")
        self.assertEqual(encoded["status"], "blocked")
        tied = AUDIT.evaluate_robots("User-agent: *\nDisallow: /path$\nAllow: /path\n", "googlebot", "https://example.com/path")
        self.assertEqual(tied["status"], "allowed")
        self.assertEqual(tied["matched_rule_length"], len("/path"))

    def test_robots_unsupported_rule_is_unknown_not_allowed(self):
        malformed = AUDIT.evaluate_robots("User-agent: *\nDisallow: /bad%ZZ\n", "googlebot", "https://example.com/anything")
        self.assertEqual(malformed["status"], "unknown")
        audited = AUDIT.audit(GOOD_HTML, "https://example.com/anything", robots_snapshot="User-agent: *\nDisallow: /bad%ZZ\n")
        finding = next(item for item in audited["findings"] if item["id"] == "robots-access")
        self.assertEqual(finding["status"], "unknown")
        self.assertIn("supplied robots snapshot", finding["evidence"])
        self.assertNotIn("No robots.txt snapshot", finding["evidence"])
        self.assertNotIn("bad%ZZ", json.dumps(audited, sort_keys=True))
        oversized_pattern = "/" + ("a" * (AUDIT.MAX_ROBOTS_PATTERN_CHARS + 1))
        oversized = AUDIT.evaluate_robots(f"User-agent: *\nDisallow: {oversized_pattern}\n", "googlebot", "https://example.com/path")
        self.assertEqual(oversized["status"], "unknown")

    def test_robots_many_wildcards_use_bounded_matcher(self):
        pattern = "/" + ("*a" * 1000) + "*z$"
        outcome = AUDIT._bounded_robots_match(pattern, "/" + ("a" * 2000) + "y")
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome[0])

    def test_reader_rejects_non_regular_file_without_blocking(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "snapshot-dir"
            directory.mkdir()
            with self.assertRaises(AUDIT.AuditInputError):
                AUDIT._read_bounded(directory, 10, "HTML")
            if hasattr(os, "mkfifo"):
                fifo = Path(temporary) / "snapshot-fifo"
                os.mkfifo(fifo)
                with self.assertRaises(AUDIT.AuditInputError):
                    AUDIT._read_bounded(fifo, 10, "HTML")

    def test_cross_origin_expected_link_is_rejected(self):
        with self.assertRaises(AUDIT.AuditInputError):
            AUDIT.audit(GOOD_HTML, "https://example.com/", expected_links=["https://other.example/path"])

    def test_cli_rejects_oversized_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            html_path = Path(temporary) / "large.html"
            html_path.write_text("x" * (AUDIT.MAX_HTML_BYTES + 1), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HELPER_PATH), "--html", str(html_path), "--url", "https://example.com/"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("exceeds", result.stderr)

    def test_cli_contains_deep_jsonld_without_traceback_or_content_dump(self):
        with tempfile.TemporaryDirectory() as temporary:
            html_path = Path(temporary) / "deep-jsonld.html"
            private_marker = "private-jsonld-marker"
            nested = ("[" * 1200) + json.dumps(private_marker) + ("]" * 1200)
            html_path.write_text(
                f'<html><head><script type="application/ld+json">{nested}</script></head><body><h1>Example</h1></body></html>',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(HELPER_PATH), "--html", str(html_path), "--url", "https://example.com/"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn(private_marker, result.stdout)
            payload = json.loads(result.stdout)
            finding = next(item for item in payload["findings"] if item["id"] == "jsonld-parse")
            self.assertEqual(finding["status"], "fail")

    def test_cli_rejects_deep_json_headers_without_traceback_or_content_dump(self):
        with tempfile.TemporaryDirectory() as temporary:
            html_path = Path(temporary) / "page.html"
            headers_path = Path(temporary) / "deep-headers.json"
            private_marker = "private-header-marker"
            html_path.write_text(GOOD_HTML, encoding="utf-8")
            nested = ("[" * 1200) + json.dumps(private_marker) + ("]" * 1200)
            headers_path.write_text('{"headers":' + nested + "}", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER_PATH),
                    "--html",
                    str(html_path),
                    "--url",
                    "https://example.com/",
                    "--headers",
                    str(headers_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn(private_marker, result.stderr)
            self.assertIn("Header snapshot is not valid JSON", result.stderr)


class PackageTests(unittest.TestCase):
    def test_archives_are_allow_listed_and_reproducible(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_result = PACK.build_packages(Path(first))
            second_result = PACK.build_packages(Path(second))
            self.assertEqual(
                {key: value["sha256"] for key, value in first_result.items()},
                {key: value["sha256"] for key, value in second_result.items()},
            )
            for target, members in PACK.PACKAGE_FILES.items():
                self.assertEqual(first_result[target]["members"], sorted(members))
                self.assertFalse(any(name.startswith("tests/") or name.startswith("evidence/") for name in members))


if __name__ == "__main__":
    unittest.main()
