"""Seed Langfuse with the canonical OCR prompts.

Run once per Langfuse project (or whenever you want to push a code-side
prompt change up to the prompt editor):

    docker compose exec ocr python -m scripts.seed_langfuse_prompts

The script uploads each prompt under its canonical name with the
`production` label so `langfuse_client.get_prompt(name)` resolves it
without any extra config. After the initial seed, edit prompts in the
Langfuse UI; code-side fallbacks stay only as a safety net for
unconfigured deploys.

Idempotent: re-running creates a new version of each prompt, so it's
safe to invoke from CI as a one-shot deployment step.
"""

from __future__ import annotations

import logging
import os
import sys

# Make sibling `app` package importable when run via `python -m scripts.…`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import langfuse_client  # noqa: E402
from app.services.ai_extractor import _FIELD_EXTRACTOR_SYSTEM_FALLBACK  # noqa: E402
from app.services.doc_classifier import _DOC_CLASSIFIER_SYSTEM_FALLBACK  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_langfuse_prompts")


PROMPTS = [
    (langfuse_client.PROMPT_NAME_FIELD_EXTRACTOR, _FIELD_EXTRACTOR_SYSTEM_FALLBACK),
    (langfuse_client.PROMPT_NAME_DOC_CLASSIFIER, _DOC_CLASSIFIER_SYSTEM_FALLBACK),
]


def main() -> int:
    client = langfuse_client.get_client()
    if client is None:
        log.error(
            "Langfuse not configured — set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
            "(and LANGFUSE_HOST for self-hosted)."
        )
        return 2

    for name, body in PROMPTS:
        try:
            client.create_prompt(
                name=name,
                prompt=body,
                labels=["production"],
                # Tag so the Langfuse UI groups DocFlow prompts.
                tags=["docflow", "ocr"],
            )
            log.info("seeded %s (%d chars)", name, len(body))
        except Exception as exc:  # noqa: BLE001
            log.exception("failed to seed %s: %s", name, exc)
            return 1

    client.flush()
    log.info("done — %d prompts pushed", len(PROMPTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
