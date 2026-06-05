from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import jinja2


TEMPLATE_PATH = Path("ops/templates/qwen3_thinking_switchable.jinja")


def _render_template(enable_thinking: bool) -> str:
    template = jinja2.Environment().from_string(TEMPLATE_PATH.read_text(encoding="utf-8"))
    messages = [
        SimpleNamespace(role="system", content="SYS"),
        SimpleNamespace(role="user", content="USER"),
    ]
    return template.render(messages=messages, tools=None, add_generation_prompt=True, enable_thinking=enable_thinking)


def test_qwen_thinking_template_off_closes_empty_reasoning_block() -> None:
    rendered = _render_template(False)

    assert rendered.endswith("<|im_start|>assistant\n</think>\n\n")
    assert not rendered.endswith("<|im_start|>assistant\n<think>\n")


def test_qwen_thinking_template_on_starts_reasoning_block() -> None:
    rendered = _render_template(True)

    assert rendered.endswith("<|im_start|>assistant\n<think>\n")
