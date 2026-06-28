"""Pydantic schema for structured clinical fact extraction.

This schema is the ground-truth representation used to evaluate context
compression techniques on clinical text. A :class:`FactFile` holds document
metadata plus a list of atomic :class:`Fact` entries; compound clinical
statements are decomposed into multiple facts linked by ``group_id``.

See ``fact-taxonomy.md`` for the conceptual taxonomy this operationalizes.
"""

from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NoteType(StrEnum):
    DISCHARGE_SUMMARY = "discharge_summary"
    PROGRESS_NOTE = "progress_note"
    HISTORY_AND_PHYSICAL = "history_and_physical"
    CONSULT = "consult"
    IMAGING_REPORT = "imaging_report"
    PROCEDURE_NOTE = "procedure_note"
    NURSING_NOTE = "nursing_note"
    ER_PROVIDER_NOTE = "er_provider_note"
    ECHOCARDIOGRAPHY_REPORT = "echocardiography_report"
    CASE_REPORT = "case_report"
    OTHER = "other"


class FactCategory(StrEnum):
    CATEGORICAL = "categorical"
    TEMPORAL = "temporal"
    QUANTITATIVE = "quantitative"
    CLINICAL_REASONING = "clinical_reasoning"


class FactSource(StrEnum):
    PATIENT_REPORTED = "patient_reported"
    PHYSICIAN_ASSESSED = "physician_assessed"
    OUTSIDE_RECORDS = "outside_records"
    NURSING_NOTE = "nursing_note"
    FAMILY_REPORTED = "family_reported"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Subcategory map — single source of truth for the subcategory validator and
# a useful downstream reference.
# ---------------------------------------------------------------------------

SUBCATEGORY_MAP: dict[FactCategory, list[str]] = {
    FactCategory.CATEGORICAL: [
        "previous_diagnosis",
        "reported_symptom",
        "patient_identifier",
        "family_history",
        "behavior",
        "code_status",
        "negated_fact",
        "allergy",
        "infection_precaution",
        "fall_risk",
        "drug_name",
        "device_type",
    ],
    FactCategory.TEMPORAL: [
        "medication_timing",
        "event_sequence",
        "lab_trajectory",
        "dosage_change",
        "time_since_event",
    ],
    FactCategory.QUANTITATIVE: [
        "lab_value",
        "vital_sign",
        "medication_dosage",
    ],
    FactCategory.CLINICAL_REASONING: [
        "considered_rejected_diagnosis",
        "conditional_fact",
        "explanatory_link",
        "uncertainty_marker",
        "pending_planned_task",
    ],
}


# ---------------------------------------------------------------------------
# Negation cues (validation rule 2)
# ---------------------------------------------------------------------------

# A negated fact's `content` must contain explicit negation language so that
# polarity inversions ("denies chest pain" -> "chest pain") are caught at
# authoring time rather than slipping through silently. This list is
# deliberately generous and meant to grow: add a cue here whenever a
# legitimate negation phrasing produces a false negative.
NEGATION_CUES: tuple[str, ...] = (
    "denies",
    "denied",
    "deny",
    "no",
    "not",
    "never",
    "negative",
    "without",
    "absent",
    "none",
    "non",
    "no history",
    "no evidence",
    "no signs",
    "ruled out",
    "free of",
    # Medical-convention negation: terms that express absence without an
    # English negation word ("afebrile" == "no fever", "unremarkable" ==
    # "no abnormal findings"). See NEGATION rule in extraction/prompts.py.
    "unremarkable",
    "afebrile",
    "asymptomatic",
    "atraumatic",
    "anicteric",
    "nontender",
    "noncontributory",
    "benign",
    "normal",
    "clear",
    "stable",
    "intact",
    "within normal limits",
)


def _build_negation_re(cues: tuple[str, ...]) -> re.Pattern[str]:
    parts: list[str] = []
    for cue in cues:
        if cue == "non":
            # Prefix cue: matches "non", "non-reactive", "nonreactive".
            parts.append(r"\bnon")
        else:
            parts.append(r"\b" + re.escape(cue) + r"\b")
    return re.compile("|".join(parts), re.IGNORECASE)


_NEGATION_RE = _build_negation_re(NEGATION_CUES)

# A tag is "category:detail" where category is one of the FactCategory values.
_TAG_RE = re.compile(
    r"^(?:" + "|".join(c.value for c in FactCategory) + r"):.+$"
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DocumentMetadata(BaseModel):
    """Header information about the source document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    note_type: NoteType
    date: str | None = None
    author_role: str | None = None
    sections_present: list[str] = Field(default_factory=list)
    source_dataset: str | None = None


class Fact(BaseModel):
    """A single atomic clinical fact.

    `negated` and the `negated_fact` subcategory are intentionally orthogonal:
    a negated previous diagnosis ("no history of seizures") is
    ``subcategory="previous_diagnosis", negated=True`` — not ``negated_fact``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    category: FactCategory
    subcategory: str
    content: str
    span: str | None = None
    entities: list[str] = Field(min_length=1)
    values: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: FactSource
    negated: bool = False
    group_id: str | None = None

    @field_validator("tags")
    @classmethod
    def _check_tag_format(cls, tags: list[str]) -> list[str]:
        bad = [t for t in tags if not _TAG_RE.match(t)]
        if bad:
            valid = ", ".join(c.value for c in FactCategory)
            raise ValueError(
                f"Malformed tag(s) {bad}: each tag must be 'category:detail' "
                f"where category is one of [{valid}]."
            )
        return tags

    @model_validator(mode="after")
    def _check_subcategory(self) -> "Fact":
        allowed = SUBCATEGORY_MAP[self.category]
        if self.subcategory not in allowed:
            raise ValueError(
                f"subcategory {self.subcategory!r} is not valid for category "
                f"{self.category.value!r}. Allowed: {allowed}"
            )
        return self

    @model_validator(mode="after")
    def _check_negation_language(self) -> "Fact":
        if self.negated and not _NEGATION_RE.search(self.content):
            raise ValueError(
                f"Fact {self.id!r} is negated but its content lacks explicit "
                f"negation language: {self.content!r}. Express the negation "
                f"(e.g. 'Patient denies chest pain'), or extend NEGATION_CUES "
                f"if this is a legitimate phrasing."
            )
        return self


class FactFile(BaseModel):
    """A document's metadata plus its list of extracted facts."""

    model_config = ConfigDict(extra="forbid")

    metadata: DocumentMetadata
    facts: list[Fact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "FactFile":
        counts = Counter(f.id for f in self.facts)
        dupes = sorted(i for i, n in counts.items() if n > 1)
        if dupes:
            raise ValueError(f"Duplicate fact ids within FactFile: {dupes}")
        return self

    # ---- query helpers ----

    def get_facts_by_category(self, category: FactCategory) -> list["Fact"]:
        return [f for f in self.facts if f.category == category]

    def get_facts_by_group(self, group_id: str) -> list["Fact"]:
        return [f for f in self.facts if f.group_id == group_id]

    def get_negated_facts(self) -> list["Fact"]:
        return [f for f in self.facts if f.negated]

    def summary(self) -> dict:
        """Counts by category and subcategory."""
        return {
            "total": len(self.facts),
            "by_category": dict(Counter(f.category.value for f in self.facts)),
            "by_subcategory": dict(Counter(f.subcategory for f in self.facts)),
        }

    # ---- serialization ----

    def to_json(self, path: Path | str) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path | str) -> "FactFile":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    # ---- reconstruction ----

    def reconstruct(self) -> str:
        """Render the fact file back into a readable plain-text clinical summary.

        Implements the 8-step reconstruction from the spec. **Render order is
        consumption priority**: a fact merged into an earlier section is marked
        consumed and is not rendered again by a later section. That is why an
        explanatory_link belonging to a medication group is folded into
        MEDICATIONS (step 4) and does *not* reappear under CLINICAL REASONING
        (step 6). Reordering the steps changes the output by design, not by bug.
        """
        consumed: set[str] = set()
        sections: list[tuple[str, str]] = []

        def related(
            anchor: "Fact", *, category: FactCategory, subcats: set[str]
        ) -> list["Fact"]:
            """Unconsumed facts in `category`/`subcats` tied to `anchor` by
            shared group_id (primary signal) or shared entity (fallback)."""
            out: list[Fact] = []
            for f in self.facts:
                if f.id == anchor.id or f.id in consumed:
                    continue
                if f.category != category or f.subcategory not in subcats:
                    continue
                same_group = (
                    anchor.group_id is not None and f.group_id == anchor.group_id
                )
                shares_entity = bool(set(f.entities) & set(anchor.entities))
                if same_group or shares_entity:
                    out.append(f)
            return out

        def _primary_entity(f: "Fact") -> str:
            return f.entities[0].strip().lower() if f.entities else ""

        def duplicate_drop_ids(anchors: list["Fact"]) -> set[str]:
            """IDs of section anchors to skip as duplicates. When several
            anchors share a primary entity, keep only one: the most specific
            (longest content), tie-broken by the most recent (latest in
            document order). Anchors without a primary entity are never
            dropped."""
            best: dict[str, "Fact"] = {}
            for f in anchors:
                key = _primary_entity(f)
                if not key:
                    continue
                cur = best.get(key)
                if cur is None or len(f.content) >= len(cur.content):
                    best[key] = f
            keep = {f.id for f in best.values()}
            return {
                f.id for f in anchors if _primary_entity(f) and f.id not in keep
            }

        cat = FactCategory  # local alias for brevity below

        # Step 1 — patient identity (noun phrase, no trailing period).
        parts = []
        for f in self.facts:
            if f.category is cat.CATEGORICAL and f.subcategory == "patient_identifier":
                parts.append(_strip_patient_prefix(f.content).strip())
                consumed.add(f.id)
        if parts:
            sections.append(("PATIENT", ", ".join(parts)))

        # Step 2 — critical alerts (verbatim span preserves severity wording).
        alert_subs = {"allergy", "infection_precaution", "fall_risk"}
        parts = []
        for f in self.facts:
            if f.category is cat.CATEGORICAL and f.subcategory in alert_subs:
                text = f.span or _capitalize_first(_strip_patient_prefix(f.content))
                parts.append(_ensure_period(text))
                consumed.add(f.id)
        if parts:
            sections.append(("ALERTS", " ".join(parts)))

        # Step 3 — active problem list, with onset merged in from a related
        # temporal fact (same group / shared entity). Diagnoses sharing a
        # primary entity (e.g. the same finding noted on CXR and on CT) are
        # deduplicated to a single, most-specific entry.
        dx_anchors = [
            f for f in self.facts
            if f.category is cat.CATEGORICAL and f.subcategory == "previous_diagnosis"
        ]
        dx_drop = duplicate_drop_ids(dx_anchors)
        parts = []
        for f in dx_anchors:
            if f.id in dx_drop:
                consumed.add(f.id)
                continue
            if f.negated:  # preserve negation rather than rendering entity only
                parts.append(_ensure_period(f.span or _capitalize_first(_strip_patient_prefix(f.content))))
                consumed.add(f.id)
                continue
            name = f.entities[0]
            onset = related(f, category=cat.TEMPORAL,
                            subcats={"time_since_event", "event_sequence"})
            if onset:
                paren = (onset[0].span or onset[0].content).strip()
                text = f"{name} ({paren})"
                consumed.add(onset[0].id)
            else:
                text = name
            parts.append(_ensure_period(text))
            consumed.add(f.id)
        if parts:
            sections.append(("DIAGNOSES", " ".join(parts)))

        # Step 4 — medications: drug + current dosage, then any dosage change
        # and explanatory link merged into one statement. The explanatory_link
        # is consumed here so step 6 will not render it again.
        drug_anchors = [
            f for f in self.facts
            if f.category is cat.CATEGORICAL and f.subcategory == "drug_name"
        ]
        drug_drop = duplicate_drop_ids(drug_anchors)
        parts = []
        for f in drug_anchors:
            if f.id in drug_drop:
                consumed.add(f.id)
                continue
            if f.negated:
                parts.append(_ensure_period(f.span or _capitalize_first(_strip_patient_prefix(f.content))))
                consumed.add(f.id)
                continue
            drug = _capitalize_first(f.entities[0])
            dosage = related(f, category=cat.QUANTITATIVE, subcats={"medication_dosage"})
            if dosage:
                base = f"{drug} {' '.join(dosage[0].values)}".strip()
                consumed.add(dosage[0].id)
            else:
                # No matching medication_dosage (by group_id or entity). Mark
                # explicitly so "dose not extracted" reads differently from a
                # bare drug name.
                base = f"{drug} (dose not specified)"
            clause = ""
            change = related(f, category=cat.TEMPORAL, subcats={"dosage_change"})
            if change:
                c = change[0]
                nums = [v for v in c.values if not _is_date(v)]
                dates = [v for v in c.values if _is_date(v)]
                old = nums[0] if nums else None
                new = nums[1] if len(nums) > 1 else None
                verb = _direction(old, new, up="increased", down="decreased", flat="changed")
                if old:
                    clause += f", {verb} from {old}"
                    if dates:
                        clause += f" on {dates[0]}"
                consumed.add(c.id)
            link = related(f, category=cat.CLINICAL_REASONING, subcats={"explanatory_link"})
            if link:
                reason = _causal_clause(link[0].content)
                if reason:
                    clause += " " + reason
                consumed.add(link[0].id)
            parts.append(_ensure_period(base + clause))
            consumed.add(f.id)
        # Orphan dosage facts: a medication_dosage with no associated drug_name
        # (none shared its group_id or entity) still renders as drug + dose here
        # rather than being dropped or stranded from its drug name.
        for f in self.facts:
            if f.id in consumed:
                continue
            if f.category is cat.QUANTITATIVE and f.subcategory == "medication_dosage":
                if f.negated:
                    parts.append(_ensure_period(f.span or _capitalize_first(_strip_patient_prefix(f.content))))
                else:
                    drug = _capitalize_first(f.entities[0])
                    parts.append(_ensure_period(f"{drug} {' '.join(f.values)}".strip()))
                consumed.add(f.id)
        if parts:
            sections.append(("MEDICATIONS", " ".join(parts)))

        # Step 5 — recent results, with lab trajectory trend merged in.
        # Results sharing a primary entity (the same test reported twice) are
        # deduplicated to the most specific/most recent entry.
        result_subs = {"lab_value", "vital_sign"}
        result_anchors = [
            f for f in self.facts
            if f.category is cat.QUANTITATIVE and f.subcategory in result_subs
        ]
        result_drop = duplicate_drop_ids(result_anchors)
        parts = []
        for f in result_anchors:
            if f.id in result_drop:
                consumed.add(f.id)
                continue
            if f.negated:
                parts.append(_ensure_period(f.span or _capitalize_first(_strip_patient_prefix(f.content))))
                consumed.add(f.id)
                continue
            value = f.values[0] if f.values else ""
            base = f"{f.entities[0]} {value}".strip()
            date = _date_from_tags(f.tags)
            if date:
                base += f" ({date})"
            clause = ""
            traj = related(f, category=cat.TEMPORAL, subcats={"lab_trajectory"})
            if traj:
                prior = traj[0].values[0] if traj[0].values else None
                if prior:
                    verb = _direction(prior, value, up="up", down="down", flat="unchanged")
                    clause = f", {verb} from {prior}"
                consumed.add(traj[0].id)
            parts.append(_ensure_period(base + clause))
            consumed.add(f.id)
        if parts:
            sections.append(("RESULTS", " ".join(parts)))

        # Step 6 — clinical reasoning (skips anything already consumed above).
        reasoning_subs = {
            "uncertainty_marker",
            "considered_rejected_diagnosis",
            "explanatory_link",
            "conditional_fact",
        }
        parts = []
        for f in self.facts:
            if f.id in consumed:
                continue
            if f.category is cat.CLINICAL_REASONING and f.subcategory in reasoning_subs:
                parts.append(_ensure_period(f.content))
                consumed.add(f.id)
        if parts:
            sections.append(("CLINICAL REASONING", " ".join(parts)))

        # Step 7 — pending / planned tasks.
        parts = []
        for f in self.facts:
            if f.id in consumed:
                continue
            if f.category is cat.CLINICAL_REASONING and f.subcategory == "pending_planned_task":
                parts.append(_ensure_period(f.content))
                consumed.add(f.id)
        if parts:
            sections.append(("PENDING", " ".join(parts)))

        # Step 8 — supporting context (behavior, family history, code status,
        # negated facts). Negated facts render with explicit negation language.
        context_subs = ("behavior", "family_history", "code_status", "negated_fact")
        parts = []
        for sub in context_subs:
            for f in self.facts:
                if f.id in consumed:
                    continue
                if f.category is cat.CATEGORICAL and f.subcategory == sub:
                    text = f.span or _capitalize_first(_strip_patient_prefix(f.content))
                    parts.append(_ensure_period(text))
                    consumed.add(f.id)
        if parts:
            sections.append(("CONTEXT", " ".join(parts)))

        return "\n\n".join(f"{label}: {body}" for label, body in sections)


# ---------------------------------------------------------------------------
# Reconstruction text helpers
# ---------------------------------------------------------------------------

_PATIENT_PREFIXES = (
    "patient is a ",
    "patient is an ",
    "patient is ",
    "patient has a ",
    "patient has ",
    "the patient ",
    "patient ",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CAUSAL_MARKERS = ("due to", "because of", "secondary to", "attributed to", "owing to")


def _strip_patient_prefix(text: str) -> str:
    low = text.lower()
    for pre in _PATIENT_PREFIXES:
        if low.startswith(pre):
            return text[len(pre):]
    return text


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _ensure_period(text: str) -> str:
    text = text.rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _leading_number(value: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(m.group()) if m else None


def _is_date(value: str) -> bool:
    return bool(_DATE_RE.match(value.strip()))


def _direction(
    old: str | None, new: str | None, *, up: str, down: str, flat: str
) -> str:
    o, n = _leading_number(old or ""), _leading_number(new or "")
    if o is not None and n is not None:
        if n > o:
            return up
        if n < o:
            return down
    return flat


def _date_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        prefix, _, detail = t.partition(":")
        if prefix == FactCategory.TEMPORAL.value and _is_date(detail):
            return detail
    return None


def _causal_clause(content: str) -> str | None:
    low = content.lower()
    hits = [low.find(m) for m in _CAUSAL_MARKERS if m in low]
    if not hits:
        return None
    return content[min(hits):].strip()
