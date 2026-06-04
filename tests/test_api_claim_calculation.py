import pytest

from src.api.routes import claim
from src.api.schemas.claim import ClaimCalculationRequest, ClaimItemRequest
from src.auth import users
from src.auth.users import User


def _employee() -> User:
    return User("employee01", "hash", users.ROLE_EMPLOYEE, "직원", "2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z")


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
            ]
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
    assert response.requires_review is False


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
            index_mode="v2_only",
        ),
        request=None,
        user=_employee(),
        db=None,
    )

    assert captured["top_k"] == 6
    assert captured["index_mode"] == "v2_only"
    assert response.claimed_amount == "100000"
