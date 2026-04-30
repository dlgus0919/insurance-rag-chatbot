"""BM25 키워드 검색 인덱스."""

from __future__ import annotations

import math
import pickle
import re
from collections import Counter
from pathlib import Path

from src.retrieval import Hit

TOKEN_RE = re.compile(r"[A-Za-z]{1,3}\d{2,5}|\d{5}|[가-힣A-Za-z0-9]+")


_KIWI = None
_KIWI_AVAILABLE: bool | None = None


def _get_kiwi():
    global _KIWI, _KIWI_AVAILABLE
    if _KIWI_AVAILABLE is False:
        return None
    if _KIWI is not None:
        return _KIWI
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        _KIWI_AVAILABLE = False
        return None
    _KIWI = Kiwi()
    _KIWI_AVAILABLE = True
    return _KIWI


def tokenize(text: str) -> list[str]:
    """
    한국어 검색용 토큰화.

    kiwipiepy가 있으면 명사/동사/외국어/한자 토큰을 사용하고, 없으면
    정규식 기반 한영숫자 토큰화를 사용한다.
    """

    code_tokens = TOKEN_RE.findall(text)
    kiwi = _get_kiwi()
    if kiwi is None:
        return [token.lower() for token in code_tokens if token.strip()]

    selected: list[str] = []
    for token in kiwi.tokenize(text):
        if token.tag.startswith(("N", "V")) or token.tag in {"SL", "SH"}:
            selected.append(token.form.lower())
    return [token.lower() for token in code_tokens + selected if token.strip()]


class _SimpleBM25:
    """rank_bm25를 사용할 수 없을 때의 최소 BM25 구현."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0
        self.doc_freq: Counter[str] = Counter()
        for doc in corpus:
            self.doc_freq.update(set(doc))

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores: list[float] = []
        total_docs = len(self.corpus)
        for doc, doc_len in zip(self.corpus, self.doc_len):
            frequencies = Counter(doc)
            score = 0.0
            for token in query_tokens:
                freq = frequencies[token]
                if freq == 0:
                    continue
                df = self.doc_freq[token]
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / (self.avgdl or 1))
                score += idf * freq * (self.k1 + 1) / denominator
            scores.append(score)
        return scores


class BM25Index:
    """rank_bm25 기반 BM25 인덱스."""

    def __init__(self):
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.metadatas: list[dict] = []
        self.tokenized_docs: list[list[str]] = []
        self.bm25 = None

    def build(self, ids: list[str], texts: list[str], metadatas: list[dict] | None = None) -> None:
        """문서 목록으로 BM25 인덱스를 생성한다."""

        self.ids = list(ids)
        self.texts = list(texts)
        self.metadatas = list(metadatas or [{} for _ in ids])
        self.tokenized_docs = [tokenize(text) for text in texts]
        try:
            from rank_bm25 import BM25Okapi

            self.bm25 = BM25Okapi(self.tokenized_docs)
        except ImportError:  # pragma: no cover - 일반 환경에서는 rank_bm25 사용
            self.bm25 = _SimpleBM25(self.tokenized_docs)

    def save(self, path: Path) -> None:
        """인덱스를 pickle 파일로 저장한다."""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            pickle.dump(self, file)

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        """pickle 파일에서 인덱스를 로드한다."""

        with path.open("rb") as file:
            loaded = pickle.load(file)
        if not isinstance(loaded, cls):
            raise TypeError(f"BM25 인덱스 파일 형식이 올바르지 않습니다: {path}")
        return loaded

    def query(self, text: str, top_k: int) -> list[Hit]:
        """질의 텍스트에 대한 상위 BM25 결과를 반환한다."""

        if self.bm25 is None:
            raise RuntimeError("BM25 인덱스가 아직 생성되지 않았습니다.")

        query_tokens = tokenize(text)
        scores = list(self.bm25.get_scores(query_tokens))
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:top_k]
        return [
            Hit(
                id=self.ids[index],
                score=float(score),
                document=self.texts[index],
                metadata=dict(self.metadatas[index]) if index < len(self.metadatas) else {},
            )
            for index, score in ranked
        ]
