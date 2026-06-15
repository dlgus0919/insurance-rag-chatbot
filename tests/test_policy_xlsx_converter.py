from scripts.convert_policy_xlsx_eval import _clause_terms, _important_terms


def test_policy_converter_does_not_use_category_as_required_terms():
    terms = _important_terms(
        "보험나이는 어떻게 계산하나?",
        "계약일 현재 피보험자의 실제 만 나이 기준으로 계산합니다.",
        "계약 성립·철회·무효",
    )

    assert terms == ["보험나이"]


def test_policy_converter_extracts_table_reference_terms():
    assert _clause_terms("비급여 특약 <표1>") == ["<표1>"]


def test_policy_converter_omits_generic_clause_terms_when_specific_clause_exists():
    assert _clause_terms("보통약관 제16조") == ["제16조"]


def test_policy_converter_uses_article_level_clause_terms():
    assert _clause_terms("보통약관 제16조 제2항") == ["제16조"]
