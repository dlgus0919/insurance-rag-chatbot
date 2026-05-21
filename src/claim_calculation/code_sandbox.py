"""안전한 Python AST 샌드박스 실행기."""

from __future__ import annotations

import ast
import io
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal
from typing import Any, Dict


class SecurityValidationError(Exception):
    """샌드박스 보안 검증 실패 에러."""
    pass


class SafeASTVisitor(ast.NodeVisitor):
    """AST 노드를 순회하며 허용된 안전한 구문만 사용하는지 검증한다."""

    # 허용된 함수/클래스 생성자 목록
    ALLOWED_FUNCTIONS = {"Decimal", "max", "min", "abs"}

    # 허용된 노드 타입 화이트리스트
    ALLOWED_NODES = {
        ast.Module,
        ast.Expr,
        ast.Assign,
        ast.Name,
        ast.Constant,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.BoolOp,
        ast.If,
        ast.IfExp,
        ast.Load,
        ast.Store,
        ast.Call,
        ast.Attribute,
        # 연산자들
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.USub,
        ast.UAdd,
        # 비교 연산자들
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        # 논리 연산자들
        ast.And,
        ast.Or,
    }

    def visit(self, node: ast.AST) -> None:
        # Import 조기 차단
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SecurityValidationError("모듈 import는 허용되지 않습니다.")

        # 노드 타입 검증
        node_type = type(node)
        if node_type not in self.ALLOWED_NODES:
            # Python < 3.8 호환성을 위한 구 버전 AST 노드 허용
            if node_type.__name__ in ("Num", "Str", "Bytes", "NameConstant"):
                pass
            else:
                raise SecurityValidationError(
                    f"허용되지 않은 구문 구조가 감지되었습니다: {node_type.__name__}"
                )
        super().visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Call 노드 검증: 화이트리스트에 정의된 함수만 호출 가능하다."""
        # func이 단순 변수명(ast.Name)인 경우만 허용
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name not in self.ALLOWED_FUNCTIONS:
                raise SecurityValidationError(
                    f"허용되지 않은 함수 호출이 감지되었습니다: {func_name}"
                )
        elif isinstance(node.func, ast.Attribute):
            # Decimal 객체의 메서드(예: quantize) 등은 안전하므로 Attribute 호출 자체는 허용하되,
            # base 객체가 Name이고 호출하려는 속성이 안전한 것인지 보수적으로 체크할 수 있다.
            # 여기서는 Decimal.quantize와 같은 호출을 허용하기 위해 Attribute 검증을 수행한다.
            attr_name = node.func.attr
            allowed_attrs = {"quantize"}
            if attr_name not in allowed_attrs:
                raise SecurityValidationError(
                    f"허용되지 않은 메서드 호출이 감지되었습니다: {attr_name}"
                )
        else:
            raise SecurityValidationError("지원되지 않는 형태의 함수 호출입니다.")

        # 인자(args, keywords)들도 재귀적으로 검증
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        raise SecurityValidationError("모듈 import는 허용되지 않습니다.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise SecurityValidationError("모듈 import는 허용되지 않습니다.")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Attribute 접근 검증: Decimal 객체의 quantize 속성 접근만 허용한다."""
        if node.attr != "quantize":
            raise SecurityValidationError(
                f"허용되지 않은 속성 접근이 감지되었습니다: {node.attr}"
            )
        self.generic_visit(node)


def validate_code_safety(code_str: str) -> None:
    """코드가 안전한지 AST 검증을 수행한다."""
    if len(code_str) > 1000:
        raise SecurityValidationError("코드 길이가 너무 깁니다. (최대 1000자)")
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        raise SecurityValidationError(f"구문 오류가 발생했습니다: {e}")

    visitor = SafeASTVisitor()
    visitor.visit(tree)


def execute_calculation(code_str: str) -> dict[str, Any]:
    """제한된 안전한 환경에서 Python 코드를 실행하고 전역 변수 상태와 출력을 반환한다.

    - AST 안전성 검증 선행
    - builtins가 제거된 제한된 globals 사용
    - stdout/stderr 캡처
    """
    validate_code_safety(code_str)

    # 제한된 globals 설정
    safe_globals: dict[str, Any] = {
        "__builtins__": {},
        "Decimal": Decimal,
        "max": max,
        "min": min,
        "abs": abs,
    }
    # 실행 시점의 변수들을 담을 locals 딕셔너리
    local_vars: dict[str, Any] = {}

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            # exec 실행
            exec(code_str, safe_globals, local_vars)
    except Exception as e:
        raise RuntimeError(f"실행 중 런타임 에러 발생: {e}") from e

    # 결과 변수 딕셔너리에서 Decimal 타입의 변수들을 직렬화하기 쉽도록 가공하거나 반환
    return {
        "variables": local_vars,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
    }
