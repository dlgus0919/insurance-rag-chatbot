from src.parser.ocr_postprocess import normalize_ocr_text


def test_normalize_ocr_text_fixes_common_korean_suffix_errors() -> None:
    text = "반월판 연골올 제거해내논 수술올 말하다"

    assert normalize_ocr_text(text) == "반월판 연골을 제거해내는 수술을 말하다"


def test_normalize_ocr_text_fixes_signature_particle_error() -> None:
    assert normalize_ocr_text("피보험자 서명틀 대필") == "피보험자 서명을 대필"


def test_normalize_ocr_text_removes_repeated_noise_lines() -> None:
    text = "제2장 수술분류표 해설 73\n보험금 지급 기준\n\n\n{\n123\n다음 내용"

    normalized = normalize_ocr_text(text)

    assert "수술분류표 해설 73" not in normalized
    assert "{" not in normalized
    assert "123" not in normalized
    assert "보험금 지급 기준" in normalized
