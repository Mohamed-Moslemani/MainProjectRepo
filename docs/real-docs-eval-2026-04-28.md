# Real-document E2E — first run, 2026-04-28

Run config: `OCR_MOCK_MODE=false`, `FACE_MOCK_MODE=false`, real
Google Cloud Vision + AWS Rekognition. Provider cost ~$0.02 for
this run. Raw output: [`real_docs_2026-04-28.json`](./real_docs_2026-04-28.json).

## Aggregate

**21/31 ground-truth fields matched = 67%** across the 6 cases that
have transcribed expected values. The other 6 cases are
quality-only stress tests (deliberately bad images), where success
means the quality gate flags the right reasons — all 6 did.

| Case                              | Match  | Notes |
| --------------------------------- | ------ | ----- |
| haddad_sarah_biometric            | 7/7    | LR-prefix biometric LB passport — full MRZ (number, surname, given names, nationality, DOB, expiry, sex) |
| service_doe_specimen              | 7/7    | LB service passport specimen — MRZ checksums passed |
| ashraf_mohammad_watermarked       | 3/3    | extracted despite glare warning |
| utopia_icao_specimen              | 4/5    | ICAO 9303 baseline; missed 1 |
| diplomatic_doe_specimen           | 0/7    | MRZ not extracted — see below |
| palestinian_zeina_barakeh         | 0/2    | Palestinian passport (RPL) — see below |
| amhaz_imad_biometric              | quality-only | low res 460×277 → retake correctly flagged |
| sakr_taghrid_photocopy            | quality-only | blur score 31.4 < 100 → retake correctly flagged |
| bahmad_nasser_partial             | quality-only | 480×270 → retake correctly flagged |
| pre2003_non_biometric             | quality-only | glare + low res + 45° skew → retake correctly flagged |
| redacted_elbraidy                 | quality-only | glare + 45° skew → retake correctly flagged |
| psdlife_template                  | quality-only | 225×225 → retake correctly flagged |

## What works

- **MRZ parsing on real Lebanese biometric passports.** All seven
  fields (passport number, surname, given names, nationality,
  DOB, expiry, sex) extracted from `haddad_sarah` and `service_doe`,
  including the LR-prefix format that's specific to LB biometrics.
- **Quality gate correctly flags every deliberately-bad image**
  with specific reasons (resolution, blur, glare, skew). No false
  passes — this is what `need_info` routing depends on.
- **Field extraction tolerates moderate glare** —
  `ashraf_mohammad` matched all expected fields despite a 48%
  overexposed warning.
- **Real-provider mode boots cleanly.** Both `/health/ready`
  endpoints report `mode: live` with valid GCV + AWS credentials.

## What's broken — and what to do

### 1. `diplomatic_doe_specimen`: MRZ format `999D16<<9LBN...` not extracted

The field-extractor regex assumes `[A-Z]{1,2}[0-9]{6,7}` for the
passport-number slot. LB diplomatic passports use the literal
`999D16` followed by `<<` filler, which doesn't match. Service
passports (`999SV16`) work because the SV happens to fit the
two-letter prefix variant.

**Fix:** widen the MRZ passport-number pattern in
[services/ocr/app/services/field_extractor.py] to accept a
`[A-Z0-9]{6,9}` token for diplomatic/service category passports.
ETA: 30 min including a unit test.

### 2. `palestinian_zeina_barakeh`: RPL nationality, no MRZ extracted

The MRZ exists (visible to the eye) but Vision didn't return text
in the expected position, or the extractor's nationality filter
rejected it. Need to look at the raw `text_annotations` payload
for this image.

**Fix:** check raw OCR output. If text was returned, the issue is
in our parser — accept non-LBN nationalities through the same
path, only flag them at the policy/risk layer (which is where
"foreign passport submitted to a Lebanese ID flow" should be
caught, not the OCR layer). ETA: 1 hour, depends on what the raw
text looks like.

### 3. `utopia_icao_specimen`: 4/5 (sex field missed)

The MRZ printed sex character is in the expected position but the
specimen's image quality / contrast may have OCR'd it as `<`. Not
a real-world concern for LB passports; documenting only.

## What this means for the demo

A demo on `haddad_sarah` (or `service_doe`) gives you a clean
end-to-end real-document run: the citizen uploads, OCR extracts
all 7 MRZ fields with checksums passing, the quality gate flags
the resolution warning but the field accuracy is 100%, the case
proceeds. **That's the demo path.**

The diplomatic + Palestinian cases are interesting failure modes
to discuss but should not block submission. Document them as
known limits.

## Reproducibility

```bash
# Switch to real-provider mode (costs ~$0.02 per full run)
sed -i 's/OCR_MOCK_MODE=true/OCR_MOCK_MODE=false/' .env.dev
sed -i 's/FACE_MOCK_MODE=true/FACE_MOCK_MODE=false/' .env.dev
docker compose --env-file .env.dev up -d --force-recreate ocr face

# Run
python scripts/test_real_docs.py evaluation/real_samples/manifest.yaml \
  --json-out evaluation/results/real_docs_$(date +%Y-%m-%d).json

# Switch back to mock so everyday dev is free
sed -i 's/OCR_MOCK_MODE=false/OCR_MOCK_MODE=true/' .env.dev
sed -i 's/FACE_MOCK_MODE=false/FACE_MOCK_MODE=true/' .env.dev
docker compose --env-file .env.dev up -d --force-recreate ocr face
```
