# Real-document test harness

Measure how well OCR + face services handle actual Lebanese documents,
not just the synthetic fixtures used by the E2E suite.

## Setup

1. Put document images under `evaluation/real_samples/<case_id>/`.
   Use public sample passports/IDs or redacted personal docs — do
   **not** commit real PII.
2. Copy the template and fill in ground-truth fields:
   ```bash
   cp evaluation/real_samples/manifest.example.yaml evaluation/real_samples/manifest.yaml
   ```
3. Bring up the stack (OCR + Face containers must be running):
   ```bash
   docker compose up -d gateway ocr face
   ```
4. Install harness deps if missing:
   ```bash
   pip install httpx pyyaml
   ```

## Run

```bash
python scripts/test_real_docs.py evaluation/real_samples/manifest.yaml
```

Optional JSON summary:
```bash
python scripts/test_real_docs.py evaluation/real_samples/manifest.yaml \
  --json-out evaluation/results/real_docs.json
```

## What it reports

Per document:
- Overall OCR confidence + quality flags (blur / glare / skew)
- Per-field match vs expected (✓/✗) with confidence
- MRZ validity for passports

Per case:
- Face similarity + liveness + decision

Aggregate:
- Overall field accuracy across every case

## Interpreting results

- **<70% field accuracy** → regex patterns in
  [services/ocr/app/services/field_extractor.py](../../services/ocr/app/services/field_extractor.py)
  likely need tuning for real LB ID/passport layouts.
- **MRZ invalid on real passports** → check image quality; the parser
  is strict about ICAO 9303 TD3 format.
- **Face similarity < 0.7 on the same person** → `FACE_MOCK_MODE`
  might be on, or the reference photo quality is too low.

## Privacy

`evaluation/real_samples/**` is gitignored by the `uploads/` and broad
patterns above. Double-check before committing — redact faces + numbers
on any sample you plan to push publicly.
