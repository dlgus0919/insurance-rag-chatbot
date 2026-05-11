#!/usr/bin/env python3
"""클라우드 첫 부팅 시 인덱스 자산을 외부 URL에서 다운로드한다."""

from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import zipfile

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config


def main() -> int:
    """INDEX_RELEASE_URL이 설정되고 인덱스가 비어 있으면 zip 자산을 내려받는다."""

    if os.getenv("REBUILD_INDEX_FROM_CHUNKS", "false").lower() == "true":
        if not (config.CHROMA_DIR.exists() and any(config.CHROMA_DIR.iterdir())):
            print("ChromaDB가 비어있습니다. chunks.jsonl에서 인덱스를 재빌드합니다...")
            from scripts.build_cloud_index import rebuild_from_chunks

            rebuild_from_chunks()
            print("인덱스 재빌드 완료")
        else:
            print("ChromaDB 존재 - 재빌드 스킵")
        return 0

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
