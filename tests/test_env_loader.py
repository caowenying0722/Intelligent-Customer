from __future__ import annotations

import unittest

from utils.env_loader import clean_env_value


class EnvLoaderTest(unittest.TestCase):
    def test_plain_value_is_preserved(self) -> None:
        self.assertEqual(
            clean_env_value("https://api.deepseek.com/anthropic"),
            "https://api.deepseek.com/anthropic",
        )

    def test_markdown_link_value_uses_url(self) -> None:
        value = (
            "[https://api.deepseek.com/anthropic](https://api.deepseek.com/anthropic)"
        )

        self.assertEqual(clean_env_value(value), "https://api.deepseek.com/anthropic")


if __name__ == "__main__":
    unittest.main()
