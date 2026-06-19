from __future__ import annotations

from src.retrieval.index_mode import resolve_effective_index_mode, resolve_index_profile


def test_user_facing_default_index_resolves_to_corrected_ocr():
    assert resolve_index_profile("default", user_facing=True) == "v2_only"
    assert resolve_index_profile("", user_facing=True) == "v2_only"
    assert resolve_index_profile("basic", user_facing=True) == "v2_only"


def test_effective_default_index_keeps_corrected_ocr_for_general_question():
    assert resolve_effective_index_mode("도수치료 보상 여부 알려줘", "default") == "v2_only"


def test_effective_default_index_routes_ocr_comparison_to_combined():
    assert resolve_effective_index_mode("원본 OCR과 보정본을 비교해줘", "default") == "v1_v2_combined"


def test_explicit_combined_index_is_preserved():
    assert resolve_index_profile("v1_v2_combined", user_facing=True) == "v1_v2_combined"
