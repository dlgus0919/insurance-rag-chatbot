from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


LAUNCHER = Path("ops/bin/insurance-rag-desktop-launcher")
CANDIDATE_GUI = Path("ops/bin/insurance-rag-rule-candidate-review-gui")


def _executable(path: Path) -> None:
    path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _launcher_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("ontology", "rule_candidate", "rule_review"):
        _executable(fake_bin / name)
    model_dir = tmp_path / "aiops/llm/models/gpt-oss-20b"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    template_dir = tmp_path / "aiops/llm/templates"
    template_dir.mkdir(parents=True)
    (template_dir / "gpt_oss_harmony.jinja").write_text("template", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "AI_OPS_ROOT": str(tmp_path / "aiops"),
            "AI_OPS_BIN_DIR": str(fake_bin),
            "INSURANCE_RAG_PROJECT_DIR": str(Path.cwd()),
            "INSURANCE_RAG_PYTHON": sys.executable,
            "INSURANCE_RAG_ONTOLOGY_REVIEW_GUI": str(fake_bin / "ontology"),
            "INSURANCE_RAG_RULE_CANDIDATE_REVIEW_GUI": str(fake_bin / "rule_candidate"),
            "INSURANCE_RAG_RULE_REVIEW_GUI": str(fake_bin / "rule_review"),
            "SGLANG_BASE_URL": "http://127.0.0.1:9/v1",
            "VLLM_BASE_URL": "http://127.0.0.1:9/v1",
            "TRTLLM_BASE_URL": "http://127.0.0.1:9/v1",
            "OLLAMA_HOST": "http://127.0.0.1:9",
        }
    )
    return env


def test_launcher_primary_choices_hide_model_rows(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--choices"],
        check=True,
        text=True,
        capture_output=True,
        env=_launcher_env(tmp_path),
    )

    assert "ontology|review|" in result.stdout
    assert "rules|candidate|" in result.stdout
    assert "rules|review|active" in result.stdout
    assert "model|select|available" in result.stdout
    assert "start|sglang|gpt-oss-20b" not in result.stdout
    if "current|" in result.stdout:
        assert result.stdout.index("model|select|available") < result.stdout.index("current|")


def test_launcher_model_choices_show_available_models(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--model-choices"],
        check=True,
        text=True,
        capture_output=True,
        env=_launcher_env(tmp_path),
    )

    assert "start|sglang|gpt-oss-20b" in result.stdout


def test_rule_candidate_gui_wrapper_dry_run() -> None:
    result = subprocess.run(
        ["bash", str(CANDIDATE_GUI), "--dry-run"],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "INSURANCE_RAG_PROJECT_DIR": str(Path.cwd()), "INSURANCE_RAG_PYTHON": sys.executable},
    )

    assert "candidate_count=" in result.stdout
