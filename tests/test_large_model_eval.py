from scripts.eval_large_model_rag import (
    _contains_all,
    _contains_any,
    _output_health_ok,
    _regex_all,
    _required_groups_ok,
    CaseResult,
    ModelSpec,
    parse_args,
    parse_model_specs,
    result_to_dict,
    stop_model_server,
)


def test_large_eval_normalizes_unicode_hyphen_and_percent_spacing():
    answer = "전신성 복막염은 1‑3종: 2, 1‑5종: 3입니다. 보상률은 40 %에서 80 %로 바뀌었습니다."

    assert _regex_all(answer, [r"1-3종\s*[:=은는 ]*\s*2종?", r"1-5종\s*[:=은는 ]*\s*3종?"])
    assert _contains_all(answer, ["40%", "80%"])


def test_large_eval_detects_citation_only_answer_as_unhealthy():
    answer = "[출처: 심평원, p.812]\n[출처: 자사_SOL건강, p.268-269]"

    assert not _output_health_ok(answer)


def test_large_eval_detects_pad_repetition_as_unhealthy():
    answer = "<pad><pad><pad><pad><pad><pad><pad><pad>"

    assert not _output_health_ok(answer)


def test_large_eval_allows_required_any_after_normalization():
    answer = "기존에는 40 %만 보상했으나 이후 80 %까지 보상합니다."

    assert _contains_any(answer, ["40%"])


def test_large_eval_normalizes_korean_money_units():
    answer = "연간 한도는 3,500,000원이며 공제금액은 60,000원입니다."

    assert _contains_all(answer, ["350만원", "6만원"])


def test_large_eval_matches_korean_terms_with_spacing_variants():
    answer = "계약 전 알릴 의무를 위반했더라도 보험회사가 계약을 해지할 수 없는 경우입니다."

    assert _contains_all(answer, ["계약 전 알릴의무", "계약 해지"])


def test_large_eval_parses_provider_prefixed_model_specs():
    specs = parse_model_specs("gpt-oss-20b, vllm:gemma-4-31b-it-nvfp4, ollama:exaone3.5:7.8b")

    assert [spec.id for spec in specs] == [
        "sglang:gpt-oss-20b",
        "vllm:gemma-4-31b-it-nvfp4",
        "ollama:exaone3.5:7.8b",
    ]


def test_large_eval_required_groups_accepts_one_expression_per_group():
    answer = "계약 해지 후에는 비례분담 방식으로 처리합니다."

    assert _required_groups_ok(answer, [["해지", "계약 해지"], ["비례", "분담", "비례분담"]])
    assert not _required_groups_ok(answer, [["해지"], ["재가입"]])


def test_large_eval_stop_model_server_targets_provider_tmux_session(monkeypatch):
    calls = []
    monkeypatch.setattr("scripts.eval_large_model_rag.subprocess.run", lambda args, check=False: calls.append((args, check)))

    stop_model_server(ModelSpec(provider="sglang", model="gpt-oss-20b"))
    stop_model_server(ModelSpec(provider="vllm", model="gemma-4-31b-it-nvfp4"))
    stop_model_server(ModelSpec(provider="ollama", model="exaone3.5:7.8b"))

    assert calls == [
        (["tmux", "kill-session", "-t", "sglang-local"], False),
        (["tmux", "kill-session", "-t", "vllm-gemma4"], False),
    ]


def test_large_eval_accepts_v2_only_index_mode():
    args = parse_args(["--cases", "eval/policy_xlsx_qa.jsonl", "--models", "sglang:gpt-oss-20b", "--index-mode", "v2_only"])

    assert args.index_mode == "v2_only"


def test_large_eval_defaults_to_corrected_ocr_index_mode(monkeypatch):
    monkeypatch.delenv("LARGE_RAG_EVAL_INDEX_MODE", raising=False)

    args = parse_args(["--cases", "eval/policy_xlsx_qa.jsonl", "--models", "sglang:gpt-oss-20b"])

    assert args.index_mode == "v2_only"


def test_large_eval_result_serializes_index_mode():
    result = CaseResult(
        model="sglang:gpt-oss-20b",
        index_mode="v2_only",
        case_id="case-1",
        category="cat",
        question="question",
        passed=True,
        checks={"ok": True},
        failures=[],
        answer="answer",
        top_sources=[],
        timing={"elapsed_s": 1.0},
    )

    assert result_to_dict(result)["index_mode"] == "v2_only"
