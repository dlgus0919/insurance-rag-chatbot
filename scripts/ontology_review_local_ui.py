#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.candidate_display import format_candidate_for_practitioner
from src.ontology.hold_feedback import HOLD_REASONS, normalize_hold_reason_codes
from src.ontology.review_store import (
    DEFAULT_APPLIED_REVIEWS_PATH,
    DEFAULT_CANDIDATES_PATH,
    DEFAULT_REVIEW_LOG_PATH,
    PENDING,
    VALID_STATUSES,
    OntologyCandidate,
    OntologyReviewStore,
)


CSS = """
:root {
  color-scheme: light;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f7f7f5;
  color: #1f2933;
}
body {
  margin: 0;
}
main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
h1 {
  font-size: 22px;
  margin: 0 0 6px;
}
.muted {
  color: #667085;
  font-size: 13px;
}
.layout {
  display: grid;
  grid-template-columns: minmax(260px, 360px) minmax(0, 1fr);
  gap: 16px;
}
.panel {
  background: #ffffff;
  border: 1px solid #d9dee7;
  border-radius: 8px;
  overflow: hidden;
}
.list {
  max-height: calc(100vh - 145px);
  overflow: auto;
}
.candidate {
  display: block;
  padding: 12px 14px;
  border-bottom: 1px solid #eef1f5;
  color: inherit;
  text-decoration: none;
}
.candidate:hover, .candidate.active {
  background: #eef6ff;
}
.candidate strong {
  display: block;
  font-size: 14px;
}
.badge {
  display: inline-block;
  margin-top: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef1f5;
  color: #344054;
  font-size: 12px;
}
.detail {
  padding: 18px;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}
form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  border-top: 1px solid #eef1f5;
  padding: 14px 18px;
}
button {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 14px;
  cursor: pointer;
}
button.approve {
  background: #0f766e;
  color: #ffffff;
  border-color: #0f766e;
}
button.hold {
  background: #f59e0b;
  color: #111827;
  border-color: #f59e0b;
}
button.reject {
  background: #b91c1c;
  color: #ffffff;
  border-color: #b91c1c;
}
textarea {
  flex: 1 1 100%;
  min-height: 58px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 8px;
  font: inherit;
}
.hold-reasons {
  flex: 1 1 100%;
  border: 1px solid #d9dee7;
  border-radius: 6px;
  padding: 10px 12px;
}
.hold-reasons legend {
  padding: 0 4px;
  font-weight: 600;
  font-size: 13px;
}
.hold-reasons label {
  display: block;
  margin: 7px 0;
  font-size: 13px;
  line-height: 1.35;
}
.hold-reasons input {
  margin-right: 6px;
}
.hold-reasons .muted {
  display: block;
  margin-left: 22px;
}
.message {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #ecfdf3;
  border: 1px solid #b7e4c7;
  border-radius: 6px;
}
@media (max-width: 850px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .list {
    max-height: 280px;
  }
}
"""


def _html_page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
""".encode("utf-8")


def _candidate_summary(candidate: OntologyCandidate) -> str:
    aliases = ", ".join(candidate.candidate_aliases[:2])
    if len(candidate.candidate_aliases) > 2:
        aliases = f"{aliases} 외 {len(candidate.candidate_aliases) - 2}개"
    return aliases or candidate.concept_id


def _hold_reason_options() -> str:
    items = []
    for reason in HOLD_REASONS:
        items.append(
            "<label>"
            f'<input type="checkbox" name="hold_reason_codes" value="{html.escape(reason.code)}">'
            f"{html.escape(reason.label)}"
            f'<span class="muted">{html.escape(reason.description)}</span>'
            "</label>"
        )
    return "\n".join(items)


class OntologyReviewHandler(BaseHTTPRequestHandler):
    server: "OntologyReviewServer"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send_html(self, body: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = _html_page("온톨로지 후보 승인", body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/":
            self._send_html("<main><h1>Not found</h1></main>", status=HTTPStatus.NOT_FOUND)
            return
        params = urllib.parse.parse_qs(parsed.query)
        selected_id = (params.get("id") or [""])[0]
        message = (params.get("message") or [""])[0]
        status_filter = (params.get("status") or [self.server.status_filter])[0]
        candidates = self.server.store.load_candidates()
        filtered = [
            candidate
            for candidate in candidates
            if status_filter == "all" or candidate.status == status_filter
        ]
        if not selected_id and filtered:
            selected_id = filtered[0].candidate_id
        selected = next((candidate for candidate in candidates if candidate.candidate_id == selected_id), None)

        status_options = ["pending", "approved", "held", "rejected", "applied", "all"]
        status_links = " ".join(
            f'<a class="badge" href="/?status={html.escape(status)}">{html.escape(status)}</a>'
            for status in status_options
        )
        items = []
        for candidate in filtered:
            active = " active" if candidate.candidate_id == selected_id else ""
            href = f"/?status={urllib.parse.quote(status_filter)}&id={urllib.parse.quote(candidate.candidate_id)}"
            items.append(
                f'<a class="candidate{active}" href="{href}">'
                f"<strong>{html.escape(candidate.canonical_name)}</strong>"
                f'<span class="muted">{html.escape(candidate.concept_id)}</span><br>'
                f'<span class="badge">{html.escape(candidate.status)}</span> '
                f'<span class="muted">{html.escape(_candidate_summary(candidate))}</span>'
                "</a>"
            )

        detail = "후보를 선택하세요."
        form = ""
        if selected is not None:
            detail = format_candidate_for_practitioner(
                selected,
                all_candidates=candidates,
                wrap_width=92,
            )
            if selected.status == PENDING:
                form = f"""
<form method="post" action="/decide">
  <input type="hidden" name="candidate_id" value="{html.escape(selected.candidate_id)}">
  <input type="hidden" name="status" value="{html.escape(status_filter)}">
  <textarea name="reason" placeholder="판단 사유를 남기려면 입력하세요."></textarea>
  <fieldset class="hold-reasons">
    <legend>보류 사유 분류</legend>
    <div class="muted">보류를 선택할 때 해당하는 사유를 하나 이상 고르세요. 다음 후보 생성/검토에서 alias 제외, 근거 재탐색, target concept 재검토 힌트로 사용됩니다.</div>
    {_hold_reason_options()}
  </fieldset>
  <button class="approve" type="submit" name="decision" value="approve">승인</button>
  <button class="hold" type="submit" name="decision" value="hold">보류</button>
  <button class="reject" type="submit" name="decision" value="reject">거절</button>
</form>
"""

        message_html = f'<div class="message">{html.escape(message)}</div>' if message else ""
        body = f"""
<main>
  <div class="topbar">
    <div>
      <h1>온톨로지 후보 승인</h1>
      <div class="muted">로컬 review JSONL 파일을 사용합니다. 운영 반영은 별도 apply/rebuild 명령으로 수행하세요.</div>
    </div>
    <div>{status_links}</div>
  </div>
  {message_html}
  <section class="layout">
    <aside class="panel list">{''.join(items) or '<div class="candidate">표시할 후보가 없습니다.</div>'}</aside>
    <article class="panel">
      <div class="detail"><pre>{html.escape(detail)}</pre></div>
      {form}
    </article>
  </section>
</main>
"""
        self._send_html(body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/decide":
            self._send_html("<main><h1>Not found</h1></main>", status=HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or "0")
        payload = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(payload)
        candidate_id = (form.get("candidate_id") or [""])[0]
        decision = (form.get("decision") or [""])[0]
        reason = (form.get("reason") or [""])[0]
        hold_reason_codes = normalize_hold_reason_codes(form.get("hold_reason_codes") or [])
        status_filter = (form.get("status") or [self.server.status_filter])[0]
        try:
            self.server.store.decide(
                candidate_id,
                decision,
                reviewer=self.server.reviewer,
                reviewer_type="practitioner_local_ui",
                reason=reason,
                hold_reason_codes=hold_reason_codes,
            )
            message = f"{candidate_id} 후보를 {decision} 처리했습니다."
        except Exception as exc:  # pragma: no cover - handler safety path.
            message = f"처리 실패: {exc}"
        self._redirect(f"/?status={urllib.parse.quote(status_filter)}&message={urllib.parse.quote(message)}")


class OntologyReviewServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        store: OntologyReviewStore,
        reviewer: str,
        status_filter: str,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.store = store
        self.reviewer = reviewer
        self.status_filter = status_filter


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local browser UI for ontology candidate review.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reviewer", default="local-practitioner")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES | {"all"}), default=PENDING)
    parser.add_argument("--candidates-path", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--review-log-path", type=Path, default=DEFAULT_REVIEW_LOG_PATH)
    parser.add_argument("--applied-reviews-path", type=Path, default=DEFAULT_APPLIED_REVIEWS_PATH)
    parser.add_argument("--no-open", action="store_true", help="Do not open the default browser automatically.")
    args = parser.parse_args()

    store = OntologyReviewStore(
        candidates_path=args.candidates_path,
        review_log_path=args.review_log_path,
        applied_reviews_path=args.applied_reviews_path,
    )
    server = OntologyReviewServer(
        (args.host, args.port),
        OntologyReviewHandler,
        store=store,
        reviewer=args.reviewer,
        status_filter=args.status,
    )
    url = f"http://{args.host}:{args.port}/?status={urllib.parse.quote(args.status)}"
    print(json.dumps({"url": url, "candidates_path": str(args.candidates_path)}, ensure_ascii=False, indent=2))
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
