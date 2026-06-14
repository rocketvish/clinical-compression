# Clinical Compression — Fact Extraction Pipeline

## Quick Start

### Prerequisites
```
cd clinical-compression
pip install -e ".[dev]"
```

### Pipeline Steps

#### 1. Prepare the case
Convert the PDF to plain text and save it in `pubmed/`:
```
pubmed/your-case-name.txt
```

#### 2. Generate extraction prompt
```
python -m src.extraction.build_prompt --input pubmed/your-case-name.txt --note-type case_report --date YYYY-MM-DD --output scratch/prompt.txt
```

#### 3. Extract facts
Open `scratch/prompt.txt`, copy everything, paste into a **new** claude.ai chat (Opus). Copy the JSON response, save to `scratch/raw_response.json`.

#### 4. Validate
```
python -m src.extraction.validate --input scratch/raw_response.json --output pubmed/your-case-name-facts.json
```

#### 5. Generate verification prompt
```
python -m src.extraction.build_verify_prompt --input pubmed/your-case-name.txt --facts pubmed/your-case-name-facts.json --output scratch/verify_prompt.txt
```

#### 6. Verify exhaustiveness
Paste `scratch/verify_prompt.txt` into a **new** claude.ai chat (Opus). Copy the JSON array response, save to `scratch/verify_response.json`.

If the model returns prose instead of JSON, reply: "Return only the JSON array, no explanation."

#### 7. Merge
```
python -m src.extraction.merge --existing pubmed/your-case-name-facts.json --new scratch/verify_response.json --output pubmed/your-case-name-facts-final.json
```

#### 8. Generate reconstruction for doctor review
```
python -c "import sys; sys.path.insert(0,'.'); from src.schema.fact_schema import FactFile; open('pubmed/your-case-name-reconstruction.txt','w').write(FactFile.from_json('pubmed/your-case-name-facts-final.json').reconstruct())"
```

#### 9. Doctor review
Send doctors:
- The original PDF
- `pubmed/your-case-name-reconstruction.txt`

Ask them:
1. What clinically relevant facts from the case are missing?
2. What's inaccurate, miscategorized, or misattributed?
3. What's over-extracted (clinically insignificant noise)?

Feed their answers back into prompt tuning (decomposition rules in `src/extraction/prompts.py`).

## File Structure

```
pubmed/                          — case texts, fact files, reconstructions
  your-case.txt                  — plain text of the clinical case
  your-case-facts-final.json     — validated, merged fact file
  your-case-reconstruction.txt   — readable reconstruction for doctors
scratch/                         — gitignored, temporary prompt/response files
  prompt.txt
  raw_response.json
  verify_prompt.txt
  verify_response.json
src/schema/fact_schema.py        — Pydantic schema (FactFile, Fact, enums)
src/extraction/
  prompts.py                     — system prompt, extraction/verification prompt builders
  validate.py                    — JSON validation against schema
  merge.py                       — merge verification pass into existing facts
  build_prompt.py                — CLI: generate extraction prompt
  build_verify_prompt.py         — CLI: generate verification prompt
```

## Running Tests
```
pytest tests/ -v
```

## Notes
- The `scratch/` directory is gitignored. Intermediate files go there.
- Validated fact files in `pubmed/` are committed to the repo.
- The extraction prompt evolves — tune decomposition rules in `prompts.py` based on doctor feedback.
- When scaling to ER-REASON (hundreds of cases), add an API runner that reuses the same prompts. The prompts are the investment; the delivery mechanism is swappable.
