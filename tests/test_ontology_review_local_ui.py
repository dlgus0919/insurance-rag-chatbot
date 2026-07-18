from __future__ import annotations

from scripts.ontology_review_local_ui import _approval_operation_options


def test_local_review_ui_renders_only_bounded_explicit_approval_operations() -> None:
    html = _approval_operation_options(
        [
            {
                "path": "/concepts/cond.alpha/evidence_tags/hash-alpha",
                "field_label": "근거 태그",
                "value_preview": "source:alpha<script>",
                "value_hash": "hash-alpha",
            }
        ]
    )

    assert 'name="approved_paths"' in html
    assert "/concepts/cond.alpha/evidence_tags/hash-alpha" in html
    assert "근거 태그" in html
    assert "source:alpha&lt;script&gt;" in html
    assert "runtime_properties" not in html
