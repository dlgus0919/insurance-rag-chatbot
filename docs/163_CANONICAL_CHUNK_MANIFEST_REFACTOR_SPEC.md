# 163. Canonical Chunk Manifest Refactor Spec

작성일: 2026-06-01
대상 프로젝트: `insurance-rag-chatbot`
대상 범위: `v2_only / v1_v2_combined / GraphDB` chunk identity 정합성 재편

## 1. 목적

현재 GraphDB는 `v1_v2_combined` 기반 chunk 흐름과 가장 직접적으로 정합되고, `v2_only`는 같은 문서/같은 페이지를 보더라도 주로 `doc/page fallback`으로 회수된다.
이는 OCR 품질 문제가 아니라, **같은 근거를 인덱스/그래프가 서로 다른 chunk identity로 관리하는 구조 문제**다.

이번 재편의 목표는 다음 하나로 요약된다.

> `GraphDB`, `v2_only`, `v1_v2_combined`가 모두 같은 canonical chunk manifest를 공유하게 만든다.

이후에는 다음 상태를 목표로 한다.

- 같은 논리 근거는 항상 같은 `canonical_chunk_id`를 가진다.
- `v2_only`와 `v1_v2_combined`는 같은 manifest에서 row subset만 달리 선택한다.
- Graph evidence는 `doc/page fallback`이 아니라 `canonical_chunk_id` 또는 그에 준하는 stable key를 1차 참조로 사용한다.

## 2. 현재 문제 요약

### 2.1 현재 구조

- `default`: `data/processed/chunks.jsonl`
- `v2_only`: `data/processed/chunks_v2_manual.jsonl`
- `v1_v2_combined`: `data/processed/chunks_v1_v2_combined.jsonl`
- GraphDB build: 기본적으로 `chunks_v1_v2_combined.jsonl`을 source로 사용

### 2.2 현재 약점

1. `v2_only`와 GraphDB가 같은 page evidence를 보고도 동일 chunk id를 공유하지 않는다.
2. `v1_v2_combined`는 통합 시점에 새 chunk id를 재부여한다.
3. Graph evidence는 현재 사실상 `combined` build 시점 chunk 흐름의 부산물을 참조한다.
4. 따라서 `v2_only`는 내용은 좋아도 identity 정합성은 낮다.
5. 결과적으로 운영 경고와 sync 진단이 `doc/page fallback`에 과도하게 의존한다.

### 2.3 진단상 관찰된 사실

- `v1_v2_combined`: direct hit이 매우 높음
- `v2_only`: 일부 stable key hit은 생겼지만 여전히 다수가 `doc/page fallback`
- `default`: 구조적으로 OCR 문서군이 빠져 있어 일부 miss는 정상

즉, 이번 재편은 `default`를 해결하려는 작업이 아니라 **`v2_only`와 GraphDB의 동일 근거 동일 ID 체계 확립**이 핵심이다.

## 3. 설계 원칙

1. **canonical first**
   - 모든 chunk identity의 기준은 단 하나의 canonical manifest에서 나온다.

2. **derived index**
   - `v2_only`, `v1_v2_combined`는 chunk를 각각 새로 “만드는” 것이 아니라 canonical manifest에서 파생된다.

3. **graph follows manifest**
   - GraphDB evidence는 build 시점 임시 id가 아니라 canonical manifest id를 따라야 한다.

4. **fallback is secondary**
   - `doc/page fallback`은 장애 복구용으로만 남기고, 기본 경로가 되어서는 안 된다.

5. **incremental migration**
   - 기존 산출물 전체를 한 번에 갈아엎지 않고, backfill 및 dual-read 기간을 둔다.

## 4. 제안 구조

## 4.1 Canonical manifest 파일

신규 기준 파일:

```text
data/processed/chunks_canonical_manifest.jsonl
```

각 row는 하나의 **논리 chunk**를 나타낸다.

필수 필드 예시:

```json
{
  "canonical_chunk_id": "심평원_ch_007841",
  "doc_short": "심평원",
  "doc_name": "BZ202603053039374.pdf",
  "page_start": 638,
  "page_end": 638,
  "section_path": ["제9장", "분류항목별 진료행위", "췌이식술"],
  "content_type": "table_row",
  "text": "Q8061 췌이식술-부분 ...",
  "token_count": 143,
  "source_variants": {
    "v2_only": {
      "variant_chunk_id": "심평원_ch_007841",
      "ocr_version": "v2_manual",
      "available": true
    },
    "v1": {
      "variant_chunk_id": "심평원_ch_007820",
      "ocr_version": "v1_original",
      "available": true
    },
    "v1_v2_combined": {
      "variant_chunk_id": "심평원_v2_manual_ch_007841",
      "ocr_version": "v2_manual",
      "available": true
    }
  },
  "metadata": {
    "bbox": null,
    "codes": ["Q8061"],
    "table_row_no": 2
  }
}
```

핵심은 `canonical_chunk_id`와 `source_variants`다.

## 4.2 ID 규칙

### canonical id

원칙:

- `doc_short + logical_chunk_sequence`
- 인덱스 모드명(`v1`, `v2_manual`, `combined`)을 넣지 않는다.

예:

```text
심평원_ch_007841
실무가이드_ch_000111
상담사례집_ch_001203
```

### variant id

실제 인덱스 내부 collection id는 유지할 수 있다. 다만 canonical과 분리한다.

예:

```text
canonical_chunk_id = 심평원_ch_007841
variant_chunk_id(v2_only) = 심평원_ch_007841
variant_chunk_id(v1_v2_combined) = 심평원_v2_manual_ch_007841
```

즉 **variant id는 저장 형식상 달라도 되지만, canonical id는 동일**해야 한다.

## 4.3 인덱스별 파생 규칙

### `v2_only`

- canonical manifest row 중 `source_variants.v2_only.available=true`인 row만 사용
- Chroma/BM25 metadata에 반드시 저장:
  - `canonical_chunk_id`
  - `source_chunk_id` (초기 이행기에는 canonical과 동일하게 둠)
  - `variant_chunk_id`
  - `ocr_version=v2_manual`

### `v1_v2_combined`

- canonical manifest row 중 `v1` 또는 `v2_only` variant가 있는 row를 둘 다 포함
- 다만 collection id는 variant 기준으로 저장 가능
- metadata에는 동일하게 `canonical_chunk_id`를 넣는다

중요:

- combined는 더 이상 “새 chunk 집합을 생성하는 단계”가 아니라
- **canonical manifest row를 variant별로 두 벌 주입하는 단계**가 되어야 한다.

## 4.4 GraphDB

GraphDB build 입력을 기존 `chunks_v1_v2_combined.jsonl`에서 아래 구조로 바꾼다.

1. Graph extractor는 canonical manifest를 읽는다.
2. graph fact / graph evidence는 `canonical_chunk_id`를 1차 key로 저장한다.
3. 필요하면 `variant_chunk_id`와 `source_mode`를 부가 metadata로 둔다.

신규 `graph_evidence` 권장 필드:

- `canonical_chunk_id`
- `variant_chunk_id`
- `doc_short`
- `page_start`
- `page_end`
- `source_mode`
- `ocr_version`

`chunk_id` 컬럼은 이행기 동안 유지하되, 의미를 아래처럼 제한한다.

- 기존: build 시점 임시 chunk id
- 변경 후: 사실상 `variant_chunk_id`

장기적으로는 `chunk_id` 이름도 모호하므로 아래 중 하나를 권장한다.

- `chunk_id` 유지 + `canonical_chunk_id` 추가
- 또는 `variant_chunk_id`로 명시 rename

이번 재편에서는 **호환성을 위해 `chunk_id` 유지 + `canonical_chunk_id` 추가**가 안전하다.

## 5. 파이프라인 변경안

## 5.1 신규 단계

```text
raw/ocr documents
  -> canonical manifest builder
  -> derived index builder (v2_only / v1_v2_combined)
  -> graph builder
```

## 5.2 신규/변경 스크립트

### 신규 권장

```text
scripts/build_canonical_chunk_manifest.py
scripts/build_index_from_canonical_manifest.py
scripts/backfill_canonical_chunk_id.py
```

### 기존 스크립트 역할 변경

- `scripts/build_ocr_combined_chunks.py`
  - 직접 JSONL을 새로 만드는 스크립트에서
  - canonical manifest 기반 파생 인덱스 생성기로 역할 축소 또는 폐기

- `scripts/build_graph_index.py`
  - `--chunks-path` 대신 `--canonical-manifest`
  - 혹은 둘 다 지원하되 canonical 우선

## 5.3 단계별 구현 순서

### Phase 1. Canonical metadata 병행 저장

목표:

- 기존 인덱스 구조를 유지한 채 metadata에 `canonical_chunk_id`를 추가

작업:

1. chunker / OCR chunker가 `canonical_chunk_id` 생성
2. Chroma metadata에 `canonical_chunk_id` 저장
3. Graph evidence metadata에도 `canonical_chunk_id` 저장
4. lookup은 `canonical_chunk_id`를 우선 사용

효과:

- 큰 재빌드 없이도 stable key lookup 품질을 먼저 높일 수 있다.

### Phase 2. Canonical manifest 파일 도입

목표:

- `chunks_canonical_manifest.jsonl` 생성

작업:

1. v2 chunk를 기준 축으로 삼아 canonical row 생성
2. 가능한 경우 v1 variant를 row에 매핑
3. 일부 unmatched v1 row는 별도 canonical row로 남김

중요:

- 여기서 “v1 row 수와 v2 row 수가 꼭 같아야 한다”는 가정을 두지 않는다.
- 1:1 매핑 실패는 정상 케이스로 허용한다.

### Phase 3. Derived index rebuild

목표:

- `v2_only`, `v1_v2_combined`를 canonical manifest에서 재생성

작업:

1. `v2_only`는 `v2_only.available=true` row만 인덱싱
2. `v1_v2_combined`는 variant별 row를 풀어 인덱싱
3. 모든 인덱스 metadata에 `canonical_chunk_id` 저장

### Phase 4. GraphDB rebuild

목표:

- GraphDB가 canonical manifest를 직접 source로 사용

작업:

1. graph extractors가 canonical row를 기준으로 evidence 생성
2. `graph_evidence.canonical_chunk_id`를 본 필드로 사용
3. sync diagnostic도 `canonical_chunk_id` 우선으로 재작성

### Phase 5. Legacy cleanup

조건:

- sync 진단에서 `v2_only` source-key/direct hit 비중이 충분히 올라간 뒤

작업:

1. string fallback lookup 축소
2. `doc/page fallback` 경고를 더 엄격하게 표시
3. old id alias/backfill 스크립트 의존도 축소

## 6. 마이그레이션 전략

## 6.1 호환성 유지

즉시 제거하지 않고 일정 기간 아래를 함께 유지한다.

- `chunk_id` (legacy/variant id)
- `source_chunk_id` (현재 stable key)
- `canonical_chunk_id` (최종 기준 key)

lookup 우선순위:

1. `canonical_chunk_id`
2. `source_chunk_id`
3. `chunk_id`
4. string fallback
5. `doc/page fallback`

## 6.2 데이터 백필

대상:

- `data/processed/*.jsonl`
- Chroma metadata
- `graph_evidence.metadata_json`
- 필요하면 graph table schema

주의:

- Chroma update는 batch limit을 지켜야 한다.
- metadata encoding 규칙(`codes` 빈 리스트 금지 등)을 반드시 재사용해야 한다.

## 7. 기대 효과

1. `v2_only`에서 Graph evidence 회수가 `doc/page fallback` 중심에서 `canonical/source key hit` 중심으로 이동
2. 관리자 sync 진단이 “내용상 비슷한 청크를 찾았다”가 아니라 “같은 논리 근거를 찾았다”를 보여줄 수 있음
3. GraphDB rebuild source를 `combined` 전용 흐름에 묶어두지 않게 됨
4. 장기적으로 `default` / `v2_only` / `v1_v2_combined` 비교 평가가 더 명확해짐

## 8. 비목표

이번 설계는 아래를 직접 해결하지 않는다.

1. `default` 인덱스의 OCR 문서군 미포함 문제
2. OCR 텍스트 정확도 자체의 추가 향상
3. Graph ontology 확장
4. Graph fact 품질 개선 또는 extraction rule 개선

즉 이번 작업은 **근거 identity 정합성 재편**이지, retrieval 품질 전체를 다시 설계하는 작업은 아니다.

## 9. 구현 수용 기준

다음이 충족되면 이번 설계 구현이 성공한 것으로 본다.

1. `v2_only` Chroma metadata에 `canonical_chunk_id`가 전건 저장됨
2. Graph evidence가 `canonical_chunk_id`를 저장함
3. `v2_only` sync 진단에서 `source/canonical key hit` 비중이 유의미하게 증가함
4. `v1_v2_combined` direct hit 회귀가 없음
5. 전체 회귀 테스트 통과

권장 목표치:

- `v1_v2_combined`: direct hit 유지
- `v2_only`: `doc_page_hit` 비중 유의미 감소

## 10. 주요 위험과 대응

### 위험 1. v1/v2 row 1:1 대응 강박

문제:

- 실제 데이터는 v1과 v2 chunk 수가 정확히 일치하지 않을 수 있다.

대응:

- canonical row는 “논리 근거 단위”이며, variant 존재 여부는 optional로 둔다.
- unmatched variant를 정상 상태로 허용한다.

### 위험 2. combined 재인덱싱 시 평가 회귀

문제:

- 기존 `v1_v2_combined` direct hit 구조를 깨뜨릴 수 있다.

대응:

- Phase 3 전후로 sync diagnostic과 stage2 smoke/hard subset을 비교한다.

### 위험 3. Chroma metadata update 제약

문제:

- batch limit 및 metadata validation 제약이 있다.

대응:

- `_encode_metadata()`를 재사용하고, batch update 크기를 제한한다.

## 11. Self-review & 첨삭

초안 작성 후 아래 관점으로 점검했다.

1. **문제 정의가 명확한가**
   - OCR 품질 문제와 chunk identity 문제를 분리해 설명했다.

2. **현재 구조와 충돌하지 않는가**
   - `chunk_id`를 즉시 제거하지 않고 `canonical_chunk_id`를 병행하는 방식으로 조정했다.

3. **실제 데이터 현실을 반영하는가**
   - `v1`과 `v2` chunk 수가 다를 수 있음을 전제로 수정했다.
   - 1:1 대응을 강제하는 설계를 제거했다.

4. **바로 구현 가능한가**
   - Phase 1~5 순서로 잘라 구현 가능하도록 정리했다.

5. **남는 결점은 무엇인가**
   - 이 설계만으로 `default` 인덱스 miss는 해결되지 않는다.
   - 이는 의도된 비목표로 명시했다.

최종 판단:

- 현재 코드베이스와 최근 sync 진단 결과를 기준으로 볼 때, 이 설계는 과도한 재작성 없이 단계적으로 구현 가능하다.
- 치명적 결점은 없으며, 구현 시작 전 명세로 사용 가능하다.
