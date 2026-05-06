#!/usr/bin/env python3
"""클라우드 첫 부팅 시 인덱스 자산을 외부 URL에서 다운로드한다."""

from __future__ import annotations

import io
import os
import sys
import zipfile

import requests

from src import config


def main() -> int:
    """INDEX_RELEASE_URL이 설정되고 인덱스가 비어 있으면 zip 자산을 내려받는다."""

    url = os.getenv("INDEX_RELEASE_URL")
    if not url:
        print("INDEX_RELEASE_URL 미설정 - 스킵")
        return 0
    if config.CHROMA_DIR.exists() and any(config.CHROMA_DIR.iterdir()):
        print("인덱스가 이미 존재합니다 - 스킵")
        return 0
    print(f"인덱스 자산 다운로드: {url}")
    try:
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(config.ROOT_DIR)
        print("다운로드 완료")
        return 0
    except Exception as exc:
        print(f"다운로드 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
