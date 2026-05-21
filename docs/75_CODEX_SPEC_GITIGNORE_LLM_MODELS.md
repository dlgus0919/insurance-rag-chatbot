# Codex Spec #75 — handoff/ LLM 모델 디렉토리 git 추적 차단 강화

> **작성일:** 2026-05-21
> **작성자:** Claude (검토자/기획자)
> **구현 담당:** Codex
> **성격:** 저장소 위생 / .gitignore 보강
> **우선순위:** 🟡 중간 — 맥북 디스크 보호 + remote push/pull 안전성

---

## 0. 배경

DGX Spark에서 사용할 대용량 로컬 LLM 스냅샷(총 ~31 GB)이 맥북 작업 트리에 남아 있다.

```
handoff/llm_stage1_20260519/downloads/models/
├── Gemma-4-26B-A4B-NVFP4/   # 약 18 GB
└── gpt-oss-20b/             # 약 13 GB
```

운영 정책 상 모델은 DGX Spark에 직접 배치하고 SSH로 사용한다. 맥북에는 모델 사본을 둘 필요가 없다.

현재 `.gitignore` 13행에 `handoff/` 전체 무시 규칙이 있고, `git ls-files handoff/`는 0개 결과로 모델 파일이 origin에 push된 적이 없음이 확인됐다. 즉, **기본 보호는 이미 작동 중**이다. 그러나 다음 두 가지 이유로 방어적 규칙 추가가 필요하다.

1. 추후 누군가 `handoff/` 라인을 의도치 않게 풀어버려도 모델 디렉토리는 계속 차단되어야 한다.
2. 새로운 stage(`llm_stage2_*`, `llm_stage3_*`)가 생겨도 동일 규칙이 적용되어야 한다.

이번 작업은 `.gitignore`에 명시적 규칙을 한 줄 추가하는 가벼운 변경이다. **파일 실삭제는 명세 범위 밖**이며 Claude가 Codex 검증 이후 직접 수행한다.

---

## 1. 목표 (Goal)

- `handoff/llm_stage*_*/downloads/models/`가 어떤 상황에서도 git 추적 대상이 되지 않도록 `.gitignore`에 명시적이고 영구적인 보호 규칙을 추가한다.
- 기존 `.gitignore`의 일반 `handoff/` 규칙은 유지한다(중복 OK, 한쪽이 사라져도 다른 한쪽이 보호).
- 어떤 기존 추적 파일도 제거하거나 변경하지 않는다.

---

## 2. 대상 파일

**변경 허용:**
- `.gitignore`

**변경 금지:**
- 기타 모든 파일.
- 특히 `handoff/` 하위 실제 파일/디렉토리는 손대지 않는다(삭제는 Claude가 별도 단계에서 수행).

---

## 3. 상세 요구사항

### 3-1. `.gitignore` 보강

기존 `# --- DGX runtime / private artifacts ---` 섹션 이후 또는 파일 끝에 다음 블록을 추가한다.

```gitignore
# --- DGX local LLM snapshots (must NEVER be tracked) ---
# 모델 스냅샷은 DGX Spark에 직접 배치한다. 맥북에는 사본 보관 금지.
# handoff/ 일반 무시가 풀려도 모델만은 명시적으로 차단한다.
handoff/llm_stage*_*/downloads/models/
handoff/llm_stage*_*/downloads/models/**
```

- 와일드카드 `llm_stage*_*`로 향후 stage 추가에도 대응한다.
- 디렉토리(`/`)와 와일드카드(`/**`) 양쪽을 명시해 일부 git 버전에서의 경계 케이스를 피한다.

### 3-2. 변경 후 검증

저장소 루트(`/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇`)에서 다음 명령을 실행하고 출력을 보고한다.

```bash
# 1. 모델 디렉토리가 무시되는지 확인 — 두 항목 모두 'handoff/llm_stage*_*/downloads/models/' 규칙에 매칭되어야 한다.
git check-ignore -v handoff/llm_stage1_20260519/downloads/models/
git check-ignore -v handoff/llm_stage1_20260519/downloads/models/Gemma-4-26B-A4B-NVFP4
git check-ignore -v handoff/llm_stage1_20260519/downloads/models/gpt-oss-20b

# 2. 추적된 모델 파일이 없는지 확인 — 출력이 비어 있어야 한다.
git ls-files handoff/llm_stage1_20260519/downloads/models/ | head -5

# 3. 작업 트리 상태 — 변경 대상은 .gitignore 한 파일이어야 한다.
git status --short
```

기대 결과:

- (1)은 새 규칙(`.gitignore:<라인번호>:handoff/llm_stage*_*/downloads/models/`)에 매칭. 기존 `handoff/` 규칙이 먼저 매칭돼도 무방하나, **새 규칙이 단독으로도 매칭됨**을 확인하기 위해 임시로 기존 `handoff/` 라인을 주석 처리한 상태에서 한 번 더 (1)을 실행해 본 뒤 원복한다(원복 누락 주의).
- (2)는 빈 출력.
- (3)은 `M .gitignore`만 표시.

### 3-3. 커밋 메시지

다음 메시지로 단일 커밋을 생성한다(스테이지 후 commit, push는 하지 않는다).

```
chore(gitignore): explicit ignore for handoff LLM model snapshots
```

---

## 4. 중단 조건 (Stop rules)

다음 중 하나에 해당하면 즉시 작업을 멈추고 보고한다.

1. `git ls-files handoff/llm_stage1_20260519/downloads/models/` 출력이 비어 있지 않은 경우 — 이미 추적된 대용량 파일이 있다는 뜻이므로 `git rm --cached`를 함부로 실행하지 말고 Claude에 보고.
2. `.gitignore`에 의도치 않은 다른 라인 변경이 발생하는 경우.
3. `git status --short`에 `.gitignore` 외의 파일이 추가/수정/삭제로 나타나는 경우.

---

## 5. 산출 보고 (Output requirements)

작업 종료 후 다음을 한 메시지로 보고한다.

1. 추가한 `.gitignore` 블록의 정확한 라인 번호와 텍스트.
2. 3-2의 검증 명령 3개의 실제 출력.
3. 작성한 커밋 해시(`git rev-parse HEAD`)와 메시지.
4. 미해결 위험/추가 권고 사항(있다면).

보고가 끝나면 Human Review 상태에서 대기한다. Claude가 결과를 확인한 뒤 맥북 로컬의 `handoff/llm_stage1_20260519/downloads/models/` 디렉토리(약 31 GB)를 별도로 삭제한다.
