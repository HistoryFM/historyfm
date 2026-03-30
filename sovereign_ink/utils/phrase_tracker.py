"""Cross-chapter phrase tracker — detects and accumulates notable phrases,
similes, and metaphors so they can be banned from subsequent chapters.

Also detects construction-level patterns (abstracted sentence templates
with variable slots) to prevent structural repetition even when the
specific words differ."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SIMILE_PATTERN = re.compile(
    r"(?:like|as(?:\s+if)?)\s+(?:a|an|the)?\s*[a-z][\w\s,'-]{4,60}",
    re.IGNORECASE,
)

BODILY_REACTION_PHRASES = [
    r"throat\s+(?:constrict|tighten|close)",
    r"blood\s+(?:drain|rush|rise)",
    r"hands?\s+(?:tremble|shake|shook|trembl)",
    r"mouth\s+(?:went|go|gone)\s+dry",
    r"heart\s+(?:hammer|pound|race|thud|slam)",
    r"bile\s+(?:rise|rising|rose)",
    r"black\s+spots?\s+danc",
    r"knees?\s+(?:went|go|gone)\s+weak",
    r"cold\s+sweat",
    r"ice\s+(?:shot|ran|spread)\s+through",
    r"stomach\s+(?:clench|churn|drop|lurch)",
    r"breath\s+(?:caught|catch|hitched)",
    r"pulse\s+(?:quicken|race|hammer|spike)",
]

IMPACT_CONSTRUCTION_PHRASES = [
    r"struck\s+\w+\s+(?:like\s+a|with\s+(?:\w+\s+)?(?:force|weight|intensity))",
    r"hit\s+\w+\s+(?:like\s+a|with\s+(?:\w+\s+)?(?:force|weight))",
    r"(?:words?|reali[sz]ation|question|accusation|revelation)\s+struck",
]

FORMULAIC_QUALIFIER_PHRASES = [
    r"with\s+(?:evident|practiced|unmistakable|barely\s+concealed|calculated|careful|deliberate|studied|unconscious)\s+\w+",
]

AI_CLICHE_PATTERNS = (
    BODILY_REACTION_PHRASES
    + IMPACT_CONSTRUCTION_PHRASES
    + FORMULAIC_QUALIFIER_PHRASES
)

AI_CLICHE_RE = re.compile(
    "|".join(AI_CLICHE_PATTERNS), re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Construction-level patterns — abstracted sentence templates with slots
# ---------------------------------------------------------------------------

CONSTRUCTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "the weight/burden/gravity of X settling/pressing upon Y"
    (re.compile(
        r"the\s+(?:weight|burden|gravity|force|enormity)\s+of\s+[\w\s]+\s+"
        r"(?:settl|press|descend|fall)\w*\s+(?:up)?on",
        re.IGNORECASE,
    ), "the [WEIGHT-NOUN] of [X] [SETTLING-VERB] upon [Y]"),

    # "something in X's expression/voice/manner"
    (re.compile(
        r"something\s+in\s+\w+(?:'s)?\s+"
        r"(?:expression|voice|manner|tone|bearing|posture|eyes|gaze)",
        re.IGNORECASE,
    ), "something in [CHARACTER]'s [expression/voice/manner]"),

    # "X found Y studying/watching/regarding Z"
    (re.compile(
        r"\w+\s+found\s+\w+\s+(?:studying|watching|regarding|observing|examining)",
        re.IGNORECASE,
    ), "[CHARACTER] found [CHARACTER] [WATCHING-VERB] [OBJECT]"),

    # "with a X that Y" (formulaic characterization)
    (re.compile(
        r"with\s+a\s+\w+\s+that\s+(?:spoke|whispered|hinted|suggested|betrayed|revealed)",
        re.IGNORECASE,
    ), "with a [NOUN] that [spoke/suggested/betrayed]"),

    # "a X that spoke/suggested of Y"
    (re.compile(
        r"a\s+\w+\s+that\s+(?:spoke|whispered|hinted|suggested|betrayed|revealed)\s+of",
        re.IGNORECASE,
    ), "a [NOUN] that [VERB] of [QUALITY]"),

    # "which is precisely the point / which was precisely what"
    (re.compile(
        r"which\s+(?:is|was)\s+precisely\s+(?:the|what|why)",
        re.IGNORECASE,
    ), "which [is/was] precisely [the point/what/why]"),

    # "mathematical/surgical/clinical precision"
    (re.compile(
        r"(?:mathematical|surgical|clinical|ruthless|cold)\s+precision",
        re.IGNORECASE,
    ), "[ADJ] precision"),

    # "measuring us/him/her/them"
    (re.compile(
        r"measuring\s+(?:us|him|her|them|me|you|each\s+other)",
        re.IGNORECASE,
    ), "measuring [PRONOUN]"),

    # "settled/settling upon [pronoun/character] like a [noun]"
    (re.compile(
        r"settl\w+\s+(?:up)?on\s+\w+\s+like\s+a",
        re.IGNORECASE,
    ), "[SETTLING] upon [CHARACTER] like a [NOUN]"),
]


def extract_notable_phrases(chapter_text: str) -> list[str]:
    """Extract similes, metaphors, and repeated descriptive constructions
    from a single chapter using regex heuristics.

    Returns a deduplicated list of phrase strings.
    """
    phrases: set[str] = set()

    for m in SIMILE_PATTERN.finditer(chapter_text):
        raw = m.group(0).strip()
        cleaned = re.sub(r"\s+", " ", raw).strip(" ,.")
        if len(cleaned.split()) >= 3:
            phrases.add(cleaned.lower())

    for m in AI_CLICHE_RE.finditer(chapter_text):
        raw = m.group(0).strip()
        phrases.add(re.sub(r"\s+", " ", raw).lower())

    return sorted(phrases)


def extract_construction_patterns(chapter_text: str) -> list[str]:
    """Extract abstracted construction patterns from chapter text.

    Returns construction template strings like
    'the [WEIGHT-NOUN] of [X] [SETTLING-VERB] upon [Y]'.
    """
    patterns: set[str] = set()
    for regex, template in CONSTRUCTION_PATTERNS:
        if regex.search(chapter_text):
            patterns.add(template)
    return sorted(patterns)


def extract_phrases_with_llm(
    chapter_text: str,
    chapter_number: int,
    llm_client,
    system_prompt: str,
    model: str,
) -> tuple[list[str], list[str]]:
    """Use a lightweight LLM call to extract distinctive phrases, similes,
    metaphors, repeated constructions, AND construction-level patterns.

    Returns (phrases, constructions) where constructions are abstracted
    template strings with [SLOT] markers.
    """
    user_prompt = (
        f"You are a copy-editor reviewing Chapter {chapter_number} of a novel. "
        "Extract distinctive phrases and construction patterns that should NOT "
        "be reused in later chapters.\n\n"
        "**Phrases** (literal strings to ban):\n"
        "1. Similes and metaphors — any figurative comparison\n"
        "2. Involuntary physical/emotional reactions — bodily responses to "
        "emotion or surprise\n"
        "3. Distinctive descriptive constructions — any memorable image or "
        "unusual word combination\n"
        "4. Any sentence-level pattern used more than once within this chapter\n\n"
        "**Construction patterns** (abstracted templates with [SLOT] markers):\n"
        "5. Sentence-structure templates that would feel repetitive if reused "
        "with different nouns/adjectives. Express as templates with [SLOT] markers.\n"
        '   Examples: "the [WEIGHT-NOUN] of [X] settling upon [Y]", '
        '"something in [CHARACTER]\'s [ATTRIBUTE]", '
        '"[CHARACTER] found [CHARACTER] [WATCHING-VERB] [OBJECT]"\n\n'
        "Return a JSON object with two arrays:\n"
        '{"phrases": ["literal phrase 1", ...], '
        '"constructions": ["pattern template 1", ...]}\n'
        "No commentary, no markdown fences.\n\n"
        f"Chapter text:\n\n{chapter_text[:8000]}"
    )

    response = llm_client.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=0.2,
        max_tokens=2048,
    )

    content = response.content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)

        # Handle new format: {"phrases": [...], "constructions": [...]}
        if isinstance(parsed, dict):
            phrases = [
                str(p).strip().lower()
                for p in parsed.get("phrases", [])
                if isinstance(p, str) and len(p) > 3
            ]
            constructions = [
                str(c).strip()
                for c in parsed.get("constructions", [])
                if isinstance(c, str) and len(c) > 3
            ]
            return phrases, constructions

        # Backward-compatible: old format was a flat JSON array of phrases
        if isinstance(parsed, list):
            phrases = [
                str(p).strip().lower()
                for p in parsed
                if isinstance(p, str) and len(p) > 3
            ]
            return phrases, []

    except (json.JSONDecodeError, Exception):
        logger.warning(
            "Failed to parse LLM phrase extraction for chapter %d, using regex only",
            chapter_number,
        )
    return [], []


def _normalize_entry(entry) -> dict:
    """Normalize a banned-phrases entry to the new format.

    Old format: list of phrase strings
    New format: {"phrases": [...], "constructions": [...]}
    """
    if isinstance(entry, list):
        return {"phrases": entry, "constructions": []}
    if isinstance(entry, dict):
        return {
            "phrases": entry.get("phrases", []),
            "constructions": entry.get("constructions", []),
        }
    return {"phrases": [], "constructions": []}


def update_banned_phrases(
    state_dir: Path,
    chapter_number: int,
    chapter_text: str,
    llm_client=None,
    system_prompt: str = "",
    model: str = "",
) -> list[str]:
    """Extract phrases and construction patterns from a chapter and merge
    them into the cumulative banned-phrases file.

    Returns the full list of banned phrases (across all chapters processed
    so far). Construction patterns are stored alongside but returned
    separately via ``load_banned_constructions()``.
    """
    banned_path = state_dir / "banned_phrases.json"

    existing: dict = {}
    if banned_path.exists():
        try:
            existing = json.loads(banned_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            existing = {}

    # Normalize any old-format entries
    for key in existing:
        existing[key] = _normalize_entry(existing[key])

    regex_phrases = extract_notable_phrases(chapter_text)
    regex_constructions = extract_construction_patterns(chapter_text)

    llm_phrases: list[str] = []
    llm_constructions: list[str] = []
    if llm_client and model:
        try:
            llm_phrases, llm_constructions = extract_phrases_with_llm(
                chapter_text, chapter_number, llm_client, system_prompt, model
            )
        except Exception:
            logger.warning(
                "LLM phrase extraction failed for chapter %d, using regex only",
                chapter_number,
            )

    combined_phrases = sorted(set(regex_phrases) | set(llm_phrases))
    combined_constructions = sorted(set(regex_constructions) | set(llm_constructions))

    existing[str(chapter_number)] = {
        "phrases": combined_phrases,
        "constructions": combined_constructions,
    }

    all_phrases = sorted({
        p
        for entry in existing.values()
        for p in _normalize_entry(entry)["phrases"]
    })

    banned_path.parent.mkdir(parents=True, exist_ok=True)
    banned_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    all_constructions = sorted({
        c
        for entry in existing.values()
        for c in _normalize_entry(entry)["constructions"]
    })

    logger.info(
        "Phrase tracker: chapter %d added %d phrases + %d constructions "
        "(total banned: %d phrases, %d constructions)",
        chapter_number,
        len(combined_phrases),
        len(combined_constructions),
        len(all_phrases),
        len(all_constructions),
    )

    return all_phrases


def load_banned_phrases(state_dir: Path) -> list[str]:
    """Load the accumulated banned phrases from disk.

    Handles both old format (chapter -> list) and new format
    (chapter -> {"phrases": [...], "constructions": [...]}).
    """
    banned_path = state_dir / "banned_phrases.json"
    if not banned_path.exists():
        return []

    try:
        data = json.loads(banned_path.read_text(encoding="utf-8"))
        phrases: set[str] = set()
        for entry in data.values():
            phrases.update(_normalize_entry(entry)["phrases"])
        return sorted(phrases)
    except (json.JSONDecodeError, Exception):
        return []


def load_banned_constructions(state_dir: Path) -> list[str]:
    """Load the accumulated banned construction patterns from disk.

    Returns abstracted template strings like
    'the [WEIGHT-NOUN] of [X] [SETTLING-VERB] upon [Y]'.
    """
    banned_path = state_dir / "banned_phrases.json"
    if not banned_path.exists():
        return []

    try:
        data = json.loads(banned_path.read_text(encoding="utf-8"))
        constructions: set[str] = set()
        for entry in data.values():
            constructions.update(_normalize_entry(entry)["constructions"])
        return sorted(constructions)
    except (json.JSONDecodeError, Exception):
        return []
