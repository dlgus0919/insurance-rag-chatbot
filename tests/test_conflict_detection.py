import pytest
from src.parser.chunker import Chunk
from src.rag.evidence import detect_retrieval_conflicts

def test_detect_retrieval_conflicts_no_multiple_docs():
    # 단일 문서만 있을 때 -> conflict_detected는 False여야 함
    chunks = [
        Chunk(id="c1", text="도수치료는 연간 50회 한도 내에서 보상합니다.", metadata={"doc_short": "약관"})
    ]
    res = detect_retrieval_conflicts(chunks, "도수치료 보상 한도와 횟수를 알려주세요.")
    assert not res["conflict_detected"]

def test_detect_retrieval_conflicts_no_keyword():
    # 복수 문서가 있으나, 질문에 충돌 키워드가 없을 때 -> False
    chunks = [
        Chunk(id="c1", text="안녕하세요. 반갑습니다.", metadata={"doc_short": "약관"}),
        Chunk(id="c2", text="오늘 날씨가 좋네요.", metadata={"doc_short": "자사_SOL건강"})
    ]
    res = detect_retrieval_conflicts(chunks, "인사말을 건네주세요.")
    assert not res["conflict_detected"]

def test_detect_retrieval_conflicts_numerical_mismatch():
    # 복수 문서가 있고, 수치가 다를 때 -> True
    chunks = [
        Chunk(id="c1", text="도수치료는 연간 50회 한도 내에서 보상합니다.", metadata={"doc_short": "약관"}),
        Chunk(id="c2", text="도수치료는 연간 30회 한도 내에서 보상합니다.", metadata={"doc_short": "자사_SOL건강"})
    ]
    res = detect_retrieval_conflicts(chunks, "도수치료는 상품별로 몇 회 보상하나요?")
    assert res["conflict_detected"]
    assert "약관" in res["conflicting_docs"]
    assert "자사_SOL건강" in res["conflicting_docs"]

def test_detect_retrieval_conflicts_disclaimer_mismatch():
    # 한 문서는 보상, 한 문서는 면책(보상하지 않음)일 때 -> True
    chunks = [
        Chunk(id="c1", text="다빈치 로봇 수술비는 100% 보상합니다.", metadata={"doc_short": "약관"}),
        Chunk(id="c2", text="다빈치 로봇 수술비는 보상하지 않습니다.", metadata={"doc_short": "자사_SOL건강"})
    ]
    res = detect_retrieval_conflicts(chunks, "로봇수술은 보상되나요?")
    assert res["conflict_detected"]

def test_detect_retrieval_conflicts_explicit_compare():
    # 질문에 '비교'가 들어가고 복수 문서일 때 -> True
    chunks = [
        Chunk(id="c1", text="도수치료 약관 내용", metadata={"doc_short": "약관"}),
        Chunk(id="c2", text="도수치료 SOL건강 내용", metadata={"doc_short": "자사_SOL건강"})
    ]
    res = detect_retrieval_conflicts(chunks, "두 상품의 도수치료 보상을 비교해줘.")
    assert res["conflict_detected"]
