import asyncio
import json
import time
import httpx
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.api.security import create_token
from datetime import timedelta
ACCESS_TOKEN = create_token("testAdmin", "admin", "access", timedelta(days=1))


API_BASE = "http://127.0.0.1:18080/api"
MODELS = ["gemma4", "nemotron", "gpt-oss", "qwen3"]

# 20 Test Cases
# 12 Claim Calculations (60%)
# 4th Gen: 6
# 5th Gen: 6
# 5 General Queries (25%)
# 2 Formal Search (10%)
# 1 Quick Search (5%)

TEST_CASES = [
    # ---- CLAIM CALCULATIONS (4th Gen) ----
    {
        "type": "claim", "id": "claim_4_benefit_outpatient",
        "payload": {
            "items": [{"input_name": "급여 처방약", "claimed_amount": "30000", "quantity": "1", "user_category_hint": "처방약"}],
            "context": {"visit_type": "outpatient", "policy_generation": "4th", "facility_grade": "clinic"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "8000"} # 4th gen prescription min deductible is 8000
    },
    {
        "type": "claim", "id": "claim_4_manual_therapy",
        "payload": {
            "items": [{"input_name": "도수치료", "claimed_amount": "100000", "quantity": "1", "user_category_hint": "비급여"}],
            "context": {"visit_type": "outpatient", "policy_generation": "4th", "facility_grade": "clinic"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "30000"} # 100,000 * 0.3 = 30k. Min is 30k.
    },
    {
        "type": "claim", "id": "claim_4_mri",
        "payload": {
            "items": [{"input_name": "MRI", "claimed_amount": "500000", "quantity": "1", "user_category_hint": "비급여"}],
            "context": {"visit_type": "outpatient", "policy_generation": "4th", "facility_grade": "general_hospital"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "150000"} # 500,000 * 0.3 = 150k
    },
    {
        "type": "claim", "id": "claim_4_benefit_inpatient",
        "payload": {
            "items": [{"input_name": "입원실료", "claimed_amount": "1000000", "quantity": "1", "user_category_hint": "급여"}],
            "context": {"visit_type": "hospitalization", "policy_generation": "4th"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "0", "fallback_ratio_check": "0.2"} # Usually 20%, wait let's just check if it returns
    },
    {
        "type": "claim", "id": "claim_4_cancer",
        "payload": {
            "items": [{"input_name": "표적항암약물치료", "claimed_amount": "2000000", "quantity": "1", "user_category_hint": "중증 비급여"}],
            "context": {"visit_type": "outpatient", "policy_generation": "4th", "facility_grade": "tertiary_hospital"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "600000"} # 2M * 0.3 = 600k
    },
    {
        "type": "claim", "id": "claim_4_mixed",
        "payload": {
            "items": [
                {"input_name": "진찰료", "claimed_amount": "20000", "quantity": "1", "user_category_hint": "급여"},
                {"input_name": "초음파", "claimed_amount": "80000", "quantity": "1", "user_category_hint": "비급여"}
            ],
            "context": {"visit_type": "outpatient", "policy_generation": "4th", "facility_grade": "hospital"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible_range": True} # Just ensure it processes multi-items
    },

    # ---- CLAIM CALCULATIONS (5th Gen) ----
    {
        "type": "claim", "id": "claim_5_benefit_outpatient",
        "payload": {
            "items": [{"input_name": "급여 처방약", "claimed_amount": "30000", "quantity": "1", "user_category_hint": "처방약"}],
            "context": {"visit_type": "outpatient", "policy_generation": "5th", "facility_grade": "clinic"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "8000"} # 5th gen prescription min is 8000
    },
    {
        "type": "claim", "id": "claim_5_manual_therapy",
        "payload": {
            "items": [{"input_name": "도수치료", "claimed_amount": "100000", "quantity": "1", "user_category_hint": "비중증비급여"}],
            "context": {"visit_type": "outpatient", "policy_generation": "5th", "facility_grade": "clinic"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "50000"} # 100k * 0.5 = 50k. Min is 50k.
    },
    {
        "type": "claim", "id": "claim_5_mri",
        "payload": {
            "items": [{"input_name": "MRI", "claimed_amount": "500000", "quantity": "1", "user_category_hint": "3대비급여"}],
            "context": {"visit_type": "outpatient", "policy_generation": "5th", "facility_grade": "general_hospital"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "250000"} # 500k * 0.5 = 250k
    },
    {
        "type": "claim", "id": "claim_5_benefit_inpatient",
        "payload": {
            "items": [{"input_name": "입원실료", "claimed_amount": "1000000", "quantity": "1", "user_category_hint": "급여"}],
            "context": {"visit_type": "hospitalization", "policy_generation": "5th"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "200000"} # 1M * 0.2 = 200k
    },
    {
        "type": "claim", "id": "claim_5_cancer",
        "payload": {
            "items": [{"input_name": "표적항암약물치료", "claimed_amount": "2000000", "quantity": "1", "user_category_hint": "중증비급여"}],
            "context": {"visit_type": "outpatient", "policy_generation": "5th", "facility_grade": "tertiary_hospital"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible": "600000"} # 2M * 0.3 = 600k (Serious non-benefit in 5th gen is 30%)
    },
    {
        "type": "claim", "id": "claim_5_mixed",
        "payload": {
            "items": [
                {"input_name": "진찰료", "claimed_amount": "20000", "quantity": "1", "user_category_hint": "급여"},
                {"input_name": "초음파", "claimed_amount": "80000", "quantity": "1", "user_category_hint": "비급여"}
            ],
            "context": {"visit_type": "outpatient", "policy_generation": "5th", "facility_grade": "hospital"},
            "index_mode": "v2_only"
        },
        "expect": {"deductible_range": True}
    },

    # ---- CHAT: GENERAL (25% = 5) ----
    {
        "type": "chat", "id": "chat_general_1",
        "payload": {"query": "4세대 실손에서 비급여 도수치료 연간 보장 한도와 횟수는?", "mode": "general", "index_mode": "v2_only"},
        "expect": {"keywords": ["350만원", "50회"]}
    },
    {
        "type": "chat", "id": "chat_general_2",
        "payload": {"query": "5세대 실손에서 비중증 비급여의 본인부담률은 얼마인가요?", "mode": "general", "index_mode": "v2_only"},
        "expect": {"keywords": ["50%"]}
    },
    {
        "type": "chat", "id": "chat_general_3",
        "payload": {"query": "백내장 수술 시 다초점 렌즈 비용은 실손 보상이 되나요?", "mode": "general", "index_mode": "v2_only"},
        "expect": {"keywords": ["면책", "보상하지", "않습니다", "제외"]}
    },
    {
        "type": "chat", "id": "chat_general_4",
        "payload": {"query": "갑상선 결절 고주파 절제술의 보상 요건을 설명해줘.", "mode": "general", "index_mode": "v2_only"},
        "expect": {"keywords": ["결절", "크기", "고주파"]}
    },
    {
        "type": "chat", "id": "chat_general_5",
        "payload": {"query": "해외 의료기관에서 발생한 의료비도 실손 청구가 가능한가요?", "mode": "general", "index_mode": "v2_only"},
        "expect": {"keywords": ["해외", "의료기관", "제외", "면책"]}
    },

    # ---- CHAT: FORMAL (10% = 2) ----
    {
        "type": "chat", "id": "chat_formal_1",
        "payload": {"query": "도수치료 보상 제외 조건 4세대 약관 찾아줘", "mode": "formal", "index_mode": "v2_only"},
        "expect": {"keywords": ["도수치료", "보상하지 않는"]}
    },
    {
        "type": "chat", "id": "chat_formal_2",
        "payload": {"query": "자동차보험에서 보상받은 의료비의 실손 약관", "mode": "formal", "index_mode": "v2_only"},
        "expect": {"keywords": ["자동차보험", "보상받은", "제외"]}
    },

    # ---- CHAT: QUICK (5% = 1) ----
    {
        "type": "chat", "id": "chat_quick_1",
        "payload": {"query": "질병코드 J20.9 (급성 기관지염) 실손 청구 가능해?", "mode": "quick", "index_mode": "v2_only"},
        "expect": {"keywords": ["J20.9", "보상", "가능"]}
    }
]

async def run_test(client, model, test):
    payload = test["payload"].copy()
    payload["model"] = model

    result = {"model": model, "id": test["id"], "type": test["type"], "status": "FAIL", "reason": "", "time_ms": 0}
    start = time.time()

    try:
        if test["type"] == "claim":
            res = await client.post(f"{API_BASE}/claim/calculate", json=payload, timeout=30.0)
            if res.status_code != 200:
                result["reason"] = f"HTTP {res.status_code}: {res.text}"
            else:
                data = res.json()
                result["output"] = data
                expect = test["expect"]
                if "deductible" in expect:
                    if str(data.get("deductible")) == expect["deductible"]:
                        result["status"] = "PASS"
                    else:
                        result["reason"] = f"Expected deductible {expect['deductible']} but got {data.get('deductible')}"
                else:
                    result["status"] = "PASS" # for mixed cases, just ensure 200 OK
        else:
            # Stream chat endpoint
            # Actually, to make testing easy without stream parsing, we can hit standard HTTP chat if exists,
            # or just consume SSE
            headers = {"Accept": "text/event-stream"}
            async with client.stream("POST", f"{API_BASE}/chat/stream", json=payload, headers=headers, timeout=60.0) as res:
                if res.status_code != 200:
                    result["reason"] = f"HTTP {res.status_code}"
                else:
                    full_text = ""
                    async for line in res.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                d = json.loads(line[6:])
                                if "answer" in d:
                                    full_text = d["answer"]
                            except:
                                pass
                    result["output"] = full_text

                    # Keyword check
                    missed = []
                    for kw in test["expect"]["keywords"]:
                        if kw not in full_text:
                            missed.append(kw)

                    if not missed:
                        result["status"] = "PASS"
                    else:
                        # try basic normalization
                        passed = True
                        for m in missed:
                            if m.replace(" ", "") not in full_text.replace(" ", ""):
                                passed = False
                        if passed:
                            result["status"] = "PASS"
                        else:
                            result["reason"] = f"Missing keywords: {missed}"
    except Exception as e:
        result["reason"] = f"Exception: {str(e)}"

    result["time_ms"] = int((time.time() - start) * 1000)
    return result

async def main():
    results = []
    async with httpx.AsyncClient(cookies={'access_token': ACCESS_TOKEN}) as client:
        for model in MODELS:
            print(f"\\n--- Testing Model: {model} ---")
            for t in TEST_CASES:
                res = await run_test(client, model, t)
                results.append(res)
                print(f"[{res['status']}] {res['id']} ({res['time_ms']}ms)")
                if res['status'] == "FAIL":
                    print(f"  -> {res['reason']}")

    with open("/srv/ai-ops/logs/e2e_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
