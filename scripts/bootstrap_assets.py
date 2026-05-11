#!/usr/bin/env python3
"""클라우드 첫 부팅 시 인덱스 자산을 외부 URL에서 다운로드한다."""

from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config


def _asset_marker() -> Path:
    return config.ROOT_DIR / "data" / "index" / ".assets_complete"


def _asset_lock() -> Path:
    return config.ROOT_DIR / "data" / "index" / ".assets_download.lock"


def _index_ready() -> bool:
    return _asset_marker().exists() and (config.CHROMA_DIR / "chroma.sqlite3").exists()


def _acquire_lock(timeout_sec: int = 300) -> bool:
    asset_lock = _asset_lock()
    asset_lock.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    while True:
        try:
            fd = os.open(asset_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _index_ready():
                return False
            if time.monotonic() - started >= timeout_sec:
                raise TimeoutError("인덱스 자산 다운로드 락 대기 시간이 초과되었습니다.")
            time.sleep(1)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(str(os.getpid()))
        return True


def _release_lock() -> None:
    try:
        _asset_lock().unlink()
    except FileNotFoundError:
        pass


def _clear_partial_assets() -> None:
    _asset_marker().unlink(missing_ok=True)
    if config.CHROMA_DIR.exists():
        shutil.rmtree(config.CHROMA_DIR)


def _safe_extract(zf: zipfile.ZipFile) -> None:
    root = config.ROOT_DIR.resolve()
    for member in zf.infolist():
        target = (config.ROOT_DIR / member.filename).resolve()
        if root not in (target, *target.parents):
            raise RuntimeError(f"zip 경로가 프로젝트 밖을 가리킵니다: {member.filename}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)


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
    if _index_ready():
        print("인덱스가 이미 존재합니다 - 스킵")
        return 0
    print(f"인덱스 자산 다운로드: {url}")
    lock_acquired = False
    try:
        lock_acquired = _acquire_lock()
        if not lock_acquired:
            print("인덱스가 이미 존재합니다 - 스킵")
            return 0
        if _index_ready():
            print("인덱스가 이미 존재합니다 - 스킵")
            return 0
        _clear_partial_assets()
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            _safe_extract(zf)
        asset_marker = _asset_marker()
        asset_marker.parent.mkdir(parents=True, exist_ok=True)
        asset_marker.write_text("complete\n", encoding="utf-8")
        print("다운로드 완료")
        return 0
    except Exception as exc:
        print(f"다운로드 실패: {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_acquired:
            _release_lock()


if __name__ == "__main__":
    sys.exit(main())
