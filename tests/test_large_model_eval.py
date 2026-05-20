from scripts.eval_large_model_rag import (
    _contains_all,
    _contains_any,
    _output_health_ok,
    _regex_all,
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
