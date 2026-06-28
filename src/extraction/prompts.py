"""Prompt builders for local (claude.ai) clinical fact extraction.

These functions produce prompt *text* only — no API calls. The user pastes the
output into claude.ai and saves the JSON response for local validation/merge.
When we scale to ER-REASON, an API runner can reuse these same builders.
"""

from __future__ import annotations

from src.schema.fact_schema import (
    FactCategory,
    FactSource,
    NoteType,
    SUBCATEGORY_MAP,
)

# ---------------------------------------------------------------------------
# Static prompt fragments
# ---------------------------------------------------------------------------

_ROLE = (
    "You are a clinical fact extractor. Given a medical document, you extract "
    "every clinically relevant patient-specific fact into a structured JSON "
    "format. You are exhaustive, precise, and follow strict decomposition rules."
)

# Verbatim per spec — these 9 rules constrain decomposition behavior.
_DECOMPOSITION_RULES = """DECOMPOSITION RULES:

1. ONE ENTITY PER FACT. "Patient takes tylenol 200mg and metformin 10mg" becomes TWO facts, each with a single entity and its associated values. Never put multiple unrelated entities in one fact entry.

2. ATOMIC FACTS. Compound clinical statements are decomposed into separate facts by category. "Metformin increased from 250mg to 500mg on 2024-01-10 due to inadequate glycemic control" becomes:
   - categorical/drug_name: "Patient takes metformin"
   - quantitative/medication_dosage: "Metformin 500mg" (current dose)
   - temporal/dosage_change: "Metformin increased from 250mg to 500mg on 2024-01-10"
   - clinical_reasoning/explanatory_link: "Metformin increased due to inadequate glycemic control"
   All share the same group_id.

3. GROUP_ID links facts decomposed from the same clinical statement. Each fact in a group is independently meaningful. Use format "g001", "g002", etc. Facts that stand alone have group_id: null.

4. NEGATION. Any negated clinical fact (denies, no history of, ruled out, absent, etc.) MUST have negated: true. The content field MUST include the negation word. "Denies chest pain" → content: "Patient denies chest pain", negated: true. The entities field contains the concept being negated: ["chest pain"]. Medical-convention negation terms also count as negation: afebrile (no fever), asymptomatic (no symptoms), atraumatic (no trauma), unremarkable (no abnormal findings), nontender, noncontributory, within normal limits. These must have negated: true and the content field should use explicit negation language (e.g., "No abnormal findings on physical exam" rather than just "unremarkable exam").

5. VERBATIM SPAN. The span field captures the original text from the document, preserving abbreviations and formatting. If the fact comes from multiple non-contiguous spans, capture the most informative one.

6. SOURCE ATTRIBUTION. Set the source field based on who asserted the fact:
   - patient_reported: patient's own statements
   - physician_assessed: physician's clinical judgment or documentation
   - outside_records: from external records or prior documentation
   - nursing_note: nursing documentation
   - family_reported: family member statements
   - unknown: cannot determine source

7. MULTIPLE VALUES on one entity follow chronological order for changes (old first, new second) and co-equal listing for current state. Content must state direction explicitly for changes.

8. TAGS for cross-cutting concerns use format "category:detail" (e.g. "temporal:started_2024-03-15"). Use tags when a fact has a secondary category relationship but its primary category is something else.

9. EXTRACT PATIENT-SPECIFIC FACTS ONLY. Do not extract general medical knowledge, literature findings, study results, or guideline recommendations. Extract only facts about the specific patient in the case.

10. PRESERVE DISEASE QUALIFIERS. Stage, grade, severity, functional status, and subtype modifiers must be included in the content field. "Chronic kidney disease stage 3" not "chronic kidney disease." "Heart failure with preserved ejection fraction" not "heart failure." These qualifiers change clinical management.

11. TREATMENT REGIMENS ARE NOT DRUGS. Do not extract combination therapy descriptions ("triple antithrombotic therapy", "dual antiplatelet therapy") as drug_name facts. The individual drugs in the regimen should each have their own drug_name entry. If the regimen concept is clinically relevant, categorize it as clinical_reasoning/explanatory_link.

12. DEDUPLICATE FACTS. If the same clinical fact appears in multiple sections of the document (e.g., mentioned in the case presentation and again in the discussion), extract it ONCE. Use the most complete or specific version. Do not create separate fact entries for each mention of the same fact.

13. DIAGNOSIS HIERARCHY. When a condition has an etiology, pathology, and functional consequence (e.g., alcoholic liver disease → cirrhosis → liver failure), extract the most clinically specific composite diagnosis rather than separate entries for each level. Use the content field for the composite ('end-stage alcoholic cirrhosis with liver failure') and entities for the key terms. Extract separate facts only when different levels are clinically independent or diagnosed at different times.

14. PROGRESSIVE CONDITIONS. When the same condition appears at different severity levels across the document timeline (e.g., 'heart failure' early, 'decompensated heart failure' later), extract the progression as a single temporal fact showing the trajectory, not as two separate categorical diagnoses.

15. QUALITATIVE VS QUANTITATIVE LAB RESULTS. Lab results with numeric values (HbA1c 7.2%, INR 4.9, WBC 11,600) are quantitative/lab_value. Lab results that are categorical or binary (blood culture positive for MSSA, eosinophilia without a count, urine culture negative) are categorical/previous_diagnosis if they establish a diagnosis, or categorical/negated_fact if they confirm absence. Do not put non-numeric results in quantitative/lab_value.

16. LAB ISOLATE IDENTIFIERS ARE NOT DIAGNOSES. Microbiology isolate labels (SA1, SA2, SA3, 'isolate 1', strain designations, ATCC reference numbers) are laboratory identifiers, not patient diagnoses or clinical entities. Do not extract them as standalone categorical facts. When a lab result references an isolate, the entity should be the organism (e.g., 'methicillin-susceptible Staphylococcus aureus') not the isolate label (e.g., 'SA1')."""

_OUTPUT_FORMAT = (
    "Return ONLY valid JSON matching the FactFile structure — a single JSON "
    'object with "metadata" and "facts" keys.\n\n'
    "CRITICAL: Your entire response must be valid JSON and nothing else. Start "
    "your response with { and end it with }. No text before or after the "
    "object. No explanation, no commentary, no markdown fencing."
)

# The worked example is embedded inline rather than read from tests/fixtures so
# that `src` never imports from `tests`. A drift-guard test asserts this copy
# parses to a FactFile equal to tests/fixtures/example_extraction.json — if the
# fixture ever changes, update this constant to match.
WORKED_EXAMPLE_JSON = """{
  "metadata": {
    "document_id": "example-001",
    "note_type": "progress_note",
    "date": "2024-03-15",
    "author_role": "attending physician",
    "sections_present": ["HPI", "Assessment/Plan"],
    "source_dataset": "synthetic"
  },
  "facts": [
    {
      "id": "f001",
      "category": "categorical",
      "subcategory": "patient_identifier",
      "content": "Patient is a 67-year-old male",
      "span": "67-year-old male",
      "entities": ["patient"],
      "values": ["67"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": null
    },
    {
      "id": "f002",
      "category": "categorical",
      "subcategory": "previous_diagnosis",
      "content": "Patient has Type 2 diabetes",
      "span": "history of Type 2 diabetes (diagnosed 2019)",
      "entities": ["Type 2 diabetes"],
      "values": [],
      "tags": ["temporal:diagnosed_2019"],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g001"
    },
    {
      "id": "f003",
      "category": "temporal",
      "subcategory": "time_since_event",
      "content": "Type 2 diabetes diagnosed in 2019",
      "span": "diagnosed 2019",
      "entities": ["Type 2 diabetes"],
      "values": ["2019"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g001"
    },
    {
      "id": "f004",
      "category": "categorical",
      "subcategory": "drug_name",
      "content": "Patient is currently on metformin",
      "span": "currently on metformin 500mg BID",
      "entities": ["metformin"],
      "values": [],
      "tags": ["quantitative:500mg_BID"],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f005",
      "category": "quantitative",
      "subcategory": "medication_dosage",
      "content": "Metformin 500mg twice daily",
      "span": "metformin 500mg BID",
      "entities": ["metformin"],
      "values": ["500mg", "BID"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f006",
      "category": "categorical",
      "subcategory": "negated_fact",
      "content": "Patient denies chest pain",
      "span": "Denies chest pain",
      "entities": ["chest pain"],
      "values": [],
      "tags": [],
      "source": "patient_reported",
      "negated": true,
      "group_id": null
    },
    {
      "id": "f007",
      "category": "quantitative",
      "subcategory": "lab_value",
      "content": "HbA1c is 7.2%",
      "span": "HbA1c 7.2% on 2024-03-15",
      "entities": ["HbA1c"],
      "values": ["7.2%"],
      "tags": ["temporal:2024-03-15"],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g003"
    },
    {
      "id": "f008",
      "category": "temporal",
      "subcategory": "lab_trajectory",
      "content": "HbA1c increased from 6.8% to 7.2% between September 2023 and March 2024",
      "span": "HbA1c 7.2% on 2024-03-15, up from 6.8% in 2023-09",
      "entities": ["HbA1c"],
      "values": ["6.8%", "7.2%"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g003"
    },
    {
      "id": "f009",
      "category": "categorical",
      "subcategory": "allergy",
      "content": "Patient is allergic to penicillin with anaphylaxis reaction",
      "span": "Allergic to penicillin (anaphylaxis)",
      "entities": ["penicillin"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": null
    },
    {
      "id": "f010",
      "category": "temporal",
      "subcategory": "dosage_change",
      "content": "Metformin increased from 250mg to 500mg on 2024-01-10",
      "span": "Metformin was increased from 250mg to 500mg on 2024-01-10",
      "entities": ["metformin"],
      "values": ["250mg", "500mg", "2024-01-10"],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f011",
      "category": "clinical_reasoning",
      "subcategory": "explanatory_link",
      "content": "Metformin was increased due to inadequate glycemic control",
      "span": "due to inadequate glycemic control",
      "entities": ["metformin", "glycemic control"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g002"
    },
    {
      "id": "f012",
      "category": "clinical_reasoning",
      "subcategory": "uncertainty_marker",
      "content": "Concerning for early diabetic nephropathy",
      "span": "Concerning for early diabetic nephropathy",
      "entities": ["diabetic nephropathy"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g004"
    },
    {
      "id": "f013",
      "category": "clinical_reasoning",
      "subcategory": "pending_planned_task",
      "content": "Plan to order urine albumin test",
      "span": "plan to order urine albumin",
      "entities": ["urine albumin"],
      "values": [],
      "tags": [],
      "source": "physician_assessed",
      "negated": false,
      "group_id": "g004"
    }
  ]
}"""


# ---------------------------------------------------------------------------
# Dynamically generated fragments (kept in sync with the schema)
# ---------------------------------------------------------------------------


def _category_label(category: FactCategory) -> str:
    return category.value.replace("_", " ").title()


def _taxonomy_block() -> str:
    """Category -> subcategory listing, generated from SUBCATEGORY_MAP so it
    can never drift from the schema."""
    lines = []
    for category, subs in SUBCATEGORY_MAP.items():
        lines.append(f"{_category_label(category)}: {', '.join(subs)}")
    return "\n".join(lines)


def _source_block() -> str:
    return ", ".join(s.value for s in FactSource)


def _factfile_reference() -> str:
    note_types = ", ".join(n.value for n in NoteType)
    categories = ", ".join(c.value for c in FactCategory)
    sources = _source_block()
    return f"""FactFile structure:
{{
  "metadata": {{
    "document_id": str,
    "note_type": one of [{note_types}],
    "date": str | null,            // ISO YYYY-MM-DD
    "author_role": str | null,
    "sections_present": [str, ...],
    "source_dataset": str | null
  }},
  "facts": [
    {{
      "id": str,                    // "f001", unique within the file
      "category": one of [{categories}],
      "subcategory": str,           // a valid subcategory for the category
      "content": str,               // normalized, human-readable statement
      "span": str | null,           // verbatim source text
      "entities": [str, ...],       // at least one clinical entity
      "values": [str, ...],         // quantitative values with units; may be empty
      "tags": [str, ...],           // cross-cutting "category:detail"
      "source": one of [{sources}],
      "negated": bool,
      "group_id": str | null        // links decomposed facts, e.g. "g001"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_system_prompt() -> str:
    """The full, static extraction system prompt."""
    return f"""{_ROLE}

TAXONOMY (category: subcategories):
{_taxonomy_block()}

SOURCE ATTRIBUTION VALUES:
{_source_block()}

{_DECOMPOSITION_RULES}

WORKED EXAMPLE

Given this clinical text:
"Patient is a 67-year-old male with history of Type 2 diabetes (diagnosed 2019), currently on metformin 500mg BID. Denies chest pain. HbA1c 7.2% on 2024-03-15, up from 6.8% in 2023-09. Allergic to penicillin (anaphylaxis). Metformin was increased from 250mg to 500mg on 2024-01-10 due to inadequate glycemic control. Concerning for early diabetic nephropathy — plan to order urine albumin."

Produce this extraction:
{WORKED_EXAMPLE_JSON}

OUTPUT FORMAT:
{_OUTPUT_FORMAT}

{_factfile_reference()}"""


def build_extraction_prompt(
    document_text: str,
    document_id: str,
    note_type: str = "other",
    date: str | None = None,
    author_role: str | None = None,
    source_dataset: str = "manual",
) -> str:
    """The combined system+user prompt to paste into claude.ai for extraction."""
    return f"""<SYSTEM>
{build_system_prompt()}
</SYSTEM>

<USER>
Extract all patient-specific clinical facts from this document.

Document metadata:
- document_id: {document_id}
- note_type: {note_type}
- date: {date or "unknown"}
- author_role: {author_role or "unknown"}
- source_dataset: {source_dataset}

Document text:
---
{document_text}
---

Return the complete FactFile JSON with metadata and all extracted facts.
</USER>"""


def build_verification_prompt(document_text: str, existing_facts_json: str) -> str:
    """The verification prompt to paste into claude.ai for a second pass."""
    return f"""<SYSTEM>
{build_system_prompt()}
</SYSTEM>

<USER>
Review this clinical document against the facts already extracted. Identify any clinically relevant patient-specific facts that are MISSING from the extraction.

Focus especially on:
- Negated facts (things the patient denies or does not have)
- Temporal relationships (when things started, stopped, changed)
- Clinical reasoning (why decisions were made, what was considered and rejected)
- Conditional instructions (if X then Y)
- Source attributions that may be wrong
- Quantitative values (lab numbers, vitals, dosages) that were missed
- Drug interactions or risk factors mentioned specifically about this patient

Document text:
---
{document_text}
---

Already extracted facts:
---
{existing_facts_json}
---

Return ONLY a JSON array of additional Fact objects that are missing. Use fact IDs continuing from the highest existing ID. Use group_ids continuing from the highest existing group. If no facts are missing, return an empty array: []

CRITICAL: Your entire response must be valid JSON and nothing else. Start your response with [ and end it with ]. No text before or after the array. No explanation, no commentary, no markdown fencing.
</USER>"""
