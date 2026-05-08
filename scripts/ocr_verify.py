#!/usr/bin/env python3
"""D6/D7 스캔 PDF의 OCR 품질을 샘플 페이지로 검증한다."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import io
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KOREAN_RE = re.compile(r"[가-힣]")
NOISE_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.,·\-()]")
ENGINE_LABELS = {"tesseract": "tesseract", "easyocr": "easyocr  "}


@dataclass(frozen=True)
class PageResult:
    page_no: int
    metrics: dict
    elapsed_sec: float
    output_file: Path


def sample_page_indices(total_pages: int, n: int = 10) -> list[int]:
    """총 페이지에서 n개를 균등 간격으로 선택한다. 반환값은 0-indexed다."""

    if total_pages <= 0 or n <= 0:
        return []
    if total_pages <= n:
        return list(range(total_pages))
    step = total_pages / n
    return [int(index * step) for index in range(n)]


def page_to_image(pdf_path: str | Path, page_no: int, dpi: int = 200):
    """PDF 페이지를 그레이스케일 PIL Image로 변환한다."""

    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("PyMuPDF(fitz)가 설치되어 있지 않습니다.") from exc
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("Pillow가 설치되어 있지 않습니다.") from exc

    with fitz.open(pdf_path) as doc:
        if page_no < 0 or page_no >= doc.page_count:
            raise IndexError(f"page_no가 범위를 벗어났습니다: {page_no} / {doc.page_count}")
        page = doc[page_no]
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        image.load()
        return image


def ocr_tesseract(image) -> str:
    """Tesseract OCR로 한국어+영어 텍스트를 추출한다."""

    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("pytesseract가 설치되어 있지 않습니다. requirements-ocr.txt를 설치하세요.") from exc

    config = "--oem 3 --psm 3 -l kor+eng"
    try:
        return pytesseract.image_to_string(image, config=config)
    except Exception as exc:  # pragma: no cover - 시스템 OCR 환경 의존
        exc_name = exc.__class__.__name__
        message = str(exc)
        if exc_name == "TesseractNotFoundError":
            raise RuntimeError("tesseract 바이너리가 PATH에 없습니다. requirements-ocr.txt의 시스템 패키지 안내를 확인하세요.") from exc
        if "Error opening data file" in message or "Failed loading language" in message:
            raise RuntimeError("Tesseract 한국어/영어 언어 데이터(kor+eng)를 찾지 못했습니다.") from exc
        raise


def ocr_easyocr(image, reader) -> str:
    """EasyOCR reader로 한국어+영어 텍스트를 추출한다."""

    if reader is None:
        raise RuntimeError("EasyOCR reader가 초기화되지 않았습니다.")
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("numpy가 설치되어 있지 않습니다.") from exc

    result = reader.readtext(np.array(image), detail=0, paragraph=True)
    return "\n".join(result)


def quality_metrics(text: str) -> dict:
    """OCR 텍스트의 품질 지표를 계산한다."""

    total = len(text)
    if total == 0:
        return {"chars": 0, "korean_ratio": 0.0, "noise_ratio": 1.0, "grade": "FAIL"}

    korean = len(KOREAN_RE.findall(text))
    noise = len(NOISE_RE.findall(text))
    korean_ratio = korean / total
    noise_ratio = noise / total

    if korean_ratio >= 0.35 and noise_ratio <= 0.10 and total >= 200:
        grade = "PASS"
    elif korean_ratio >= 0.20 and total >= 100:
        grade = "MARGINAL"
    else:
        grade = "FAIL"

    return {
        "chars": total,
        "korean_ratio": round(korean_ratio, 3),
        "noise_ratio": round(noise_ratio, 3),
        "grade": grade,
    }


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("PyMuPDF(fitz)가 설치되어 있지 않습니다.") from exc
    with fitz.open(path) as doc:
        return doc.page_count


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _doc_label(doc_short: str) -> str:
    if doc_short == "실무가이드":
        return "실무가이드 (D6)"
    if doc_short == "상담사례집":
        return "상담사례집 (D7)"
    return doc_short


def summarize_engine(results: list[PageResult]) -> dict:
    """페이지별 결과를 엔진 단위 요약으로 집계한다."""

    metrics = [result.metrics for result in results]
    return {
        "avg_chars": round(sum(metric["chars"] for metric in metrics) / len(metrics), 1) if metrics else 0.0,
        "avg_korean_ratio": _average([metric["korean_ratio"] for metric in metrics]),
        "avg_noise_ratio": _average([metric["noise_ratio"] for metric in metrics]),
        "pass_count": sum(1 for metric in metrics if metric["grade"] == "PASS"),
        "marginal_count": sum(1 for metric in metrics if metric["grade"] == "MARGINAL"),
        "fail_count": sum(1 for metric in metrics if metric["grade"] == "FAIL"),
        "total": len(metrics),
        "elapsed_sec": round(sum(result.elapsed_sec for result in results), 1),
    }


def recommended_engine(engine_results: dict[str, list[PageResult]]) -> str:
    """PASS 수, MARGINAL 수, 평균 글자 수 기준으로 권장 엔진을 고른다."""

    if not engine_results:
        return "없음"
    ranked = []
    for engine, results in engine_results.items():
        summary = summarize_engine(results)
        ranked.append(
            (
                summary["pass_count"],
                summary["marginal_count"],
                summary["avg_chars"],
                engine,
            )
        )
    ranked.sort(reverse=True)
    return ranked[0][3]


def write_summary(
    output_path: Path,
    all_results: dict[str, dict[str, list[PageResult]]],
    page_counts: dict[str, int],
    sample_count: int,
    dpi: int,
    engine_errors: dict[tuple[str, str], str] | None = None,
) -> None:
    """OCR 검증 요약 파일을 작성한다."""

    engine_errors = engine_errors or {}
    lines = [
        "=== OCR 검증 요약 ===",
        f"실행일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"DPI: {dpi}",
        f"샘플 페이지: {sample_count}개 (균등 분산)",
        "",
    ]

    for doc_short, engine_results in all_results.items():
        lines.append(f"--- {_doc_label(doc_short)} ({page_counts.get(doc_short, 0)}p) ---")
        for engine, results in engine_results.items():
            summary = summarize_engine(results)
            label = ENGINE_LABELS.get(engine, engine)
            lines.append(
                f"[{label}] 평균 chars: {summary['avg_chars']}, "
                f"한글비율: {summary['avg_korean_ratio']}, "
                f"노이즈: {summary['avg_noise_ratio']}, "
                f"PASS: {summary['pass_count']}/{summary['total']}, "
                f"MARGINAL: {summary['marginal_count']}/{summary['total']}, "
                f"FAIL: {summary['fail_count']}/{summary['total']}, "
                f"소요: {summary['elapsed_sec']}초"
            )
            error = engine_errors.get((doc_short, engine))
            if error:
                lines.append(f"  ERROR: {error}")
        lines.append("")

    lines.append("=== 권장 엔진 ===")
    for doc_short, engine_results in all_results.items():
        engine = recommended_engine(engine_results)
        if engine == "없음":
            lines.append(f"{_doc_label(doc_short)}: 없음")
            continue
        summary = summarize_engine(engine_results[engine])
        lines.append(
            f"{_doc_label(doc_short)}: {engine} "
            f"(PASS {summary['pass_count']}/{summary['total']}, "
            f"MARGINAL {summary['marginal_count']}/{summary['total']})"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _init_easyocr_reader():
    try:
        import easyocr
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("easyocr가 설치되어 있지 않습니다. requirements-ocr.txt를 설치하세요.") from exc

    print("[ocr_verify] EasyOCR 초기화 중 (최초 실행 시 모델 다운로드 수분 소요)...")
    return easyocr.Reader(["ko", "en"], gpu=False)


def _run_engine(engine: str, image, reader) -> str:
    if engine == "tesseract":
        return ocr_tesseract(image)
    if engine == "easyocr":
        return ocr_easyocr(image, reader)
    raise ValueError(f"unknown engine: {engine}")


def run_verification(engine: str, pages: int, dpi: int, output_dir: Path) -> dict[str, dict[str, list[PageResult]]]:
    """대상 OCR 문서에 대해 지정 엔진 검증을 실행한다."""

    from src import config

    engines = ["tesseract", "easyocr"] if engine == "all" else [engine]
    reader = _init_easyocr_reader() if "easyocr" in engines else None
    targets = [source for source in config.PDF_SOURCES if source.requires_ocr and source.path.exists()]
    if not targets:
        raise RuntimeError("requires_ocr=True이며 파일이 존재하는 PDF 소스가 없습니다.")

    output_dir.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, dict[str, list[PageResult]]] = {}
    engine_errors: dict[tuple[str, str], str] = {}
    page_counts: dict[str, int] = {}

    for source in targets:
        total_pages = _pdf_page_count(source.path)
        page_counts[source.doc_short] = total_pages
        indices = sample_page_indices(total_pages, pages)
        print(f"[ocr_verify] {source.doc_short}: {total_pages}p, 샘플 {indices}")
        all_results[source.doc_short] = {}

        for engine_name in engines:
            print(f"[ocr_verify] 엔진 시작: {source.doc_short} / {engine_name}")
            engine_results: list[PageResult] = []
            try:
                for page_no in indices:
                    started = time.perf_counter()
                    image = page_to_image(source.path, page_no, dpi)
                    text = _run_engine(engine_name, image, reader)
                    elapsed_sec = time.perf_counter() - started
                    metrics = quality_metrics(text)

                    out_file = output_dir / f"{source.doc_short}_{engine_name}_p{page_no:03d}.txt"
                    out_file.write_text(text, encoding="utf-8")
                    engine_results.append(PageResult(page_no, metrics, elapsed_sec, out_file))
                    print(
                        f"  [{engine_name}] p{page_no:03d}: "
                        f"chars={metrics['chars']}, "
                        f"kor={metrics['korean_ratio']:.2f}, "
                        f"noise={metrics['noise_ratio']:.2f}, "
                        f"grade={metrics['grade']}, "
                        f"elapsed={elapsed_sec:.1f}s"
                    )
            except Exception as exc:  # pragma: no cover - 실제 OCR 엔진/원본 PDF 환경 의존
                error = f"{exc.__class__.__name__}: {exc}"
                engine_errors[(source.doc_short, engine_name)] = error
                print(f"  [{engine_name}] ERROR: {error}")
            all_results[source.doc_short][engine_name] = engine_results

    write_summary(output_dir / "summary.txt", all_results, page_counts, pages, dpi, engine_errors)
    print(f"\n[ocr_verify] 완료. 결과: {output_dir}/")
    return all_results


def main() -> int:
    parser = argparse.ArgumentParser(description="D6/D7 스캔 PDF OCR 품질 검증")
    parser.add_argument("--engine", choices=["tesseract", "easyocr", "all"], default="all")
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/ocr_sample"))
    args = parser.parse_args()

    run_verification(args.engine, args.pages, args.dpi, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
