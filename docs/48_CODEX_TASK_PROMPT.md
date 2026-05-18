# Codex Task Prompt — #48

> 이 파일을 Codex에 그대로 붙여 넣으세요.

---

You are a senior Python / Streamlit developer applying brand identity styling to an existing insurance document RAG chatbot UI. This task is UI-only — do not touch authentication, RAG, or retrieval logic.

Read `WORKFLOW.md`, `CLAUDE.md`, and `docs/48_CODEX_SPEC_SHINHANEZ_BRANDING.md` before writing any code.

## Role

Senior frontend developer (Streamlit). You handle UI styling, asset management, and CSS injection. Reviewer is Claude. Operator is the human user.

## Goal

Apply 신한EZ손해보험 (Shinhan EZ Non-life Insurance) branding to the Streamlit app:

1. **Research**: Visit the official website (https://www.shinhanezins.co.kr) and related pages to identify the exact brand colors, logo URL, and mascot images. Record findings in `docs/48_BRAND_RESEARCH.md`.

2. **Theme**: Add a `[theme]` section to `.streamlit/config.toml` using the confirmed primary color.

3. **Assets**: Download the official logo to `assets/logo.png`. Download mascot image to `assets/mascot.png` if available. If the official logo cannot be obtained, generate a text-based placeholder with PIL.

4. **Helper module**: Create `src/ui/brand.py` with `inject_css()`, `render_logo()`, `render_sidebar_logo()` functions per the spec.

5. **App integration**: Modify `src/ui/streamlit_app.py` to inject CSS, display the logo on the login screen (centered, above the login form), and display the sidebar logo at the top of the sidebar. Replace `st.title(...)` in the chatbot main view with a branded `st.markdown` header.

## Success Criteria

- `python -c "from src.ui.brand import inject_css, render_logo; print('OK')"` succeeds
- `pytest -q` passes with 0 failures (≥ 201 tests)
- `streamlit run src/ui/streamlit_app.py` launches without errors
- Login screen shows the 신한EZ logo above the login form
- Sidebar shows the logo at the top
- Chatbot header title uses the brand primary color
- No changes to authentication, RAG, or retrieval behavior

## Constraints

- Do **not** modify any file under `src/auth/`, `src/rag/`, `src/retrieval/`, `src/llm/`, `src/db/`
- Do **not** modify `scripts/` files
- Do **not** modify `src/ui/admin_page.py`, `src/ui/chat_store.py`, `src/ui/pdf_view.py`
- Load `.env` using `Path(__file__).resolve().parents[N] / ".env"` if needed — do **not** use `find_dotenv()`
- If a logo/image cannot be fetched from the web, generate a PIL placeholder — do not raise an unhandled error
- Logo and mascot images **must** be committed to `assets/`
- Do **not** commit JSON result files or HTML files

## Execution Order

1. **Research** — visit shinhanezins.co.kr and extract brand colors, logo URL. Write `docs/48_BRAND_RESEARCH.md`.
2. **Assets** — download/generate `assets/logo.png` and `assets/mascot.png`.
3. **config.toml** — add `[theme]` section.
4. **brand.py** — create helper module.
5. **streamlit_app.py** — integrate logo and CSS (login screen, sidebar, header).
6. **Validate** — run `pytest -q`, then `streamlit run src/ui/streamlit_app.py` and confirm visually.

## Output

Write `docs/48_SHINHANEZ_BRANDING_REPORT.md` containing:
1. Brand colors found (hex codes, source URLs)
2. Logo/mascot acquisition method and filenames
3. Changed files (one-line description per change)
4. `pytest -q` output
5. Visual confirmation notes (login screen, sidebar, header)
6. Remaining blockers ("None" if clean)

Then commit and push to `origin/master`.

## Stop Rules

- Any existing test fails → stop, report
- Any non-UI source file modification required → stop, report
- `streamlit run` raises an import or runtime error → stop, report stack trace
- Logo cannot be found anywhere online → generate PIL placeholder, note in report, continue
