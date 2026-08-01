from __future__ import annotations

import unittest
from pathlib import Path

from scripts.scan_secrets import line_findings, redact


class SecretScanTest(unittest.TestCase):
    def test_detects_anthropic_token_assignment(self) -> None:
        token = "sk-" + "1234567890abcdef1234567890"
        findings = line_findings(Path("x.env"), 1, f"ANTHROPIC_AUTH_TOKEN={token}")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].secret, token)

    def test_ignores_placeholder_assignment(self) -> None:
        findings = line_findings(Path(".env.example"), 1, "ANTHROPIC_AUTH_TOKEN=your_anthropic_compatible_key_here")

        self.assertEqual(findings, [])

    def test_redacts_secret(self) -> None:
        token = "sk-" + "1234567890abcdef"
        self.assertEqual(redact(token), "sk-123...cdef")


if __name__ == "__main__":
    unittest.main()
