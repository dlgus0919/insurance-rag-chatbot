# Developer Handoff Triage

- Timestamp: 2026-07-20 19:31:17 +0900
- Cycle: uat-mri-operational-retrieval-fixback-20260720-1931
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- Scope/spec: Chrome P0 rerun after protected-main commit `ba3426e`

## Reported

The reviewed provenance and frontend candidate was deployed to protected main as `ba3426e`. API-only restart succeeded; API PID changed from `3696667` to `3794847`, while SGLang PID `344387` remained unchanged. Focused, related, Node, bundle-parity, frozen-boundary, and health checks passed.

## Observed

- Chrome was reloaded against `http://localhost:18080` after deployment.
- The `4세대 실손` radio was selected and a new chat asked exactly: `4세대 자기공명영상진단(MRI/MRA)의 연간 보상한도는?`
- Final visible answer: `제공된 문서에서 4세대 실손의료보험에서의 자기공명영상진단(MRI/MRA) 연간 보상한도에 대한 정보를 확인할 수 없습니다.`
- The prior internal phrase `직접 연결된 판단 조건 경로를 찾지 못했습니다.` was no longer rendered. The structured panel retained status and the other non-missing generation summary.
- Audit row `501` recorded `policy_generation=4th`, `effective_index_mode=v2_only`, `resolved_intent=ambiguous_medical_term`, and `source_count=0`.
- Its search-intent payload recorded `requires_clause_lookup=false`, `requires_coverage_judgment=false`, and no exact terms.
- Retrieval executed general dense and BM25, then reranked five counseling-case chunks. The final generation filter produced no result; no canonical 4th-generation direct clause entered the final source set.
- The deployed provenance crosswalk therefore had no matching direct-clause candidate to hydrate. This is a retrieval-planning/candidate-recall defect, not a remaining frontend-summary defect.
- `src/rag/search_intent.py` routes MRI/MRA to `ambiguous_medical_term` after only explicit article/appendix and narrow clause-detail cues. Pure policy-attribute cues such as annual benefit limits are not represented in that classifier.
- `src/rag/pipeline.py` currently enables filtered dense only for explicit codes. `requires_clause_lookup` alone does not select a generation-aware direct-clause retrieval path.

## Not Verified

- The minimal general retrieval fix has not been designed or implemented.
- The 5th-generation, comparison, coverage-judgment, repeat-consistency, and source-link UAT cases were not run because the first P0 case failed.
- It is not yet proven whether intent classification alone, a direct-clause retrieval lane, v2 metadata/index coverage, or a combination is the smallest correct fix.

## Findings

- **P0:** An explicit generation-scoped policy-attribute question still returns no answer despite a canonical 4th-generation direct clause being present.
- **P1:** Existing tests validate deterministic answer generation only after correct source rows are supplied; they do not exercise the live v2 retrieval path from the exact user question to a non-empty source set.
- **Resolved subfinding:** The internal `status=missing` technical summary no longer leaks into the visible structured panel.

## Decision

`DEVELOPER_FIXBACK`

## Dispatch

Developer must reproduce audit row 501 in an isolated runtime using the actual v2 index and canonical metadata, trace the query from search-intent classification through candidate retrieval, hydration, generation filtering, reranking, and final source selection, then add a general retrieval contract for explicit generation-scoped policy-attribute questions. The fix must not hardcode MRI, generation, amounts, or the exact UAT sentence. Coverage-judgment queries must preserve clarification behavior. Protected main, API, data, Graph/ontology, active rules, and push remain unchanged until a new candidate passes Review Team.
