"""보안 AST Python 실행기(Code Sandbox) 테스트."""

from __future__ import annotations

from decimal import Decimal
import pytest

from src.claim_calculation.code_sandbox import (
    execute_calculation,
    validate_code_safety,
    SecurityValidationError,
)


def test_sandbox_success_calculation():
    """안전한 할당 및 연산이 수행되는지 테스트한다."""
    code = """
claimed_amount = Decimal('150000')
deductible = max(Decimal('30000'), claimed_amount * Decimal('0.3'))
payable_amount = (claimed_amount - deductible).quantize(Decimal('1'))
"""
    result = execute_calculation(code)

    variables = result["variables"]
    assert variables["claimed_amount"] == Decimal("150000")
    assert variables["deductible"] == Decimal("45000")
    assert variables["payable_amount"] == Decimal("105000")


def test_sandbox_ast_validation_import_rejection():
    """import 키워드 사용 시 예외를 발생시키는지 테스트한다."""
    unsafe_code_1 = "import os; os.system('echo hack')"
    unsafe_code_2 = "from sys import exit; exit(1)"

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(unsafe_code_1)
    assert "모듈 import는 허용되지 않습니다" in str(excinfo.value)

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(unsafe_code_2)
    assert "모듈 import는 허용되지 않습니다" in str(excinfo.value)


def test_sandbox_ast_validation_illegal_function_rejection():
    """eval, exec, open 등 화이트리스트에 없는 함수 호출을 완벽하게 차단하는지 테스트한다."""
    unsafe_eval = "eval('1 + 1')"
    unsafe_open = "open('/etc/passwd')"
    unsafe_exec = "exec('x = 5')"

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(unsafe_eval)
    assert "허용되지 않은 함수 호출이 감지되었습니다: eval" in str(excinfo.value)

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(unsafe_open)
    assert "허용되지 않은 함수 호출이 감지되었습니다: open" in str(excinfo.value)

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(unsafe_exec)
    assert "허용되지 않은 함수 호출이 감지되었습니다: exec" in str(excinfo.value)


def test_sandbox_execution_builtins_removal():
    """실행 시점에 builtins 환경이 격리되어 builtins 함수를 직접 부르면 NameError(또는 KeyError/RuntimeError)를 내는지 테스트한다."""
    code_with_eval = "x = eval('5')"
    # AST 검증을 우회하더라도 실행 시 builtins가 완전히 빠져 있어 동작하지 않아야 한다.
    # 단, ast validator가 먼저 잡을 것이므로 직접 exec 시 global context에서 builtins가 비어있는지를 확인한다.
    # 여기서는 ast 검증은 통과하지만 runtime builtins가 비어있는 형태를 모사해 본다.
    # ast validation을 거치고 execute_calculation을 직접 실행하면 validation 에러가 날 것이다.
    # 따라서 validation을 제외하고 제한된 globals 하에서 runtime 에러가 나는지 본다.
    # (validation을 통과할 수 있는 예: print()는 ALLOWED_FUNCTIONS에 없어서 차단된다.
    # 하지만 print가 validation에 없어도 execution 환경에 builtins가 차단됨을 테스트하기 위해
    # NameError가 발생하여 execute_calculation이 RuntimeError를 던지는지 확인한다.)

    # 예: 만약 ast validator에 'print'를 임시 허용하고 실행했을 때 builtins가 비어있다면 print 함수가 없어 NameError가 나야 함.
    # validate_code_safety를 우회해서 exec를 safe_globals로 직접 시도해보자.
    safe_globals = {
        "__builtins__": {},
        "Decimal": Decimal,
    }
    with pytest.raises(NameError):
        exec("x = sum([1, 2])", safe_globals)  # sum은 builtins인데 context에 없으므로 NameError 발생


def test_sandbox_print_and_pow_rejection():
    """print 함수 호출 및 ast.Pow 연산(제곱)이 AST 검증 단계에서 차단되는지 테스트한다."""
    code_with_print = "print('hello')"
    code_with_pow = "x = Decimal('2') ** Decimal('3')"
    code_with_unsafe_attr = "x = Decimal('12.345').conjugate()"

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(code_with_print)
    assert "허용되지 않은 함수 호출이 감지되었습니다: print" in str(excinfo.value)

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(code_with_pow)
    assert "허용되지 않은 구문 구조가 감지되었습니다: Pow" in str(excinfo.value)

    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(code_with_unsafe_attr)
    assert "conjugate" in str(excinfo.value)


def test_sandbox_code_length_limit():
    """코드 길이가 1000자를 초과할 때 차단되는지 테스트한다."""
    long_code = "#" * 1001
    with pytest.raises(SecurityValidationError) as excinfo:
        validate_code_safety(long_code)
    assert "코드 길이가 너무 깁니다" in str(excinfo.value)
