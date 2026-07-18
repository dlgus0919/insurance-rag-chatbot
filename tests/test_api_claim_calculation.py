import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.db import Base
from src.api.models import ChatMessage, ChatSession
from src.api.routes import claim
from src.api.schemas.claim import ClaimCalculationRequest, ClaimItemRequest
from src.auth import users
from src.auth.users import User


def _employee() -> User:
    return User("employee01", "hash", users.ROLE_EMPLOYEE, "직원", "2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z")


@pytest.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'claim_chat.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session

    await engine.dispose()


def test_claim_default_model_uses_answer_primary_sglang(monkeypatch) -> None:
    monkeypatch.setattr(claim.config, "SGLANG_DEFAULT_MODEL", "qwen3-next-80b-a3b-instruct-fp8")

    selected = claim._select_model(
        ClaimCalculationRequest(items=[ClaimItemRequest(input_name="도수치료")])
    )

    assert selected == "sglang:qwen3-next-80b-a3b-instruct-fp8"


@pytest.mark.anyio
async def test_claim_calculation_route_returns_payable_amount(monkeypatch) -> None:
    """4세대 도수치료 단일 보상 코드의 순수 계산 route를 검증한다.

    실사용 심사에서는 한도/횟수/특약 증빙에 따라 별도 review가 붙을 수 있지만,
    이 API 단위 테스트는 명시 입력 코드가 보상 의견으로 확정된 경로의 금액 산출만
    고정한다.
    """

    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.db.standard_codes.lookup_by_std_cd",
        lambda *_args, **_kwargs: {
            "std_cd": "MX122",
            "std_cd_nm": "도수치료",
            "mid_category_cd_nm": "3대비급여",
            "pay_opn_cd_nm": "보상",
        },
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="도수치료",
                    input_code="MX122",
                    claimed_amount="150000",
                    quantity="1",
                    user_category_hint="3대비급여",
                )
            ],
            context={
                "policy_generation": "4th",
                "visit_type": "outpatient",
                "coverage_topic": "실손, 3대비급여",
            },
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert response.claimed_amount == "150000"
    assert response.deductible == "45000"
    assert response.payable_amount == "105000"
    assert response.policy_generation == "4th"
    assert response.line_results[0]["input_name"] == "도수치료"
    assert response.requires_review is True
    assert response.line_results[0]["requires_review"] is True
    assert any("누적 청구 이력이 없어 승인 룰의 연간 한도" in reason for reason in response.review_reasons)
    assert any("상해 또는 질병의 치료 목적" in reason for reason in response.line_results[0]["review_reasons"])



@pytest.mark.anyio
async def test_claim_calculation_route_requires_code_selection_before_manual_therapy_payout(monkeypatch) -> None:
    """항목명만으로는 4세대 도수치료 전용 룰을 적용하지 않는다."""

    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.db.standard_codes.search_by_name",
        lambda *_args, **_kwargs: [
            {
                "std_cd": "MX122",
                "std_cd_nm": "도수치료",
                "mid_category_cd_nm": "3대비급여",
                "pay_opn_cd_nm": "보상",
            }
        ],
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="도수치료",
                    claimed_amount="500000",
                    nonpay_amount="500000",
                    user_category_hint="3대비급여",
                )
            ],
            context={
                "policy_generation": "4th",
                "visit_type": "outpatient",
                "special_calculation_status": "unknown",
            },
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert response.calculation_status == "blocked_missing_info"
    assert response.deductible is None
    assert response.payable_amount is None
    assert response.candidates[0]["code"] == "MX122"
    assert response.line_results[0]["calculation_status"] == "needs_code_selection"
    assert response.line_results[0]["deductible"] is None
    assert response.line_results[0]["payable_amount"] is None
    rendered = claim._claim_response_text(response)
    assert "예상 지급금액: 산정 보류" in rendered
    assert "None원" not in rendered


@pytest.mark.anyio
async def test_claim_calculation_route_rejects_bad_amount(monkeypatch) -> None:
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.db.standard_codes.search_by_name", lambda *_args, **_kwargs: [])

    with pytest.raises(Exception) as exc_info:
        await claim.calculate_claim(
            ClaimCalculationRequest(
                items=[
                    ClaimItemRequest(
                        input_name="도수치료",
                        claimed_amount="0",
                        quantity="1",
                    )
                ]
            ),
            request=None,
            user=_employee(),
            db=None,
        )

    assert "금액은 0보다 큰 양수" in str(exc_info.value)


@pytest.mark.anyio
async def test_claim_calculation_route_accepts_generation_and_multiple_items(monkeypatch) -> None:
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.db.standard_codes.search_by_name",
        lambda input_name, *_args, **_kwargs: [{
            "std_cd": "STD001" if "급여" in input_name else "STD002",
            "std_cd_nm": input_name,
            "mid_category_cd_nm": "급여" if "급여 진료비" in input_name else "비중증비급여",
            "pay_opn_cd_nm": "보상",
        }],
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(input_name="급여 진료비", claimed_amount="100000", user_category_hint="급여"),
                ClaimItemRequest(input_name="비급여 주사료", claimed_amount="200000", user_category_hint="비중증비급여"),
            ],
            context={"policy_generation": "5th", "visit_type": "outpatient", "coverage_topic": "실손"},
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert response.policy_generation == "5th"
    assert response.claimed_amount == "300000"
    assert response.deductible == "120000"
    assert response.payable_amount == "180000"
    assert len(response.line_results) == 2


@pytest.mark.anyio
async def test_claim_calculation_route_accepts_split_receipt_amounts(monkeypatch) -> None:
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.db.standard_codes.lookup_by_std_cd",
        lambda *_args, **_kwargs: {
            "std_cd": "L1213",
            "std_cd_nm": "척추마취관리기본[1시간기준]",
            "mid_category_cd_nm": "마취료",
            "hira_care_type_cd_nm": "급여",
            "ins_care_type_cd_nm": "급여",
            "pay_opn_cd_nm": "급여외 산정불가",
        },
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="마취료",
                    input_code="L1213",
                    insured_copay_amount="23434",
                    nonpay_amount="0",
                    quantity="1",
                    user_category_hint="급여",
                    extra_info="입원 중 수술 마취",
                )
            ],
            context={"policy_generation": "5th", "visit_type": "hospitalization", "coverage_topic": "실손"},
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert response.claimed_amount == "23434"
    assert response.payable_amount == "18747"
    assert response.deductible == "4687"
    assert response.line_results[0]["insured_copay_amount"] == "23434"
    assert "급여외 산정불가" in response.applied_basis[0]["content"]


@pytest.mark.anyio
async def test_claim_calculation_route_uses_fixed_rag_top_k(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_rag_pipeline(model: str, top_k: int, index_mode: str):
        captured["model"] = model
        captured["top_k"] = top_k
        captured["index_mode"] = index_mode
        return None

    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", fake_get_rag_pipeline)
    monkeypatch.setattr(
        "src.db.standard_codes.search_by_name",
        lambda *_args, **_kwargs: [{
            "std_cd": "STD001",
            "std_cd_nm": "도수치료",
            "mid_category_cd_nm": "비중증비급여",
            "pay_opn_cd_nm": "보상",
        }],
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="도수치료",
                    claimed_amount="100000",
                    quantity="1",
                    user_category_hint="비중증비급여",
                )
            ],
            top_k=17,
            index_mode="default",
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert captured["top_k"] == 6
    assert captured["index_mode"] == "v2_only"
    assert response.claimed_amount == "100000"


@pytest.mark.anyio
async def test_claim_calculation_route_persists_history(monkeypatch, db_session) -> None:
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.db.standard_codes.lookup_by_std_cd",
        lambda *_args, **_kwargs: {
            "std_cd": "MX122",
            "std_cd_nm": "도수치료",
            "mid_category_cd_nm": "3대비급여",
            "pay_opn_cd_nm": "보상",
        },
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="도수치료",
                    input_code="MX122",
                    claimed_amount="150000",
                    user_category_hint="3대비급여",
                )
            ]
        ),
        request=None,
        user=_employee(),
        db=db_session,
    )

    assert response.session_id
    sessions = list((await db_session.execute(select(ChatSession))).scalars())
    messages = list((await db_session.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars())
    assert sessions[0].title == "보험금 계산: 도수치료"
    assert [message.role for message in messages] == ["user", "assistant"]
    assert "보험금 계산/5세대" in messages[0].content
    assert "예상 지급금액" in messages[1].content


@pytest.mark.anyio
async def test_claim_calculation_route_selected_mx122_allows_fourth_unknown_special_status(monkeypatch) -> None:
    """선택된 MX122는 4세대 산정특례 미확인 상태에서도 전용 승인 룰로 계산한다."""

    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "src.db.standard_codes.lookup_by_std_cd",
        lambda *_args, **_kwargs: {
            "std_cd": "MX122",
            "std_cd_nm": "도수치료",
            "mid_category_cd_nm": "3대비급여",
            "ins_care_type_cd_nm": "비급여_특약1",
            "pay_opn_cd_nm": "추가확인",
        },
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="도수치료",
                    input_code="MX122",
                    nonpay_amount="500000",
                    user_category_hint="3대비급여",
                )
            ],
            context={
                "policy_generation": "4th",
                "visit_type": "outpatient",
                "special_calculation_status": "unknown",
            },
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert response.special_calculation_status == "unknown"
    assert response.calculation_status == "estimated_review_required"
    assert response.deductible == "150000"
    assert response.payable_amount == "350000"
    assert response.line_results[0]["input_code"] == "MX122"
    assert response.line_results[0]["calculation_status"] == "calculated"
    assert any("연간 한도" in reason for reason in response.review_reasons)
    assert any("최초 10회 이후" in reason for reason in response.review_reasons)
@pytest.mark.anyio
async def test_claim_calculation_route_skips_rag_in_explicit_isolated_e2e_mode(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_get_rag_pipeline(*args, **_kwargs):
        calls.append(args)
        return None

    monkeypatch.setenv("INSURANCE_RAG_ISOLATED_E2E", "1")
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", fake_get_rag_pipeline)
    monkeypatch.setattr(
        "src.db.standard_codes.lookup_by_std_cd",
        lambda *_args, **_kwargs: {
            "std_cd": "MX122",
            "std_cd_nm": "도수치료",
            "mid_category_cd_nm": "3대비급여",
            "ins_care_type_cd_nm": "비급여_특약1",
            "pay_opn_cd_nm": "추가확인",
        },
    )

    response = await claim.calculate_claim(
        ClaimCalculationRequest(
            items=[
                ClaimItemRequest(
                    input_name="도수치료",
                    input_code="MX122",
                    nonpay_amount="500000",
                )
            ],
            context={
                "policy_generation": "4th",
                "visit_type": "outpatient",
                "special_calculation_status": "unknown",
            },
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert calls == []
    assert response.deductible == "150000"
    assert response.payable_amount == "350000"
