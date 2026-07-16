"""Ollama HTTP 클라이언트."""

from __future__ import annotations

import json as jsonlib
from urllib.parse import urljoin

import requests

from src import config


class OllamaClient:
    """Ollama `/api/generate`를 호출하는 얇은 클라이언트."""

    provider = "ollama"

    def __init__(
        self,
        host: str,
        model: str,
        num_ctx: int | None = None,
        num_predict: int | None = None,
    ):
        self.host = host.rstrip("/") + "/"
        self.model = model
        self.num_ctx = num_ctx if num_ctx is not None else config.OLLAMA_NUM_CTX
        self.num_predict = num_predict if num_predict is not None else config.OLLAMA_NUM_PREDICT

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        num_ctx: int | None = None,
        num_predict: int | None = None,
    ) -> str:
        """프롬프트를 보내고 생성된 답변 문자열을 반환한다."""

        selected_num_ctx = num_ctx if num_ctx is not None else self.num_ctx
        selected_num_predict = num_predict if num_predict is not None else self.num_predict
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": selected_num_ctx,
                "num_predict": selected_num_predict,
            },
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

    def generate_stream(self, prompt: str, system: str = "", temperature: float = 0.2):
        """프롬프트를 보내고 생성 토큰을 순서대로 반환한다."""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        try:
            with requests.post(
                urljoin(self.host, "api/generate"),
                json=payload,
                stream=True,
                timeout=180,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = jsonlib.loads(line)
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
        except requests.RequestException as exc:
            raise RuntimeError(
                "Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요."
            ) from exc

    def list_models(self) -> list[str]:
        """Ollama에 설치된 모델 이름 목록을 반환한다. 실패 시 빈 리스트."""

        return self._list_model_names("api/tags")

    def list_running_models(self) -> list[str]:
        """Ollama가 현재 메모리에 올려 서빙하는 모델 이름을 반환한다."""

        return self._list_model_names("api/ps")

    def _list_model_names(self, path: str) -> list[str]:
        try:
            response = requests.get(urljoin(self.host, path), timeout=5)
        except requests.RequestException:
            return []
        if response.status_code >= 400:
            return []
        data = response.json()
        names: list[str] = []
        for model in data.get("models", []):
            name = model.get("name")
            if not name:
                continue
            names.append(name)
            if name.endswith(":latest"):
                names.append(name.removesuffix(":latest"))
        return list(dict.fromkeys(names))

    def health(self) -> bool:
        """Ollama 서버 접근 가능 여부를 반환한다."""

        try:
            response = requests.get(urljoin(self.host, "api/tags"), timeout=5)
        except requests.RequestException:
            return False
        return response.status_code < 400
