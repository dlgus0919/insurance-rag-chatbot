import pytest

from src.api.routes import claim
from src.api.schemas.claim import ClaimCalculationRequest, ClaimItemRequest
from src.auth import users
from src.auth.users import User


def _employee() -> User:
    return User("employee01", "hash", users.ROLE_EMPLOYEE, "직원", "2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z")


@pytest.mark.anyio
async def test_claim_calculation_route_returns_payable_amount(monkeypatch) -> None:
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)

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
    assert response.requires_review is True
    assert response.review_reasons


@pytest.mark.anyio
async def test_claim_calculation_route_rejects_bad_amount(monkeypatch) -> None:
    monkeypatch.setattr("src.api.routes.claim.get_rag_pipeline", lambda *_args, **_kwargs: None)

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
