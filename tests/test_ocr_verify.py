from scripts.ocr_verify import quality_metrics, sample_page_indices, write_summary


def test_sample_page_indices_even_distribution() -> None:
    indices = sample_page_indices(330, 10)

    assert len(indices) == 10
    assert indices[0] == 0
    assert all(0 <= index < 330 for index in indices)
    gaps = [indices[index + 1] - indices[index] for index in range(len(indices) - 1)]
    assert max(gaps) - min(gaps) <= 1


def test_sample_page_indices_small_doc() -> None:
    assert sample_page_indices(5, 10) == [0, 1, 2, 3, 4]


def test_sample_page_indices_handles_empty_inputs() -> None:
    assert sample_page_indices(0, 10) == []
    assert sample_page_indices(10, 0) == []


def test_quality_metrics_pass() -> None:
    text = "안녕하세요. 이 문서는 보험 약관에 관한 내용입니다. 보상 기준과 지급 조건을 설명합니다." * 5

    metrics = quality_metrics(text)

    assert metrics["grade"] == "PASS"
    assert metrics["korean_ratio"] > 0.35


def test_quality_metrics_empty() -> None:
    metrics = quality_metrics("")

    assert metrics["grade"] == "FAIL"
    assert metrics["chars"] == 0


def test_write_summary_includes_engine_errors(tmp_path) -> None:
    output_path = tmp_path / "summary.txt"

    write_summary(
        output_path,
        {"실무가이드": {"tesseract": []}},
        {"실무가이드": 330},
        sample_count=1,
        dpi=150,
        engine_errors={("실무가이드", "tesseract"): "RuntimeError: tesseract 바이너리가 PATH에 없습니다."},
    )

    summary = output_path.read_text(encoding="utf-8")
    assert "[tesseract]" in summary
    assert "ERROR: RuntimeError: tesseract 바이너리가 PATH에 없습니다." in summary
