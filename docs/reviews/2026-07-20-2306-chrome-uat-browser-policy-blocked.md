# Chrome UAT browser-policy blocker

## Status

- Protected DGX promotion completed at `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7`.
- API health was normal after API-only restart.
- The existing SGLang process remained active.
- The Chrome tab and authenticated application URL were still present.

## Blocker

Before reading or interacting with the application DOM, the Chrome automation layer rejected access to `http://localhost:18080` because that local origin is currently recorded as user-blocked. The rejection occurred before any UAT question, click, form input, or source interaction was executed.

No alternate browser, raw browser protocol, direct DOM workaround, or API-only substitute was used because those would not constitute the requested Chrome end-user UAT and would bypass the browser safety decision.

## UAT disposition

The following cases remain `미실행` and must not be scored as pass or fail:

- 4th-generation MRI/MRA annual limit final bubble (`300만원` expected)
- 5th-generation MRI/MRA annual limit final bubble, two independent runs (`200만원` expected)
- 4th/5th-generation comparison (`300만원` / `200만원` expected)
- coverage and payment-judgment boundary questions
- internal marker non-exposure in the final bubble
- source hover preview
- source click opening the authenticated original PDF at the cited page

## Resume condition

Resume only after the user explicitly permits Chrome automation for `http://localhost:18080`. Keep the existing authenticated Chrome tab if possible and run the prepared cases from a new chat. Do not change GraphDB, ontology, active calculation rules, raw documents, or operational data merely to unblock browser access.
