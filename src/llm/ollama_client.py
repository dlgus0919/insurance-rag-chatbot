"""Ollama HTTP 클라이언트."""

from __future__ import annotations

from urllib.parse import urljoin

import requests


class OllamaClient:
    """Ollama `/api/generate`를 호출하는 얇은 클라이언트."""

    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/") + "/"
        self.model = model

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int = 8192) -> str:
        """프롬프트를 보내고 생성된 답변 문자열을 반환한다."""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
        }
        try:
            response = requests.post(urljoin(self.host, "api/generate"), json=payload, timeout=120)
        except requests.RequestException as exc:
            raise RuntimeError(
                "Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요."
            ) from exc

        if response.status_code >= 400:
            raise RuntimeError(
                f"Ollama 생성 요청이 실패했습니다(status={response.status_code}). "
                f"모델 이름 `{self.model}`이 설치되어 있는지 확인하세요."
            )

        data = response.json()
        answer = data.get("response", "")
        if not answer:
            raise RuntimeError("Ollama 응답이 비어 있습니다.")
        return answer.strip()

    def health(self) -> bool:
        """Ollama 서버 접근 가능 여부를 반환한다."""

        try:
            response = requests.get(urljoin(self.host, "api/tags"), timeout=5)
        except requests.RequestException:
            return False
        return response.status_code < 400
