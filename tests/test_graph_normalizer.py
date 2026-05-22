from __future__ import annotations

from src.graph.normalizer import clean_korean_particles, normalize_code, normalize_name


def test_normalize_name() -> None:
    assert normalize_name("기관지 식도루 폐쇄술") == "기관지식도루폐쇄술"
    assert normalize_name("  위 절제수술(胃 切除手術) ") == "위절제수술胃切除手術"
    assert normalize_name("Z-flap") == "z-flap"
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_normalize_code() -> None:
    assert normalize_code("QZ966") == "QZ966"
    assert normalize_code("qz966") == "QZ966"
    assert normalize_code(" qz 966 ") == "QZ966"
    assert normalize_code("") == ""


def test_clean_korean_particles() -> None:
    assert clean_korean_particles("식도로") == "식도"
    assert clean_korean_particles("수술에서") == "수술"
    assert clean_korean_particles("기관지는") == "기관지"
    assert clean_korean_particles("수술을") == "수술"
    assert clean_korean_particles("수술") == "수술"
    assert clean_korean_particles("") == ""
