# AI Reviewer Guide

작성일: 2026-05-15  
대상 프로젝트: insurance-rag-chatbot  
운영 환경: NVIDIA DGX Spark

---

## 1. 목적

이 문서는 DGX Spark에서 Claude Code를 리뷰어/기획자 에이전트로 사용할 때의 역할, 권한, 주의사항을 정의한다.
Claude Code는 기본적으로 구현자가 아니라 리뷰어로 사용한다.

주요 역할:

- 요구사항 정리
- 변경 diff 리뷰
- 운영 리스크 분석
- 테스트 계획 검토
- 문서 검토
- Codex 작업 결과 리뷰
- Git 커밋 후보 분류

---

## 2. 역할 분담

### Claude Code

Claude Code는 리뷰어/기획자 역할을 맡는다.

주요 작업:

- 설계 검토
- 코드 변경 리뷰
- 운영 문서 리뷰
- 테스트 누락 지적
- 위험 분석
- 다음 작업 계획 수립

### Codex

Codex는 구현자/작업자 역할을 맡는다.

주요 작업:

- 코드 수정
- 스크립트 작성
- 반복 작업 자동화
- 테스트 실패 수정
- 작은 기능 구현

---

## 3. 기본 원칙

Claude Code는 기본적으로 파일을 수정하지 않는다.
사용자가 명시적으로 요청하지 않는 한 다음 작업을 하지 않는다.

- 파일 수정
- `git add`
- `git commit`
- `git push`
- `git reset`
- `git restore`
- `rm`
- `mv`
- `chmod`
- `sudo`
- `python scripts/ingest.py`
- `streamlit run`
- `ollama pull`

리뷰 요청을 받을 경우 기본 응답은 분석과 제안으로 제한한다.

---

## 4. 민감정보 규칙

다음 파일이나 경로의 값은 읽거나 출력하지 않는다.

- `.env`
- `/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh`
- `users.json`
- `CLOVA_OCR_CUSTOM_API_EXTERNAL*.json`
- OpenAI API key
- CLOVA OCR secret
- 앱 관리자 비밀번호

키 이름 확인은 가능하지만 값은 출력하지 않는다.

예:

```bash
grep -nE 'OPENAI|CLOVA|APP_PASSWORD|OLLAMA' /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh | sed 's/=.*/=<hidden>/'
```

---

## 5. Git에 올리면 안 되는 항목

다음은 Git 금지 항목이다.

- .env
- .env.*
- users.json
- users.json.tmp
- logs/
- data/chat_history/
- raw/
- 루트 PDF/XLSX/XLS 파일
- data/extracted/
- data/extracted_v2_manual/
- data/index/chroma/
- data/index/relational/*.sqlite
- data/processed_backup*/
- data/index_backup*/
- .venv/
- __pycache__/
- .pytest_cache/
- CLOVA_OCR_CUSTOM_API_EXTERNAL*.json

---

## 6. 현재 DGX 운영 기준

프로젝트 경로:

```text
/srv/shared/projects/insurance-rag-chatbot
```

실행 스크립트:

```text
/srv/ai-ops/bin/run-insurance-rag
```

점검 스크립트:

```text
/srv/ai-ops/bin/check-insurance-rag
```

비밀정보 경로:

```text
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
```

Streamlit 내부 주소:

```text
127.0.0.1:8501
```

팀원 접속 방식:

```bash
ssh -L 8501:localhost:8501 <계정>@100.88.5.57
```

Ollama 모델:

```text
exaone3.5:7.8b
```

정상 Chroma count:

```text
7825
```

정상 retrieval eval:

```text
recall@8 = 1.000
```

---

## 7. 허용되는 기본 읽기 명령

리뷰 목적에서는 다음 명령을 사용할 수 있다.

```bash
git status --short
git diff --stat
git diff -- <file>
git log --oneline -10
ls
find
grep
wc -l
sed -n
```

Python을 이용한 read-only inspection도 가능하다.

예:

```bash
python - <<'PY'
from pathlib import Path
print(Path("docs/DGX_SPARK_RUNBOOK.md").exists())
PY
```

---

## 8. 사용자 승인 없이 실행 금지

다음 명령은 사용자 승인 없이 실행하지 않는다.

```bash
git add
git commit
git push
git reset
git restore
git rm
rm
mv
chmod
sudo
python scripts/ingest.py
python scripts/eval.py --ocr
streamlit run
ollama pull
```

---

## 9. 리뷰 출력 형식

Claude Code는 리뷰 결과를 다음 형식으로 출력한다.

1. 요약
2. 변경 파일별 평가
3. 위험도
4. 테스트 필요 여부
5. 커밋 여부 추천
6. 사용자 승인 필요 작업
7. 보류할 작업

---

## 10. 현재 Git 정책 메모

현재 .gitignore에는 DGX runtime artifact 차단 규칙이 추가되어 있다.

다만 이미 Git이 추적 중인 생성물은 별도 정책 결정이 필요하다.

현재 보류 대상:

- data/processed/chunks.jsonl
- data/index/bm25.pkl
- eval/smoke_qa_v2.jsonl

원칙적으로 chunks.jsonl과 bm25.pkl은 생성물이므로 장기적으로 Git 추적 해제를 검토한다.

단, 기존 프로젝트 운영 방식과 팀 합의가 필요하므로 즉시 git rm --cached하지 않는다.

eval/smoke_qa_v2.jsonl은 평가셋이므로 무조건 추적 해제하지 않는다. 변경 내용 검토 후 별도 커밋 여부를 결정한다.

저장:

```text
Ctrl + O
Enter
Ctrl + X
```

---

## 2. Runbook 문서만 stage/commit

```bash
cd /srv/shared/projects/insurance-rag-chatbot
git status --short
git add docs/AI_REVIEWER_GUIDE.md
git diff --cached --name-only
```

출력이 이것 하나만이어야 합니다.

```text
docs/AI_REVIEWER_GUIDE.md
```

그다음 커밋합니다.

```bash
git commit -m "Add AI reviewer guide for DGX operations"
```

---

## 3. Claude 리뷰어 wrapper 만들기

커밋 후, Claude를 쉽게 호출하는 wrapper를 만듭니다.

```bash
nano /srv/ai-ops/bin/claude-review
```

내용:

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-/srv/shared/projects/insurance-rag-chatbot}"
TASK="${2:-현재 git status와 운영 리스크를 리뷰해줘. 파일은 수정하지 마.}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="/srv/ai-ops/logs/claude"
mkdir -p "$LOG_DIR"
cd "$REPO"
claude -p "$TASK" 2>&1 | tee "$LOG_DIR/review_$TS.log"
echo
echo "Claude review log: $LOG_DIR/review_$TS.log"
```

권한 부여:

```bash
chmod +x /srv/ai-ops/bin/claude-review
```

테스트:

```bash
/srv/ai-ops/bin/claude-review \
  /srv/shared/projects/insurance-rag-chatbot \
  "docs/AI_REVIEWER_GUIDE.md와 docs/DGX_SPARK_RUNBOOK.md를 참고해서 현재 git status를 리뷰해줘. 파일은 수정하지 마."
```

---

## 4. Claude의 Git 위험 지적에 대한 후속 계획

Claude가 가장 큰 리스크로 지적한 “tracked 생성물”은 별도 단계로 분리하세요.

지금은 하지 말아야 할 명령:

```bash
git rm --cached data/index/bm25.pkl
git rm --cached data/processed/chunks.jsonl
git rm --cached eval/smoke_qa_v2.jsonl
```

대신 다음 작업으로 남깁니다.

작업명: 데이터/인덱스 Git 추적 정책 정리

결정 필요:

1. chunks.jsonl을 Git에서 제거할지
2. bm25.pkl을 Git에서 제거할지
3. parquet 파일은 유지할지 제거할지
4. eval/smoke_qa_v2.jsonl 변경은 커밋할지 되돌릴지
5. GitHub public repo에 대용량 산출물 정책을 어떻게 명시할지

---

## 5. 다음 큰 단계: 역할 분리 운영 루프 확정

Claude Code 준비가 끝나면, 이제 운영 루프는 이렇게 가져가면 됩니다.

```text
사용자
 ↓
Claude Code: 요구사항 정리 / 리스크 분석 / 테스트 계획
 ↓
Codex: 구현 / 수정 / 스크립트 작성
 ↓
pytest / eval / 앱 테스트
 ↓
Claude Code: diff 리뷰 / 커밋 여부 판단
 ↓
사용자 승인 후 commit
```

---
