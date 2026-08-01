from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from utils.config_handler import (
    PROJECT_ROOT,
    ChromaConfig,
    chroma_conf,
    load_chroma_config,
    load_prompts_config,
)
from utils.path_tool import get_abs_path


def valid_chroma_config() -> dict[str, object]:
    return {
        "collection_name": "agent",
        "persist_directory": "chroma_db",
        "k": 3,
        "candidate_k": 8,
        "data_path": "data",
        "md5_hex_store": "md5.txt",
        "allow_knowledge_file_type": ["txt", "pdf"],
        "chunk_size": 200,
        "chunk_overlap": 20,
        "separators": ["\n\n", "。", ""],
        "retrieval_type": "hybrid",
        "bm25_weight": 0.4,
        "vector_weight": 0.6,
        "rerank_enabled": True,
        "rerank_top_k": 3,
        "low_confidence_threshold": 0.28,
    }


class ConfigHandlerTest(unittest.TestCase):
    def test_repository_config_is_valid_and_paths_are_absolute(self) -> None:
        self.assertEqual(
            chroma_conf["persist_directory"], str(PROJECT_ROOT / "chroma_db")
        )
        self.assertEqual(chroma_conf["data_path"], str(PROJECT_ROOT / "data"))
        self.assertEqual(chroma_conf["md5_hex_store"], str(PROJECT_ROOT / "md5.txt"))

    def test_chroma_schema_rejects_unknown_and_invalid_values(self) -> None:
        invalid_configs = []
        for key, value in (
            ("chunk_overlap", 200),
            ("candidate_k", 2),
            ("rerank_top_k", 9),
            ("low_confidence_threshold", 1.1),
        ):
            config = valid_chroma_config()
            config[key] = value
            invalid_configs.append(config)

        unknown = valid_chroma_config()
        unknown["typo_setting"] = True
        invalid_configs.append(unknown)

        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValidationError):
                ChromaConfig.model_validate(config)

    def test_loader_resolves_paths_against_explicit_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "data").mkdir()
            config_path = project_root / "chroma.yml"
            config_path.write_text(
                yaml.safe_dump(valid_chroma_config(), allow_unicode=True),
                encoding="utf-8",
            )

            loaded = load_chroma_config(config_path.name, project_root=project_root)

        self.assertEqual(
            Path(loaded["persist_directory"]), (project_root / "chroma_db").resolve()
        )
        self.assertEqual(Path(loaded["data_path"]), (project_root / "data").resolve())
        self.assertEqual(
            Path(loaded["md5_hex_store"]), (project_root / "md5.txt").resolve()
        )

    def test_prompt_loader_rejects_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_path = project_root / "prompts.yml"
            config_path.write_text(
                "main_prompt_path: missing-main.txt\n"
                "rag_summarize_prompt_path: missing-rag.txt\n"
                "report_prompt_path: missing-report.txt\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValidationError):
                load_prompts_config(config_path, project_root=project_root)

    def test_safe_loader_rejects_python_object_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_path = project_root / "chroma.yml"
            config_path.write_text(
                "collection_name: !!python/object/apply:os.system ['echo unsafe']\n",
                encoding="utf-8",
            )

            with self.assertRaises(yaml.YAMLError):
                load_chroma_config(config_path, project_root=project_root)

    def test_get_abs_path_is_independent_from_current_working_directory(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                resolved = get_abs_path("chroma_db")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(resolved, str(PROJECT_ROOT / "chroma_db"))


if __name__ == "__main__":
    unittest.main()
