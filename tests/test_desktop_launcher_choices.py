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


def _launcher_env_with_ollama_state(
    tmp_path: Path,
    *,
    installed_models: str,
    running_models: str,
) -> dict[str, str]:
    env = _launcher_env(tmp_path)
    curl_path = Path(env["AI_OPS_BIN_DIR"]) / "curl"
    curl_path.write_text(
        """#!/usr/bin/env bash
url="${!#}"
case "$url" in
  */api/tags) printf '%s' "${FAKE_OLLAMA_TAGS:-}" ;;
  */api/ps) printf '%s' "${FAKE_OLLAMA_PS:-}" ;;
esac
""",
        encoding="utf-8",
    )
    curl_path.chmod(curl_path.stat().st_mode | stat.S_IXUSR)
    env.update(
        {
            "PATH": f"{curl_path.parent}:{env['PATH']}",
            "FAKE_OLLAMA_TAGS": installed_models,
            "FAKE_OLLAMA_PS": running_models,
        }
    )
    return env


def _primary_dialog_output(
    tmp_path: Path,
    *,
    sglang_model: str = "",
    vllm_model: str = "",
    trtllm_model: str = "",
    ollama_model: str = "",
) -> str:
    fake_bin = tmp_path / "dialog-bin"
    fake_bin.mkdir()
    zenity_path = fake_bin / "zenity"
    zenity_path.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    zenity_path.chmod(zenity_path.stat().st_mode | stat.S_IXUSR)

    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'main "$@"' in source
    source = source.rsplit('main "$@"', 1)[0] + 'choose_action "$@"\n'
    result = subprocess.run(
        [
            "bash",
            "-s",
            "--",
            sglang_model,
            vllm_model,
            trtllm_model,
            ollama_model,
        ],
        check=True,
        text=True,
        input=source,
        capture_output=True,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    return result.stdout


def test_launcher_primary_choices_hide_model_rows(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--choices"],
        check=True,
        text=True,
        capture_output=True,
        env=_launcher_env(tmp_path),
    )

    assert "ontology|review|" not in result.stdout
    assert "rules|candidate|" not in result.stdout
    assert "rules|review|active" not in result.stdout
    assert "model|select|available" in result.stdout
    assert "start|sglang|gpt-oss-20b" not in result.stdout
    if "current|" in result.stdout:
        assert result.stdout.index("model|select|available") < result.stdout.index("current|")


def test_launcher_primary_dialog_height_fits_default_choices() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "row_count * 44 + 250" in source
    assert "window_height < 460" in source


def test_launcher_primary_dialog_shows_only_stopped_app_status(tmp_path: Path) -> None:
    output = _primary_dialog_output(tmp_path)

    assert "앱 상태: stopped" in output
    assert "SGLang:" not in output
    assert "vLLM:" not in output
    assert "TensorRT-LLM:" not in output
    assert "Ollama:" not in output


def test_launcher_primary_dialog_summarizes_active_model_in_one_status_line(tmp_path: Path) -> None:
    output = _primary_dialog_output(
        tmp_path,
        sglang_model="qwen3-next-80b-a3b-instruct-fp8",
    )

    assert "앱 상태: SGLang (qwen3-next-80b-a3b-instruct-fp8) 실행 중" in output
    assert "앱: running" not in output
    assert "SGLang:" not in output


def test_desktop_launcher_hides_admin_review_choices() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "온톨로지 승인 검토" not in source
    assert "액티브 룰 신규 후보" not in source
    assert "액티브 룰 검토" not in source


def test_launcher_model_choices_show_available_models(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--model-choices"],
        check=True,
        text=True,
        capture_output=True,
        env=_launcher_env(tmp_path),
    )

    assert "start|sglang|gpt-oss-20b" in result.stdout


def test_launcher_does_not_keep_installed_but_unloaded_ollama_model(tmp_path: Path) -> None:
    env = _launcher_env_with_ollama_state(
        tmp_path,
        installed_models='{"models":[{"name":"llama-3.3-70b-instruct-q4-k-m:latest"}]}',
        running_models='{"models":[]}',
    )

    result = subprocess.run(
        ["bash", str(LAUNCHER), "--choices"],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )

    assert "current|ollama|" not in result.stdout


def test_launcher_keeps_ollama_model_reported_by_running_endpoint(tmp_path: Path) -> None:
    env = _launcher_env_with_ollama_state(
        tmp_path,
        installed_models='{"models":[{"name":"exaone3.5:7.8b"}]}',
        running_models='{"models":[{"name":"llama-3.3-70b-instruct-q4-k-m:latest"}]}',
    )

    result = subprocess.run(
        ["bash", str(LAUNCHER), "--choices"],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )

    assert "current|ollama|llama-3.3-70b-instruct-q4-k-m:latest" in result.stdout


def test_launcher_does_not_auto_open_ontology_preflight() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "INSURANCE_RAG_SKIP_ONTOLOGY_PREFLIGHT" not in source
    assert '[[ "$mode" == "ontology" ]]' in source


def test_rule_candidate_gui_wrapper_dry_run() -> None:
    result = subprocess.run(
        ["bash", str(CANDIDATE_GUI), "--dry-run"],
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "INSURANCE_RAG_PROJECT_DIR": str(Path.cwd()), "INSURANCE_RAG_PYTHON": sys.executable},
    )

    assert "candidate_count=" in result.stdout
