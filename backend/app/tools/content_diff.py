from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import re

from app.models.schemas import MeaningfulChangeAssessment
from app.tools.page_extract import normalize_readable_text

_QUOTED = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{2,80})[\"'“”‘’]")
_NAMED = re.compile(
    r"\b(?:name|named|called|keyword|value)\s+[\"'“”‘’]?([A-Za-z][\w-]{1,40})",
    re.IGNORECASE,
)
_BROAD = re.compile(
    r"\b("
    r"whenever|any (?:substantial )?(?:readable[- ]content )?change|"
    r"anything changes|(?:this )?(?:web)?page changes|webpage changes|"
    r"if this page changes|when this (?:web)?page changes"
    r")\b",
    re.IGNORECASE,
)
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)"
)
_DATE = re.compile(
    rf"\b(?:\d{{1,2}}\s+{_MONTH}\.?\s+\d{{4}}|"
    rf"{_MONTH}\.?\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"\d{{4}}-\d{{2}}-\d{{2}}|"
    rf"{_MONTH}\.?\s+\d{{1,2}})\b",
    re.IGNORECASE,
)
_COUNTER = re.compile(
    r"\b\d[\d,.]*\s*(?:likes?|views?|visitors?|comments?|submissions?|"
    r"upvotes?|downloads?|shares?|followers?|points?)\b",
    re.IGNORECASE,
)
_COUNTER_LABEL = re.compile(
    r"\b(?:likes?|views?|visitors?|comments?|submissions?|upvotes?|"
    r"downloads?|shares?|followers?)\s*[:\-]?\s*\d[\d,.]*\b",
    re.IGNORECASE,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class GoalMatch:
    targets: list[str] = field(default_factory=list)
    previous_contains: dict[str, bool] = field(default_factory=dict)
    current_contains: dict[str, bool] = field(default_factory=dict)
    previous_excerpt: str = ""
    current_excerpt: str = ""
    signal: str = "none"


def extract_goal_match(
    goal: str,
    previous: str | None,
    current: str | None,
) -> GoalMatch:
    """Deterministic goal-target presence comparison. Not website-specific."""
    old = previous or ""
    new = current or ""
    targets = _watched_terms(goal or "")
    match = GoalMatch(targets=targets)
    if not targets:
        match.previous_excerpt = normalize_readable_text(old)[:400]
        match.current_excerpt = normalize_readable_text(new)[:400]
        return match
    appeared = False
    disappeared = False
    moved = False
    excerpts_old: list[str] = []
    excerpts_new: list[str] = []
    for term in targets:
        in_old = _contains_term(old, term)
        in_new = _contains_term(new, term)
        match.previous_contains[term] = in_old
        match.current_contains[term] = in_new
        if in_old:
            excerpts_old.append(_term_window(old, term) or term)
        if in_new:
            excerpts_new.append(_term_window(new, term) or term)
        if in_new and not in_old:
            appeared = True
        if in_old and not in_new:
            disappeared = True
        if in_old and in_new and _term_window(old, term) != _term_window(new, term):
            moved = True
    match.previous_excerpt = " | ".join(excerpts_old) or normalize_readable_text(old)[:400]
    match.current_excerpt = " | ".join(excerpts_new) or normalize_readable_text(new)[:400]
    if appeared and disappeared:
        match.signal = "replaced"
    elif appeared:
        match.signal = "appeared"
    elif disappeared:
        match.signal = "disappeared"
    elif moved:
        match.signal = "moved"
    elif any(match.previous_contains.values()) or any(match.current_contains.values()):
        match.signal = "unchanged"
    return match


def observation_texts_equivalent(previous: str | None, current: str | None) -> bool:
    """True when readable snapshots match after noise-tolerant normalization."""
    return normalize_readable_text(previous or "") == normalize_readable_text(
        current or ""
    )


def summarize_text_change(previous: str | None, current: str | None, *, limit: int = 280) -> str:
    """Build a short text-level summary of how normalized content changed."""
    old = " ".join((previous or "").split())
    new = " ".join((current or "").split())
    if not old and new:
        return _clip(f"New content: {new}", limit)
    if old and not new:
        return "Monitored content was removed."
    if old == new:
        return "No meaningful content change."

    old_parts = [part for part in _SENTENCE.split(old) if part]
    new_parts = [part for part in _SENTENCE.split(new) if part]
    replaced: list[str] = []
    matcher = difflib.SequenceMatcher(a=old_parts, b=new_parts, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            before = " ".join(old_parts[i1:i2]).strip()
            after = " ".join(new_parts[j1:j2]).strip()
            if before and after:
                replaced.append(f"{before} → {after}")
        elif tag == "delete":
            before = " ".join(old_parts[i1:i2]).strip()
            if before:
                replaced.append(f"Removed: {before}")
        elif tag == "insert":
            after = " ".join(new_parts[j1:j2]).strip()
            if after:
                replaced.append(f"Added: {after}")
        if len(replaced) >= 3:
            break
    if replaced:
        return _clip("; ".join(replaced), limit)
    return _clip(f"Content changed from '{old}' to '{new}'.", limit)


def _watched_terms(goal: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_QUOTED, _NAMED):
        for match in pattern.finditer(goal):
            term = match.group(1).strip().strip("\"'“”‘’")
            key = term.lower()
            if len(term) < 2 or key in seen:
                continue
            seen.add(key)
            found.append(term)
    return found


def _contains_term(text: str, term: str) -> bool:
    if " " in term:
        return term.lower() in text.lower()
    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


def _term_window(text: str, term: str, radius: int = 90) -> str:
    match = re.search(re.escape(term), text, re.IGNORECASE)
    if match is None:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return normalize_readable_text(text[start:end])


def _without_counters(text: str) -> str:
    cleaned = _COUNTER.sub(" ", text or "")
    cleaned = _COUNTER_LABEL.sub(" ", cleaned)
    return normalize_readable_text(cleaned)


def _dates(text: str) -> set[str]:
    return {match.group(0).lower() for match in _DATE.finditer(text or "")}


def _assessment(
    *,
    meaningful: bool,
    summary: str,
    reason: str,
    changed_items: list[str],
    previous_relevant: str | None = None,
    current_relevant: str | None = None,
) -> MeaningfulChangeAssessment:
    return MeaningfulChangeAssessment(
        meaningful_change=meaningful,
        summary=summary,
        reason=reason,
        action_required=meaningful,
        confidence=0.95 if meaningful else 0.9,
        changed_items=changed_items,
        previous_relevant_content=previous_relevant,
        current_relevant_content=current_relevant,
    )


def ground_meaningful_change(
    goal: str,
    previous: str | None,
    current: str | None,
) -> MeaningfulChangeAssessment | None:
    """Decide a goal-relevant change from the two readable snapshots.

    Returns None when the texts do not contain a clear signal and the model
    should decide. Hash equality is handled before this runs.
    """
    old = previous or ""
    new = current or ""
    if observation_texts_equivalent(old, new):
        return _assessment(
            meaningful=False,
            summary="No meaningful content change.",
            reason="The readable page text is the same after noise normalization.",
            changed_items=[],
        )

    goal_text = goal or ""
    lowered = goal_text.lower()
    match = extract_goal_match(goal_text, old, new)
    terms = match.targets
    if terms:
        if match.signal in {"appeared", "disappeared", "replaced", "moved"}:
            shown = terms[0]
            if match.signal == "disappeared":
                summary = f"Watched value '{shown}' was removed or replaced."
            elif match.signal == "appeared":
                summary = f"Watched value '{shown}' appeared."
            else:
                summary = f"Watched value '{shown}' changed."
            return _assessment(
                meaningful=True,
                summary=summary,
                reason=(
                    "The goal names a specific value, and that value appeared, "
                    "disappeared, or changed in the readable page text."
                ),
                changed_items=terms,
                previous_relevant=match.previous_excerpt,
                current_relevant=match.current_excerpt,
            )
        return _assessment(
            meaningful=False,
            summary="The watched value did not change.",
            reason=(
                "Other page text changed, but the value named in the goal "
                "is unchanged."
            ),
            changed_items=[],
            previous_relevant=match.previous_excerpt,
            current_relevant=match.current_excerpt,
        )

    deadline_goal = any(word in lowered for word in ("deadline", "due date", "application date"))
    if deadline_goal:
        old_dates = _dates(old)
        new_dates = _dates(new)
        if old_dates != new_dates:
            return _assessment(
                meaningful=True,
                summary="The watched date changed.",
                reason="The goal watches a date, and the date in the page text changed.",
                changed_items=sorted(old_dates.symmetric_difference(new_dates)),
            )
        return _assessment(
            meaningful=False,
            summary="The watched date did not change.",
            reason="The goal watches a date, and that date is the same in both snapshots.",
            changed_items=[],
        )

    counter_only = _without_counters(old) == _without_counters(new)
    watches_counts = any(
        word in lowered
        for word in ("like", "view", "visitor", "submission count", "comment", "upvote")
    )
    if counter_only and not watches_counts:
        return _assessment(
            meaningful=False,
            summary="Only an unrelated counter changed.",
            reason=(
                "The readable change is a count such as likes, views, or "
                "submissions, and the goal does not ask about that count."
            ),
            changed_items=[],
        )

    item_goal = any(word in lowered for word in ("paper", "article", "release"))
    broad = _BROAD.search(goal_text) is not None
    if item_goal or broad:
        return _assessment(
            meaningful=True,
            summary="The readable page content changed.",
            reason=(
                "The goal asks about new or changed page content, and the "
                "readable text changed beyond unrelated counters."
            ),
            changed_items=["readable content"],
        )
    return None


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
