# 보험 문서 RAG 챗봇 (Alpha)

1,429페이지 건강보험 고시 PDF를 로컬에서 검색하고 답변하는 RAG 챗봇입니다.  
PDF 파싱, 계층형 청킹, BGE-M3 임베딩, ChromaDB, BM25, RRF 융합, Ollama LLM 호출로 구성됩니다.  
알파 버전은 단일 사용자 로컬 실행과 출처 확인 가능한 답변 생성만 다룹니다.

## 사전 요구사항

- Python 3.11 권장
- macOS Apple Silicon 또는 Linux
- Ollama 설치 및 실행
- 기본 모델: `ollama pull qwen2.5:3b-instruct`
- Ollama 데스크톱 앱 실행 또는 `ollama serve`
- BGE-M3 모델 사전 다운로드

외부 네트워크가 필요한 모델 다운로드는 실행 코드에서 수행하지 않는 것을 전제로 합니다. BGE-M3가 HuggingFace 캐시에 없는 경우 인덱싱 단계에서 중단됩니다.

```bash
python - <<'PY'
from sentence_transformers import SentenceTransformer
SentenceTransformer("BAAI/bge-m3")
PY
```

다른 Ollama 모델을 쓰려면 `.env`에서 `OLLAMA_MODEL` 값을 바꿉니다.

## 셋업

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

입력 PDF `BZ202603053039374.pdf`는 프로젝트 루트에 있어야 합니다.

## 인덱싱

```bash
python scripts/ingest.py --stage all
```

단계별 실행도 가능합니다.

```bash
python scripts/ingest.py --stage chunks
python scripts/ingest.py --stage index
```

M4 Mac CPU 기준 BGE-M3 임베딩은 30분에서 수 시간까지 걸릴 수 있습니다. 한 번 생성된 `data/index/`는 재사용합니다.

## 실행

CLI:

```bash
python scripts/cli.py
```

Streamlit:

```bash
streamlit run src/ui/streamlit_app.py
```

## 평가

```bash
python scripts/eval.py
```

평가 문항은 `eval/smoke_qa.jsonl`에 있으며, 코드 조회 5개와 의미 검색 5개로 구성됩니다. 기준은 retrieval recall@8 0.7 이상, 출처 페이지 정확도 0.6 이상입니다.

## 트러블슈팅

Ollama 미연결: Ollama 데스크톱 앱을 켜거나 `ollama serve`를 실행하세요.

모델 미존재 또는 태그명 오타: `ollama list`로 설치 모델명을 확인하고 `.env`의 `OLLAMA_MODEL` 값을 맞추세요.

BGE-M3 다운로드 실패: 네트워크가 가능한 환경에서 `SentenceTransformer("BAAI/bge-m3")`를 먼저 실행해 HuggingFace 캐시에 저장하세요.

kiwipiepy 설치 실패: BM25 토크나이저는 정규식 기반 토큰화로 폴백합니다. 다만 한국어 검색 품질은 낮아질 수 있습니다.

Chroma 또는 BM25 인덱스 없음: `python scripts/ingest.py --stage index`를 다시 실행하세요.

## 알파 범위 외 / 베타 이월

- OCR
- bge-reranker-v2 리랭킹
- 멀티턴 질의 재작성
- 코드 정확매칭 우선 라우팅
- 인덱스 버전 관리와 증분 업데이트
- 세션 영속화와 사용자별 히스토리
- Docker/CI/CD
- LLM 7B/8B 업그레이드 평가
