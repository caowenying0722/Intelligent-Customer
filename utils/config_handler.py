from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ConfigModel = TypeVar("ConfigModel", bound=BaseModel)


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RagConfig(StrictConfigModel):
    chat_model_name: str = Field(min_length=1)
    chat_base_url: AnyHttpUrl
    embedding_model_path: str = Field(min_length=1)


class ChromaConfig(StrictConfigModel):
    collection_name: str = Field(min_length=1)
    storage_mode: Literal["embedded"] = "embedded"
    persist_directory: Path
    k: int = Field(ge=1, le=100)
    candidate_k: int = Field(ge=1, le=200)
    data_path: Path
    md5_hex_store: Path
    allow_knowledge_file_type: list[Literal["txt", "pdf"]] = Field(min_length=1)
    chunk_size: int = Field(ge=1, le=100_000)
    chunk_overlap: int = Field(ge=0)
    separators: list[str] = Field(min_length=1)
    retrieval_type: Literal["vector", "hybrid"]
    fusion_strategy: Literal["weighted", "rrf"] = "weighted"
    rrf_k: int = Field(default=60, ge=1, le=1000)
    bm25_weight: float = Field(ge=0, le=1)
    vector_weight: float = Field(ge=0, le=1)
    rerank_enabled: bool
    rerank_top_k: int = Field(ge=1, le=200)
    low_confidence_threshold: float = Field(ge=0, le=1)

    @field_validator("data_path")
    @classmethod
    def require_data_directory(cls, value: Path) -> Path:
        if not value.is_dir():
            raise ValueError(f"data_path must point to an existing directory: {value}")
        return value

    @model_validator(mode="after")
    def validate_retrieval_bounds(self) -> ChromaConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.candidate_k < self.k:
            raise ValueError("candidate_k must be greater than or equal to k")
        if self.rerank_top_k > self.candidate_k:
            raise ValueError("rerank_top_k must not exceed candidate_k")
        if self.retrieval_type == "hybrid" and (
            self.bm25_weight + self.vector_weight <= 0
        ):
            raise ValueError("hybrid retrieval weights must have a positive sum")
        return self


class PromptsConfig(StrictConfigModel):
    main_prompt_path: Path
    rag_summarize_prompt_path: Path
    report_prompt_path: Path

    @field_validator(
        "main_prompt_path", "rag_summarize_prompt_path", "report_prompt_path"
    )
    @classmethod
    def require_prompt_file(cls, value: Path) -> Path:
        if not value.is_file():
            raise ValueError(f"prompt path must point to an existing file: {value}")
        return value


class AgentConfig(StrictConfigModel):
    external_data_path: Path

    @field_validator("external_data_path")
    @classmethod
    def require_external_data_file(cls, value: Path) -> Path:
        if not value.is_file():
            raise ValueError(
                f"external_data_path must point to an existing file: {value}"
            )
        return value


def _resolve_project_paths(
    raw_config: Mapping[str, Any],
    path_fields: tuple[str, ...],
    project_root: Path,
) -> dict[str, Any]:
    resolved_config = dict(raw_config)
    for field_name in path_fields:
        value = resolved_config.get(field_name)
        if value is None:
            continue
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = project_root / path
        resolved_config[field_name] = path.resolve()
    return resolved_config


def _load_yaml_model(
    model_type: type[ConfigModel],
    config_path: str | Path,
    *,
    encoding: str,
    project_root: str | Path,
    path_fields: tuple[str, ...] = (),
) -> ConfigModel:
    root = Path(project_root).expanduser().resolve()
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    with path.open("r", encoding=encoding) as config_file:
        raw_config = yaml.safe_load(config_file)
    if not isinstance(raw_config, Mapping):
        raise TypeError(f"YAML config root must be a mapping: {path}")
    resolved_config = _resolve_project_paths(raw_config, path_fields, root)
    return model_type.model_validate(resolved_config)


def _dump_compatible(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def load_rag_settings(
    config_path: str | Path = PROJECT_ROOT / "config" / "rag.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> RagConfig:
    return _load_yaml_model(
        RagConfig,
        config_path,
        encoding=encoding,
        project_root=project_root,
    )


def load_chroma_settings(
    config_path: str | Path = PROJECT_ROOT / "config" / "chroma.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> ChromaConfig:
    return _load_yaml_model(
        ChromaConfig,
        config_path,
        encoding=encoding,
        project_root=project_root,
        path_fields=("persist_directory", "data_path", "md5_hex_store"),
    )


def load_prompts_settings(
    config_path: str | Path = PROJECT_ROOT / "config" / "prompts.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> PromptsConfig:
    return _load_yaml_model(
        PromptsConfig,
        config_path,
        encoding=encoding,
        project_root=project_root,
        path_fields=(
            "main_prompt_path",
            "rag_summarize_prompt_path",
            "report_prompt_path",
        ),
    )


def load_agent_settings(
    config_path: str | Path = PROJECT_ROOT / "config" / "agent.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> AgentConfig:
    return _load_yaml_model(
        AgentConfig,
        config_path,
        encoding=encoding,
        project_root=project_root,
        path_fields=("external_data_path",),
    )


def load_rag_config(
    config_path: str | Path = PROJECT_ROOT / "config" / "rag.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    return _dump_compatible(
        load_rag_settings(
            config_path,
            encoding=encoding,
            project_root=project_root,
        )
    )


def load_chroma_config(
    config_path: str | Path = PROJECT_ROOT / "config" / "chroma.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    return _dump_compatible(
        load_chroma_settings(
            config_path,
            encoding=encoding,
            project_root=project_root,
        )
    )


def load_prompts_config(
    config_path: str | Path = PROJECT_ROOT / "config" / "prompts.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    return _dump_compatible(
        load_prompts_settings(
            config_path,
            encoding=encoding,
            project_root=project_root,
        )
    )


def load_agent_config(
    config_path: str | Path = PROJECT_ROOT / "config" / "agent.yml",
    *,
    encoding: str = "utf-8",
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    return _dump_compatible(
        load_agent_settings(
            config_path,
            encoding=encoding,
            project_root=project_root,
        )
    )


rag_config = load_rag_settings()
chroma_config = load_chroma_settings()
prompts_config = load_prompts_settings()
agent_config = load_agent_settings()

rag_conf = _dump_compatible(rag_config)
chroma_conf = _dump_compatible(chroma_config)
prompts_conf = _dump_compatible(prompts_config)
agent_conf = _dump_compatible(agent_config)


if __name__ == "__main__":
    print(agent_conf["external_data_path"])
