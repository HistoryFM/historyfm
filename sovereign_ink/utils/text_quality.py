"""Text quality analysis utilities for detecting structural prose problems.

Provides code-level detection of issues that LLM revision passes often miss:
duplicate passages, over-explanation, repeated syntactic signatures, frequency
outliers, sensory deficits, and essay-like abstraction blocks.

Also provides gate functions (``gate_*``) that wrap detectors with explicit
pass/fail thresholds for use as pre-save acceptance gates in Stage 4.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field as dc_field
from difflib import SequenceMatcher
from math import sqrt


# ------------------------------------------------------------------
# P0: Intra-chapter duplicate detection
# ------------------------------------------------------------------

def detect_duplicate_passages(
    text: str,
    similarity_threshold: float = 0.60,
    min_paragraph_words: int = 15,
) -> list[dict]:
    """Find near-duplicate paragraphs within a chapter.

    Returns a list of dicts, each with keys:
      - ``para_a_idx``, ``para_b_idx``: 0-based paragraph indices
      - ``para_a_preview``, ``para_b_preview``: first 80 chars
      - ``similarity``: float 0–1
    """
    paragraphs = _split_paragraphs(text)
    results: list[dict] = []

    for i in range(len(paragraphs)):
        words_i = paragraphs[i].split()
        if len(words_i) < min_paragraph_words:
            continue
        for j in range(i + 1, len(paragraphs)):
            words_j = paragraphs[j].split()
            if len(words_j) < min_paragraph_words:
                continue
            ratio = SequenceMatcher(None, words_i, words_j).ratio()
            if ratio >= similarity_threshold:
                results.append({
                    "para_a_idx": i,
                    "para_b_idx": j,
                    "para_a_preview": paragraphs[i][:80],
                    "para_b_preview": paragraphs[j][:80],
                    "similarity": round(ratio, 3),
                })

    return results


def format_duplicate_report(duplicates: list[dict]) -> str:
    """Format duplicate findings into a directive string for the revision prompt."""
    if not duplicates:
        return ""

    lines = [
        "CRITICAL — DUPLICATE PASSAGE ALERT:",
        "The following paragraph pairs are near-duplicates (>60% textual similarity). "
        "This is a catastrophic error. You MUST eliminate the duplication by removing "
        "one instance or rewriting both to be structurally distinct.",
        "",
    ]
    for d in duplicates:
        lines.append(
            f"- Paragraphs {d['para_a_idx']+1} and {d['para_b_idx']+1} "
            f"({d['similarity']:.0%} similar):"
        )
        lines.append(f'  A: "{d["para_a_preview"]}..."')
        lines.append(f'  B: "{d["para_b_preview"]}..."')
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# P0: Over-explanation detection ("trust the reader" violations)
# ------------------------------------------------------------------

_MOMENT_MARKERS_RE = re.compile(
    r"\b(?:silence|paused|pause|hesitated|hesitation|did not answer|"
    r"didn't answer|did not speak|didn't speak|looked away|"
    r"looked down|nodded|shook (?:his|her|their) head|gesture)\b",
    re.IGNORECASE,
)

_EXPLANATION_MARKERS = [
    re.compile(r"\bthey were not\b.{0,80}\bthey were\b", re.IGNORECASE),
    re.compile(r"\bnot because\b.{0,120}\bbut because\b", re.IGNORECASE),
    re.compile(
        r"\bthe [a-z'-]+ was not [^.]{1,100}\.\s*it was [^.]{1,120}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:he|she|it|they) did not [^.]{1,100}\.\s*"
        r"(?:he|she|it|they) [a-z][^.]{1,120}",
        re.IGNORECASE,
    ),
]


def detect_over_explanation(
    text: str,
    short_line_words: int = 15,
    lookahead_sentences: int = 5,
    min_gloss_words: int = 100,
) -> list[dict]:
    """Detect dramatic moments followed by excessive narrator annotation."""
    sentences = _split_sentences(text)
    if not sentences:
        return []

    findings: list[dict] = []
    for idx, sent in enumerate(sentences):
        if not _is_dramatic_moment(sent, short_line_words):
            continue

        following = sentences[idx + 1 : idx + 1 + lookahead_sentences]
        if len(following) < 3:
            continue
        gloss_text = " ".join(following).strip()
        gloss_words = len(re.findall(r"[a-zA-Z']+", gloss_text))
        if gloss_words < min_gloss_words:
            continue

        marker_hits = sum(1 for pat in _EXPLANATION_MARKERS if pat.search(gloss_text))
        if marker_hits == 0:
            continue

        findings.append({
            "moment": sent.strip(),
            "gloss_word_count": gloss_words,
            "marker_hits": marker_hits,
            "gloss_preview": gloss_text[:220],
        })

    return findings


def format_over_explanation_report(findings: list[dict]) -> str:
    """Format over-explanation findings for mandatory revision directives."""
    if not findings:
        return ""

    lines = [
        "TRUST-THE-READER VIOLATIONS (OVER-EXPLANATION):",
        "Short dramatic moments are followed by heavy narrator gloss. "
        "Apply THE SILENCE RULE: after a loaded short line, silence, or gesture, "
        "do not explain what it meant. Keep the moment and delete the annotation.",
        "",
    ]
    for item in findings[:8]:
        lines.append(
            f'- Moment: "{item["moment"][:120]}..." '
            f"(followed by ~{item['gloss_word_count']} words of gloss; "
            f"{item['marker_hits']} explanation marker(s))"
        )
        lines.append(f'  Gloss preview: "{item["gloss_preview"]}..."')
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# P5: Within-chapter repetition detection
# ------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of is was were are be been "
    "has had have with from by that this which it its he she his her "
    "they them their not as if than so do did does will would could "
    "should may might shall can into upon".split()
)


def detect_within_chapter_repetition(
    text: str,
    ngram_sizes: tuple[int, ...] = (3, 4, 5),
    min_occurrences: int = 3,
    min_ngram_content_words: int = 2,
) -> list[dict]:
    """Detect repeated n-grams and construction patterns within a chapter.

    Returns a list of dicts with keys:
      - ``pattern``: the repeated n-gram or construction
      - ``count``: number of occurrences
      - ``ngram_size``: size of the n-gram
    """
    words = re.findall(r"[a-z']+", text.lower())
    results: list[dict] = []
    seen_patterns: set[str] = set()

    for n in ngram_sizes:
        counter: Counter[tuple[str, ...]] = Counter()
        for i in range(len(words) - n + 1):
            gram = tuple(words[i : i + n])
            content_words = [w for w in gram if w not in _STOP_WORDS]
            if len(content_words) >= min_ngram_content_words:
                counter[gram] += 1

        for gram, count in counter.most_common():
            if count < min_occurrences:
                break
            pattern = " ".join(gram)
            if pattern not in seen_patterns and not _is_subgram(pattern, seen_patterns):
                seen_patterns.add(pattern)
                results.append({
                    "pattern": pattern,
                    "count": count,
                    "ngram_size": n,
                })

    construction_patterns = _detect_construction_patterns(text)
    for cp in construction_patterns:
        if cp["count"] >= min_occurrences:
            key = cp["pattern"]
            if key not in seen_patterns:
                seen_patterns.add(key)
                results.append(cp)

    results.sort(key=lambda x: x["count"], reverse=True)
    return results


def _detect_construction_patterns(text: str) -> list[dict]:
    """Detect repeated syntactic construction patterns like 'the [NOUN] of [X]'."""
    patterns_to_check = [
        (r"the weight of \w+", "the weight of [X]"),
        (r"\w+'s smile \w+", "[CHARACTER]'s smile [VERB]"),
        (r"sharp as \w+", "sharp as [X]"),
        (r"cold as \w+", "cold as [X]"),
        (r"like a \w+ (?:examining|studying|addressing|watching|observing) \w+",
         "like a [NOUN] [PERCEIVING] [OBJECT]"),
        (r"with (?:evident|practiced|unmistakable|barely concealed|deliberate) \w+",
         "with [ADJECTIVE] [NOUN] (formulaic qualifier)"),
        (r"the (?:sound|weight|force|burden|cost|price) of (?:his|her|the|their) \w+",
         "the [ABSTRACT-NOUN] of [POSSESSIVE] [X]"),
        (r"(?:struck|hit) (?:him|her|them|hartwell|walker) (?:like|with) ",
         "[VERB] [CHARACTER] like/with [X] (impact formula)"),
    ]

    results: list[dict] = []
    lower_text = text.lower()
    for regex, label in patterns_to_check:
        matches = re.findall(regex, lower_text)
        if len(matches) >= 2:
            results.append({
                "pattern": f"{label} — e.g. \"{matches[0]}\"",
                "count": len(matches),
                "ngram_size": 0,
            })
    return results


def _is_subgram(pattern: str, existing: set[str]) -> bool:
    """Check if a pattern is a substring of any existing pattern."""
    return any(pattern in e and pattern != e for e in existing)


def format_repetition_report(repetitions: list[dict]) -> str:
    """Format repetition findings into a directive string for the revision prompt."""
    if not repetitions:
        return ""

    lines = [
        "WITHIN-CHAPTER REPETITION REPORT:",
        "The following constructions appear multiple times in this chapter. "
        "You MUST replace all but one instance of each with structurally "
        "different alternatives. Do not simply swap synonyms — restructure "
        "the sentence entirely.",
        "",
    ]
    for r in repetitions[:15]:
        lines.append(f'- "{r["pattern"]}" — appears {r["count"]} times')

    return "\n".join(lines)


# ------------------------------------------------------------------
# P1: "the [noun] of a [person] who" syntactic signature
# ------------------------------------------------------------------

_NOUNY_WHO_RE = re.compile(
    r"\bthe\s+\w+\s+of\s+a\s+(?:man|woman|person|people|someone)\s+who\b",
    re.IGNORECASE,
)


def detect_nouny_who_pattern(text: str, max_per_chapter: int = 3) -> dict | None:
    """Detect overuse of 'the [noun] of a [person] who' constructions."""
    matches = list(_NOUNY_WHO_RE.finditer(text))
    if len(matches) <= max_per_chapter:
        return None

    instances = []
    for m in matches:
        line = text.count("\n", 0, m.start()) + 1
        snippet = text[max(0, m.start() - 40) : min(len(text), m.end() + 80)]
        snippet = re.sub(r"\s+", " ", snippet).strip()
        instances.append({"line": line, "snippet": snippet})

    return {
        "count": len(matches),
        "threshold": max_per_chapter,
        "instances": instances,
    }


def format_nouny_who_report(data: dict | None) -> str:
    """Format syntactic signature overuse for revision injection."""
    if not data:
        return ""

    lines = [
        "SYNTACTIC SIGNATURE ALERT:",
        "This chapter overuses 'the [quality] of a [person] who [clause]'. "
        "Rewrite at least 80% of these using different structures (direct action, "
        "simple statement, or different metaphor syntax).",
        f"- Instances: {data['count']} (threshold: {data['threshold']})",
        "",
    ]
    for item in data["instances"][:12]:
        lines.append(f'- Line ~{item["line"]}: "{item["snippet"]}..."')

    return "\n".join(lines)


# ------------------------------------------------------------------
# P2: Frequency outliers and vocabulary crutches
# ------------------------------------------------------------------

_COMMON_WORDS = _STOP_WORDS | frozenset(
    "i you we us me my mine your yours our ours this that these those "
    "who whom whose what when where why how there here then than very "
    "just only even still also into over under before after".split()
)

_WATCHLIST_WORDS = (
    "particular",
    "precisely",
    "deliberate",
    "deliberately",
    "calibrate",
    "calibrated",
    "instrument",
    "mechanism",
    "architecture",
    "commerce",
    "currency",
)

_WATCHLIST_PHRASES = (
    "which was",
    "arithmetic",
    "ledger",
    "calculation",
    "calculate",
    "calculated",
)


def detect_word_frequency_outliers(
    text: str,
    threshold_per_5000: float = 4.5,
    min_count: int = 3,
) -> dict:
    """Detect word and phrase frequency crutches in a chapter."""
    tokens = re.findall(r"[a-z']+", text.lower())
    total_words = len(tokens)
    if total_words == 0:
        return {"total_words": 0, "outlier_words": [], "watchlist_hits": []}

    max_allowed = max(min_count, int((threshold_per_5000 * total_words) / 5000))
    counts = Counter(
        t for t in tokens
        if len(t) > 3 and t not in _COMMON_WORDS
    )

    outlier_words = [
        {"term": word, "count": count}
        for word, count in counts.most_common()
        if count > max_allowed
    ]

    watchlist_hits: list[dict] = []
    for word in _WATCHLIST_WORDS:
        c = counts.get(word, 0)
        if c >= 2:
            watchlist_hits.append({"term": word, "count": c, "type": "word"})
    lower = text.lower()
    for phrase in _WATCHLIST_PHRASES:
        c = len(re.findall(rf"\b{re.escape(phrase)}\b", lower))
        if c >= 2:
            watchlist_hits.append({"term": phrase, "count": c, "type": "phrase"})

    return {
        "total_words": total_words,
        "threshold_count": max_allowed,
        "outlier_words": outlier_words,
        "watchlist_hits": sorted(
            watchlist_hits, key=lambda x: x["count"], reverse=True
        ),
    }


def format_word_frequency_report(data: dict) -> str:
    """Format frequency outlier findings for revision prompts."""
    outlier_words = data.get("outlier_words", [])
    watchlist_hits = data.get("watchlist_hits", [])
    if not outlier_words and not watchlist_hits:
        return ""

    lines = [
        "VOCABULARY CRUTCH ALERT:",
        "The chapter shows machine-like frequency spikes. Vary wording and "
        "remove repeated crutch terms.",
        f"- Chapter words: {data.get('total_words', 0)}",
        f"- Outlier threshold count: {data.get('threshold_count', 0)}",
        "",
    ]
    if outlier_words:
        lines.append("Outlier words:")
        for item in outlier_words[:12]:
            lines.append(f'- "{item["term"]}" ({item["count"]}x)')
        lines.append("")

    if watchlist_hits:
        lines.append("Watch-list hits:")
        for item in watchlist_hits[:12]:
            lines.append(f'- "{item["term"]}" ({item["count"]}x, {item["type"]})')
        lines.append("")
        lines.append(
            "Rewrite repeated watch-list terms and remove duplicate phrase stems."
        )

    return "\n".join(lines)


# ------------------------------------------------------------------
# P6: Essay-passage detection
# ------------------------------------------------------------------

_ABSTRACTION_WORDS = frozenset(
    "perhaps itself whether destiny legacy meaning question vision nation "
    "republic empire history future promise dream reality aspiration "
    "ambition consequence triumph tragedy cost price purpose truth "
    "humanity civilization progress idealism pragmatism power freedom "
    "justice fate providence democracy liberty sovereignty".split()
)


def detect_essay_passages(
    text: str,
    min_consecutive: int = 3,
    abstraction_threshold: float = 0.03,
) -> list[dict]:
    """Detect essay-like passages: consecutive paragraphs with no dialogue,
    no character action, and high abstraction density.

    Returns a list of dicts with keys:
      - ``start_para``, ``end_para``: 1-based paragraph range
      - ``paragraph_count``: number of consecutive essay paragraphs
      - ``preview``: first 100 chars of the passage
    """
    paragraphs = _split_paragraphs(text)
    scored: list[bool] = []

    for para in paragraphs:
        if len(para.split()) < 10:
            scored.append(False)
            continue

        has_dialogue = '"' in para or "\u201c" in para
        words = re.findall(r"[a-z]+", para.lower())
        if not words:
            scored.append(False)
            continue

        abstraction_density = sum(
            1 for w in words if w in _ABSTRACTION_WORDS
        ) / len(words)

        action_verbs = re.findall(
            r"\b(?:said|asked|demanded|shouted|whispered|grabbed|"
            r"pulled|pushed|struck|threw|ran|walked|turned|"
            r"closed|opened|drew|rose|sat|stood|reached|"
            r"took|put|set|picked|dropped|slammed|knocked)\b",
            para.lower(),
        )

        is_essay = (
            not has_dialogue
            and len(action_verbs) == 0
            and abstraction_density >= abstraction_threshold
        )
        scored.append(is_essay)

    results: list[dict] = []
    i = 0
    while i < len(scored):
        if scored[i]:
            start = i
            while i < len(scored) and scored[i]:
                i += 1
            length = i - start
            if length >= min_consecutive:
                passage = "\n\n".join(paragraphs[start:i])
                results.append({
                    "start_para": start + 1,
                    "end_para": i,
                    "paragraph_count": length,
                    "preview": passage[:120],
                })
        else:
            i += 1

    return results


def format_essay_report(essays: list[dict]) -> str:
    """Format essay-passage findings into a directive string for the revision prompt."""
    if not essays:
        return ""

    lines = [
        "ESSAY ALERT:",
        "The following passages contain no dialogue, no character action, "
        "and high abstraction density. They read as thematic essays, not "
        "fiction. You MUST convert this material into scene — the character "
        "should be DOING something while these thoughts occur, and the "
        "thoughts should be prompted by specific sensory triggers, not "
        "free-floating reflection. Cut any paragraph that restates an idea "
        "already established earlier in the chapter.",
        "",
    ]
    for e in essays:
        lines.append(
            f"- Paragraphs {e['start_para']}–{e['end_para']} "
            f"({e['paragraph_count']} consecutive abstract paragraphs):"
        )
        lines.append(f'  "{e["preview"]}..."')
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# P4: Sensory grounding deficit detection
# ------------------------------------------------------------------

_SENSORY_KEYWORDS = {
    "smell": (
        "smell", "scent", "odor", "odour", "stink", "fragrance", "reek", "musty",
    ),
    "taste": (
        "taste", "bitter", "sweet", "sour", "salt", "coffee", "wine", "metallic",
    ),
    "touch": (
        "cold", "warm", "hot", "rough", "smooth", "wet", "damp", "clammy",
        "wool", "fabric", "texture", "pressure", "weight", "ache",
    ),
    "sound": (
        "sound", "creak", "crack", "whisper", "murmur", "boots", "footsteps",
        "thud", "clang", "rustle", "drip", "rain", "wind", "bell",
    ),
}


def detect_sensory_deficit(
    text: str,
    min_nonvisual_refs_per_scene: int = 3,
    min_sense_categories_per_scene: int = 2,
) -> list[dict]:
    """Detect scenes lacking non-visual sensory grounding."""
    scenes = [
        s.strip() for s in re.split(r"\n\s*---\s*\n", text) if s.strip()
    ]
    deficits: list[dict] = []

    for idx, scene in enumerate(scenes, start=1):
        scene_lower = scene.lower()
        total_hits = 0
        category_hits: dict[str, int] = {}
        for category, words in _SENSORY_KEYWORDS.items():
            count = sum(
                len(re.findall(rf"\b{re.escape(word)}\b", scene_lower))
                for word in words
            )
            if count > 0:
                category_hits[category] = count
                total_hits += count

        if (
            total_hits < min_nonvisual_refs_per_scene
            or len(category_hits) < min_sense_categories_per_scene
        ):
            deficits.append({
                "scene_number": idx,
                "total_hits": total_hits,
                "categories": sorted(category_hits.keys()),
                "preview": re.sub(r"\s+", " ", scene[:180]).strip(),
            })

    return deficits


def format_sensory_deficit_report(deficits: list[dict]) -> str:
    """Format sensory deficit findings for revision prompts."""
    if not deficits:
        return ""

    lines = [
        "SENSORY DEFICIT ALERT:",
        "Some scenes are overly abstract and under-grounded in the physical world. "
        "Add period-appropriate non-visual sensory detail (smell, taste, touch, "
        "sound, physical sensation) without immediately interpreting it.",
        "",
    ]
    for d in deficits:
        cats = ", ".join(d["categories"]) if d["categories"] else "none"
        lines.append(
            f"- Scene {d['scene_number']}: {d['total_hits']} non-visual "
            f"references; categories: {cats}"
        )
        lines.append(f'  Preview: "{d["preview"]}..."')
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------
# P5: Cross-chapter ending similarity warning (generation-time)
# ------------------------------------------------------------------

_ENDING_MOTIF_KEYWORDS = (
    "quiet", "room", "alone", "solitary", "fire", "grate", "ember",
    "dark", "lamp", "reflection", "reflect", "silence", "dying",
)


def build_chapter_ending_warning(
    prior_chapter_texts: dict[int, str],
    ending_window_words: int = 500,
    min_keyword_hits_per_ending: int = 3,
    min_similar_endings: int = 2,
) -> str:
    """Build a warning string when prior chapter endings repeat motifs."""
    if len(prior_chapter_texts) < min_similar_endings:
        return ""

    flagged: list[dict] = []
    aggregate_hits: Counter[str] = Counter()

    for ch_num, chapter_text in sorted(prior_chapter_texts.items()):
        ending_words = re.findall(r"[a-z']+", chapter_text.lower())[-ending_window_words:]
        ending_text = " ".join(ending_words)
        hit_terms = [
            kw for kw in _ENDING_MOTIF_KEYWORDS
            if re.search(rf"\b{re.escape(kw)}\b", ending_text)
        ]
        if len(hit_terms) >= min_keyword_hits_per_ending:
            flagged.append({"chapter": ch_num, "terms": hit_terms})
            aggregate_hits.update(hit_terms)

    if len(flagged) < min_similar_endings:
        return ""

    common_terms = ", ".join(t for t, _ in aggregate_hits.most_common(6))
    chapter_list = ", ".join(str(f["chapter"]) for f in flagged)

    return (
        "WARNING: Prior chapter endings show repeated closing motifs "
        f"(chapters: {chapter_list}; recurring terms: {common_terms}). "
        "Do NOT end this chapter with the same quiet-room / solitary-reflection "
        "shape. End differently: in motion, mid-dialogue, in public, with an "
        "arrival, or on an unresolved external action."
    )


# ------------------------------------------------------------------
# P7: Rhythm and pacing monotony
# ------------------------------------------------------------------

def detect_rhythm_monotony(
    text: str,
    min_paragraphs: int = 6,
    min_sentences: int = 20,
    paragraph_cv_threshold: float = 0.45,
    short_sentence_ratio_threshold: float = 0.10,
) -> dict | None:
    """Detect monotony in paragraph/sentence length distribution."""
    paragraphs = _split_paragraphs(text)
    paragraph_lengths = [len(re.findall(r"[a-zA-Z']+", p)) for p in paragraphs if p]
    sentences = _split_sentences(text)
    sentence_lengths = [len(re.findall(r"[a-zA-Z']+", s)) for s in sentences if s]

    if len(paragraph_lengths) < min_paragraphs or len(sentence_lengths) < min_sentences:
        return None

    para_mean, para_std = _mean_std(paragraph_lengths)
    sent_mean, sent_std = _mean_std(sentence_lengths)
    para_cv = (para_std / para_mean) if para_mean else 0.0
    short_sentence_ratio = (
        sum(1 for n in sentence_lengths if n < 10) / len(sentence_lengths)
    )

    low_paragraph_variance = para_cv < paragraph_cv_threshold
    short_sentence_deficit = short_sentence_ratio < short_sentence_ratio_threshold

    if not low_paragraph_variance and not short_sentence_deficit:
        return None

    return {
        "paragraph_count": len(paragraph_lengths),
        "sentence_count": len(sentence_lengths),
        "paragraph_mean": round(para_mean, 2),
        "paragraph_cv": round(para_cv, 3),
        "sentence_mean": round(sent_mean, 2),
        "sentence_std": round(sent_std, 2),
        "short_sentence_ratio": round(short_sentence_ratio, 3),
        "low_paragraph_variance": low_paragraph_variance,
        "short_sentence_deficit": short_sentence_deficit,
    }


def format_rhythm_monotony_report(data: dict | None) -> str:
    """Format rhythm monotony findings for revision prompts."""
    if not data:
        return ""

    lines = [
        "RHYTHM MONOTONY ALERT:",
        "Paragraph/sentence cadence is too uniform. Vary pacing deliberately.",
        f"- Paragraph CV: {data['paragraph_cv']} (mean words: {data['paragraph_mean']})",
        f"- Short sentences (<10 words): {data['short_sentence_ratio']:.1%}",
    ]
    if data["low_paragraph_variance"]:
        lines.append(
            "- Paragraph lengths are too similar. Add short punchy paragraphs and "
            "let key beats breathe with varied lengths."
        )
    if data["short_sentence_deficit"]:
        lines.append(
            "- Too few short sentences. Introduce forceful short lines after dense passages."
        )
    return "\n".join(lines)


# ------------------------------------------------------------------
# P8: Narrator psychologizing detection
# ------------------------------------------------------------------

_PSYCHOLOGIZING_RE = re.compile(
    r"\b(?:he|she|they)\s+(?:"
    r"thought\s+that|suspected\s+that|realized\s+that|understood\s+that"
    r"|knew\s+that|felt\s+that|recognized\s+that"
    r"|was\s+not\s+(?:certain|sure)\s+(?:whether|if|about)"
    r"|could\s+not\s+help\s+but\s+(?:think|wonder|feel)"
    r"|had\s+begun\s+to\s+(?:suspect|realize|understand|wonder)"
    r")"
    r"|\bit\s+occurred\s+to\s+(?:him|her|them)\s+that"
    r"|\bhe\s+was\s+aware\s+that|\bshe\s+was\s+aware\s+that"
    r"|\bhe\s+wondered\s+whether|\bshe\s+wondered\s+whether",
    re.IGNORECASE,
)


def detect_narrator_psychologizing(
    text: str,
    max_per_1k_words: float = 5.0,
) -> list[dict]:
    """Detect scenes where the narrator over-explains character psychology.

    Flags scenes where interior-state verb clusters exceed the per-1k-word
    threshold, signalling that emotion should be externalized through gesture
    and action instead of narrator annotation.

    Returns a list of dicts for flagged scenes, each with:
      - ``scene_number``: 1-based scene index
      - ``match_count``: number of psychologizing pattern hits
      - ``word_count``: scene word count
      - ``density``: hits per 1k words
      - ``examples``: up to 3 matching snippets
    """
    scenes = _split_scenes(text)
    flagged: list[dict] = []

    for idx, scene in enumerate(scenes, start=1):
        word_count = len(re.findall(r"[a-zA-Z']+", scene))
        if word_count < 50:
            continue

        matches = list(_PSYCHOLOGIZING_RE.finditer(scene))
        match_count = len(matches)
        density = match_count / max(word_count / 1000.0, 1e-9)

        if density > max_per_1k_words:
            examples = []
            for m in matches[:3]:
                start = max(0, m.start() - 20)
                end = min(len(scene), m.end() + 60)
                snippet = re.sub(r"\s+", " ", scene[start:end]).strip()
                examples.append(snippet)
            flagged.append({
                "scene_number": idx,
                "match_count": match_count,
                "word_count": word_count,
                "density": round(density, 2),
                "examples": examples,
            })

    return flagged


def format_narrator_psychologizing_report(findings: list[dict]) -> str:
    """Format narrator psychologizing findings for revision prompts."""
    if not findings:
        return ""

    lines = [
        "NARRATOR PSYCHOLOGIZING ALERT:",
        "Some scenes rely on narrator interior-state announcements instead of "
        "externalizing emotion through physical gesture and action. Apply the "
        "EXTERNALIZATION RULE: when the narrator names what a character thinks, "
        "suspects, realizes, or feels, replace it with a concrete physical action "
        "that implies the same interior state without explaining it.",
        "",
    ]
    for item in findings[:6]:
        lines.append(
            f"- Scene {item['scene_number']}: {item['match_count']} psychologizing "
            f"patterns ({item['density']:.1f}/1k words)"
        )
        for ex in item["examples"]:
            lines.append(f'  e.g. "...{ex}..."')
        lines.append("")

    lines.append(
        "REWRITE GUIDE: Replace 'He suspected that X' with an action that implies "
        "suspicion (he pocketed the letter without opening it). Replace 'She was not "
        "certain whether...' with a gesture of hesitation (she set her pen down and "
        "did not pick it up). The reader infers — the narrator does not explain."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# P9: Dialogue naturalness / uniformity
# ------------------------------------------------------------------

_DIALOGUE_RE = re.compile(r"[\"“]([^\"”]{1,300})[\"”]")


def detect_dialogue_uniformity(
    text: str,
    avg_words_threshold: float = 30.0,
    short_line_ratio_threshold: float = 0.15,
    interruption_ratio_threshold: float = 0.08,
    trailing_ratio_threshold: float = 0.0,
    response_mismatch_ratio_threshold: float = 0.35,
) -> dict | None:
    """Detect overly polished dialogue with uniformly long lines and low fracture."""
    lines = [m.group(1).strip() for m in _DIALOGUE_RE.finditer(text)]
    if not lines:
        return None

    lengths = [len(re.findall(r"[a-zA-Z']+", line)) for line in lines if line]
    if not lengths:
        return None

    avg_words = sum(lengths) / len(lengths)
    short_ratio = sum(1 for n in lengths if n < 10) / len(lengths)
    interruption_ratio = (
        sum(1 for line in lines if "--" in line or "\u2014" in line) / len(lines)
    )
    trailing_ratio = (
        sum(1 for line in lines if line.endswith("...") or line.endswith("\u2026")) / len(lines)
    )
    response_mismatch_ratio = _estimate_response_mismatch_ratio(lines)

    if (
        avg_words <= avg_words_threshold
        and short_ratio >= short_line_ratio_threshold
        and interruption_ratio >= interruption_ratio_threshold
        and trailing_ratio >= trailing_ratio_threshold
        and response_mismatch_ratio >= response_mismatch_ratio_threshold
    ):
        return None

    return {
        "dialogue_line_count": len(lengths),
        "average_words_per_line": round(avg_words, 2),
        "short_line_ratio": round(short_ratio, 3),
        "interruption_ratio": round(interruption_ratio, 3),
        "trailing_ratio": round(trailing_ratio, 3),
        "response_mismatch_ratio": round(response_mismatch_ratio, 3),
    }


def format_dialogue_uniformity_report(data: dict | None) -> str:
    """Format dialogue uniformity findings for revision prompts."""
    if not data:
        return ""

    return "\n".join([
        "DIALOGUE UNIFORMITY ALERT:",
        "Dialogue reads over-composed and lacks fracture under pressure.",
        f"- Lines analysed: {data['dialogue_line_count']}",
        f"- Average words/line: {data['average_words_per_line']}",
        f"- Short lines (<10 words): {data['short_line_ratio']:.1%}",
        f"- Interruption ratio: {data['interruption_ratio']:.1%}",
        f"- Trailing/ellipsis ratio: {data['trailing_ratio']:.1%}",
        f"- Response mismatch ratio: {data['response_mismatch_ratio']:.1%}",
        "Revise so conflict exchanges include concise lines, interruptions, and evasive answers.",
    ])


# ------------------------------------------------------------------
# P9: Metaphor cluster saturation
# ------------------------------------------------------------------

_METAPHOR_FAMILY_PATTERNS = {
    "financial": (
        r"\barithmetic\b|\bledger\b|\bcalculat(?:e|ed|ing|ion|ions)\b|"
        r"\baccount(?:ing|ed)?\b|\bbalance\b|\bcosts?\b|\bcurrency\b|"
        r"\binvest(?:ment|ments|ed|ing)?\b|\bcapital\b|\breturns?\b|"
        r"\bprice\b|\bdiscount\b|\bcompound\b"
    ),
    "mechanical": (
        r"\binstrument\b|\bmachiner(?:y|ies)\b|\bmechanis(?:m|ms)\b|"
        r"\bcalibrat(?:e|ed|ing|ion)\b|\bprecision\b|\bapparatus\b|"
        r"\btools?\b|\bengineer(?:ing|ed|s)?\b"
    ),
    "military": (
        r"\bterrain\b|\bposition(?:s)?\b|\badvance(?:s|d)?\b|\bdeploy(?:ed|ment|s)?\b|"
        r"\bmaneuver(?:s|ed)?\b|\bflank(?:ed|ing)?\b|\bstrateg(?:y|ic)\b|\btactic(?:al|s)?\b"
    ),
}


def detect_metaphor_saturation(
    text: str,
    family_threshold: int = 6,
) -> list[dict]:
    """Detect overused metaphor families in a chapter."""
    lower = text.lower()
    findings: list[dict] = []
    for family, pattern in _METAPHOR_FAMILY_PATTERNS.items():
        count = len(re.findall(pattern, lower))
        if count > family_threshold:
            findings.append({"family": family, "count": count})
    findings.sort(key=lambda x: x["count"], reverse=True)
    return findings


def format_metaphor_saturation_report(findings: list[dict]) -> str:
    """Format metaphor saturation findings for revision prompts."""
    if not findings:
        return ""
    lines = [
        "METAPHOR SATURATION ALERT:",
        "One metaphor family is overused, flattening figurative texture.",
    ]
    for f in findings:
        lines.append(
            f"- {f['family'].title()} family appears {f['count']} times; reduce by at least half."
        )
    lines.append(
        "Replace repetitive domain language with alternatives appropriate to POV voice."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# P10-P17: Reader-compulsion detectors
# ------------------------------------------------------------------

_IMMEDIATE_RISK_MARKERS = re.compile(
    r"\b(?:now|immediately|before|tonight|this hour|at once|caught|exposed|ruin|"
    r"lose|arrest|collapse|destroy|dismiss|betray|threat|"
    # political/institutional risk markers
    r"recalled|censured|impeach|repudiat|overruled|revoked|"
    r"ratif(?:y|ication)|unconstitutional|dissent|defect(?:ion|ed)|"
    r"secession|secede|faction|splinter|resign|reprimand|"
    r"vote|majority|minority|quorum|deadline|commission|"
    r"inquiry|subpoena|deposition|scandal|leak|intercept|"
    # diplomatic/treaty risk markers
    r"treaty|alliance|cede|ceded|cession|annex|territory|sovereignty|"
    r"ultimatum|concession|leverage|negotiat|expire|capitulat|abandon|forfeit|"
    r"envoy|minister|ambassador|consul|"
    r"dispatch|courier|sailed|instruction|plenipotentiary)\b",
    re.IGNORECASE,
)
_CONSEQUENCE_VERBS = re.compile(
    r"\b(?:lose|forfeit|cost|shatter|break|exile|imprison|ruin|kill|damage|strip|"
    r"expose|disgrace|humiliate|undermine|fracture|split|collapse|fall|"
    r"condemn|abandon|wreck|destroy|burn|"
    # political/institutional consequence verbs
    r"recall|censure|impeach|repudiate|overrule|revoke|disavow|"
    r"expel|dismiss|demote|isolate|marginalise|marginalize|"
    r"discredit|outmanoeuvre|outmaneuver|betray|defect|"
    r"splinter|unseat|oust|block|veto|override|reject|"
    # diplomatic consequence verbs (infinitive and common past tense forms)
    r"sacrifice|sacrificed|concede|conceded|surrender|surrendered|"
    r"withdraw|withdrew|capitulate|capitulated|"
    r"cede|ceded|annex|annexed|relinquish|relinquished|"
    r"waive|waived|yield|yielded|"
    r"compromise|compromised|subordinate|subordinated|jeopardize|jeopardized)\b",
    re.IGNORECASE,
)
_CONSEQUENCE_OUTCOME_PATTERNS = re.compile(
    r"\b(?:if|unless)\b[^.]{0,140}\b(?:will|would|must|could)\b[^.]{0,140}\b"
    r"(?:lose|cost|ruin|collapse|fall|break|destroy|expose|disgrace|"
    r"imprison|kill|damage|forfeit|shatter|"
    r"recall|censure|repudiate|dismiss|discredit|isolate|oust|reject|veto|"
    r"sacrifice|sacrificed|concede|conceded|surrender|surrendered|"
    r"withdraw|withdrew|capitulate|capitulated|"
    r"cede|ceded|annex|annexed|relinquish|relinquished|"
    r"waive|waived|yield|yielded|compromise|compromised)\b",
    re.IGNORECASE,
)
_SURPRISE_MARKERS = re.compile(
    r"\b(?:suddenly|instead|however|but then|except|until|revealed|confessed|"
    r"betrayed|unexpected|to his surprise|to her surprise|reversal|turned out)\b",
    re.IGNORECASE,
)
_TACTICAL_COGNITION = re.compile(
    r"\b(?:calculated|weighed|considered|assessed|strategic|tactical|measured|"
    r"evaluated|inferred|concluded|positioned)\b",
    re.IGNORECASE,
)
_VULNERABILITY_MARKERS = re.compile(
    r"\b(?:flinched|stammered|voice broke|could not finish|ashamed|afraid|"
    r"wanted to|needed to|nearly|almost|mistook|misread|regretted)\b",
    re.IGNORECASE,
)
_OFFSTAGE_OPPOSITION = re.compile(
    r"\b(?:report|memo|letter|word came|it was said|rumor|rumour|dispatch|"
    r"heard that|was told)\b",
    re.IGNORECASE,
)
_ONSTAGE_CONFLICT = re.compile(
    r"\b(?:refused|denied|threatened|interrupted|accused|challenged|demanded|"
    r"ordered|slammed|struck|blocked|"
    # political/institutional on-page confrontation
    r"objected|protested|insisted|overruled|vetoed|countered|"
    r"rebuked|contradicted|dismissed|rejected|withdrew|"
    r"produced|presented|delivered|tabled|filed|invoked|"
    r"warned|cautioned|forbade|confronted|summoned|"
    # diplomatic/political action verbs
    r"proposed|offered|conceded|pressed|negotiated|"
    r"stipulated|amended|ratified|signed|sealed|"
    r"yielded|capitulated|acquiesced|relented|"
    r"calculated|maneuvered|manoeuvred|positioned|"
    r"declared|announced|proclaimed|asserted)\b",
    re.IGNORECASE,
)
_ENDING_PRESSURE = re.compile(
    r"\b(?:deadline|dawn|vote|warrant|summons|arrive|coming|before|by morning|"
    r"tonight|unless|or else|unresolved|still had to|"
    # political/diplomatic urgency markers
    r"ratification|dispatch|courier|sailed|sailing|session|"
    r"reconvene|tomorrow|within the hour|by the time|"
    r"inquiry|investigation|commission|delegation|"
    r"awaiting|pending|unanswered|unsigned)\b",
    re.IGNORECASE,
)


def detect_low_immediate_jeopardy(text: str) -> list[dict]:
    """Flag scenes that discuss stakes abstractly without immediate jeopardy."""
    findings: list[dict] = []
    for idx, scene in enumerate(_split_scenes(text), start=1):
        risk_hits = len(_IMMEDIATE_RISK_MARKERS.findall(scene))
        consequence_hits = len(_CONSEQUENCE_VERBS.findall(scene))
        consequence_hits += len(_CONSEQUENCE_OUTCOME_PATTERNS.findall(scene))
        if risk_hits == 0 or consequence_hits == 0:
            findings.append({
                "scene_number": idx,
                "risk_hits": risk_hits,
                "consequence_hits": consequence_hits,
                "preview": re.sub(r"\s+", " ", scene[:180]).strip(),
            })
    return findings


def format_immediate_jeopardy_report(findings: list[dict]) -> str:
    if not findings:
        return ""
    lines = [
        "IMMEDIATE JEOPARDY DEFICIT:",
        "Some scenes lack concrete now-level risk or irreversible consequence language.",
        "Inject a jeopardy beat before scene midpoint and make the failure cost explicit.",
        "",
    ]
    for item in findings[:8]:
        lines.append(
            f"- Scene {item['scene_number']}: risk markers={item['risk_hits']}, "
            f"consequence verbs={item['consequence_hits']}"
        )
        lines.append(f'  Preview: "{item["preview"]}..."')
    return "\n".join(lines)


def detect_low_surprise_density(text: str) -> dict | None:
    """Flag chapters with insufficient reveal/reversal signals."""
    scenes = _split_scenes(text)
    if not scenes:
        return None
    scene_hits = [len(_SURPRISE_MARKERS.findall(scene)) for scene in scenes]
    scenes_with_surprise = sum(1 for hits in scene_hits if hits > 0)
    total_hits = sum(scene_hits)
    cut_idx = int(len(text) * 0.65)
    early_hits = len(_SURPRISE_MARKERS.findall(text[:cut_idx]))
    if total_hits >= 4 and scenes_with_surprise >= 2 and early_hits >= 1:
        return None
    return {
        "total_surprise_markers": total_hits,
        "scenes_with_surprise": scenes_with_surprise,
        "scene_count": len(scenes),
        "markers_before_65pct": early_hits,
    }


def format_surprise_density_report(data: dict | None) -> str:
    if not data:
        return ""
    return "\n".join([
        "SURPRISE DENSITY DEFICIT:",
        f"- Surprise markers: {data['total_surprise_markers']} across "
        f"{data['scene_count']} scenes",
        f"- Scenes with surprise: {data['scenes_with_surprise']}",
        f"- Surprise markers before 65% chapter mark: {data['markers_before_65pct']}",
        "Add at least one hard reveal and one soft reversal, with one non-trivial development before 65%.",
    ])


def detect_emotional_control_monotony(text: str, min_paragraph_run: int = 3) -> list[dict]:
    """Flag stretches dominated by tactical cognition without vulnerable leakage."""
    paragraphs = _split_paragraphs(text)
    flags: list[bool] = []
    for para in paragraphs:
        tactical = len(_TACTICAL_COGNITION.findall(para))
        vulnerable = len(_VULNERABILITY_MARKERS.findall(para))
        flags.append(tactical >= 2 and vulnerable == 0)

    findings: list[dict] = []
    i = 0
    while i < len(flags):
        if flags[i]:
            start = i
            while i < len(flags) and flags[i]:
                i += 1
            run = i - start
            if run >= min_paragraph_run:
                findings.append({
                    "start_para": start + 1,
                    "end_para": i,
                    "run_length": run,
                })
        else:
            i += 1
    return findings


def format_emotional_control_report(findings: list[dict]) -> str:
    if not findings:
        return ""
    lines = [
        "EMOTIONAL CONTROL MONOTONY:",
        "Long tactical-cognition runs appear without involuntary emotional leakage.",
        "Insert at least one unguarded reaction aligned with POV blind spots.",
    ]
    for item in findings[:6]:
        lines.append(
            f"- Paragraphs {item['start_para']}-{item['end_para']} "
            f"({item['run_length']} tactical paragraphs)"
        )
    return "\n".join(lines)


def detect_offstage_opposition_overuse(text: str) -> dict | None:
    """Compare offstage antagonism mentions against on-page adversarial action."""
    offstage = len(_OFFSTAGE_OPPOSITION.findall(text))
    onstage = len(_ONSTAGE_CONFLICT.findall(text))
    if offstage <= max(5, onstage * 3):
        return None
    return {"offstage_mentions": offstage, "onstage_conflict_markers": onstage}


def format_offstage_opposition_report(data: dict | None) -> str:
    if not data:
        return ""
    return "\n".join([
        "OFFSTAGE OPPOSITION OVERUSE:",
        f"- Offstage opposition markers: {data['offstage_mentions']}",
        f"- On-page conflict markers: {data['onstage_conflict_markers']}",
        "Convert reported antagonism into direct adversarial collisions on-page.",
    ])


def detect_low_propulsion_endings(text: str, ending_window_words: int = 250) -> dict | None:
    """Check whether the final chunk sustains unresolved external pressure."""
    ending_words = re.findall(r"[a-z']+", text.lower())[-ending_window_words:]
    if not ending_words:
        return None
    ending_text = " ".join(ending_words)
    pressure_hits = len(_ENDING_PRESSURE.findall(ending_text))
    reflection_hits = len(re.findall(r"\b(?:thought|wondered|reflected|remembered|alone|quiet)\b", ending_text))
    if pressure_hits >= 2 and reflection_hits <= 5:
        return None
    return {
        "ending_window_words": ending_window_words,
        "external_pressure_hits": pressure_hits,
        "reflection_hits": reflection_hits,
    }


def format_low_propulsion_endings_report(data: dict | None) -> str:
    if not data:
        return ""
    return "\n".join([
        "ENDING PROPULSION DEFICIT:",
        f"- External pressure hits (last {data['ending_window_words']} words): "
        f"{data['external_pressure_hits']}",
        f"- Reflective deceleration hits: {data['reflection_hits']}",
        "Rewrite ending to preserve unresolved external pressure and forward drag.",
    ])


def detect_exposition_drag(text: str, min_consecutive: int = 2) -> list[dict]:
    """Detect long exposition runs with low dialogue/action progression.

    Returns a list of dicts with keys:
      - ``start_para``: 1-based paragraph number where the drag run starts
      - ``end_para``: 1-based paragraph number where the run ends (inclusive)
      - ``paragraph_count``: number of consecutive exposition paragraphs
      - ``preview``: first 150 chars of the dragging block (for targeted retry prompts)
    """
    paragraphs = _split_paragraphs(text)
    expository_flags: list[bool] = []
    for para in paragraphs:
        words = re.findall(r"[a-z]+", para.lower())
        if not words:
            expository_flags.append(False)
            continue
        abstraction_density = sum(1 for w in words if w in _ABSTRACTION_WORDS) / len(words)
        has_dialogue = '"' in para or "\u201c" in para
        action_hits = len(_ONSTAGE_CONFLICT.findall(para))
        expository_flags.append(abstraction_density >= 0.025 and not has_dialogue and action_hits == 0)

    results: list[dict] = []
    i = 0
    while i < len(expository_flags):
        if expository_flags[i]:
            start = i
            while i < len(expository_flags) and expository_flags[i]:
                i += 1
            run = i - start
            if run >= min_consecutive:
                drag_text = "\n\n".join(paragraphs[start:i])
                results.append({
                    "start_para": start + 1,
                    "end_para": i,
                    "paragraph_count": run,
                    "preview": drag_text[:150],
                })
        else:
            i += 1
    return results


def format_exposition_drag_report(findings: list[dict]) -> str:
    if not findings:
        return ""
    lines = [
        "EXPOSITION DRAG ALERT:",
        "Consecutive abstract exposition blocks are suppressing momentum.",
        "MANDATORY REWRITE MACRO: convert each flagged run into scene conflict using the sequence",
        "ask -> deny -> threaten (or pressure) -> concede/countermove. Keep policy information,",
        "but deliver it through action and adversarial exchange instead of exposition blocks.",
    ]
    for item in findings[:8]:
        lines.append(
            f"- Paragraphs {item['start_para']}-{item['end_para']} "
            f"({item['paragraph_count']} consecutive exposition-heavy paragraphs)"
        )
        preview = item.get("preview", "")
        if preview:
            lines.append(f'  Starts with: "{preview[:100].strip()}..."')
    return "\n".join(lines)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs (non-empty, stripped)."""
    raw = re.split(r"\n\s*\n", text)
    return [p.strip() for p in raw if p.strip() and p.strip() != "---"]


def _split_scenes(text: str) -> list[str]:
    """Split text by markdown horizontal-rule scene breaks."""
    raw_scenes = [s.strip() for s in re.split(r"\n\s*---\s*\n", text) if s.strip()]
    scenes: list[str] = []
    for scene in raw_scenes:
        words = re.findall(r"[a-zA-Z']+", scene)
        # Ignore heading-only blocks like '# Chapter X: ...' that are not real scenes.
        if len(words) <= 12 and re.fullmatch(
            r"(?:#+\s*chapter[^\n]*\s*)+",
            scene.lower(),
            flags=re.IGNORECASE,
        ):
            continue
        scenes.append(scene)
    return scenes or [text.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split prose into rough sentence units."""
    chunks = re.split(r"(?<=[.!?])\s+(?=[\"“A-Z])", text.strip())
    return [c.strip() for c in chunks if c.strip()]


def _is_dramatic_moment(sentence: str, short_line_words: int) -> bool:
    """Heuristic for short loaded dialogue lines or weighted gestures/silences."""
    short_dialogue = False
    quote_match = re.search(r"[\"“”](.+?)[\"“”]", sentence)
    if quote_match:
        dialogue_words = re.findall(r"[a-zA-Z']+", quote_match.group(1))
        short_dialogue = 0 < len(dialogue_words) <= short_line_words

    gesture_or_silence = bool(_MOMENT_MARKERS_RE.search(sentence))
    return short_dialogue or gesture_or_silence


def _mean_std(values: list[int]) -> tuple[float, float]:
    """Return arithmetic mean and population standard deviation."""
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, sqrt(var)


def _estimate_response_mismatch_ratio(lines: list[str]) -> float:
    """Approximate evasive/mismatched responses in adjacent dialogue lines."""
    if len(lines) < 2:
        return 0.0
    mismatch = 0
    question_count = 0
    for idx in range(len(lines) - 1):
        question = lines[idx]
        answer = lines[idx + 1]
        if "?" not in question:
            continue
        question_count += 1
        q_words = {
            w for w in re.findall(r"[a-z']+", question.lower())
            if w not in _STOP_WORDS and len(w) > 2
        }
        a_words = {
            w for w in re.findall(r"[a-z']+", answer.lower())
            if w not in _STOP_WORDS and len(w) > 2
        }
        overlap = len(q_words & a_words)
        if overlap == 0:
            mismatch += 1
    if question_count == 0:
        return 0.0
    return mismatch / question_count


def run_all_quality_checks(text: str) -> dict[str, str]:
    """Run all quality checks and return a dict of non-empty report strings.

    Keys include: ``duplicates``, ``over_explanation``, ``nouny_who``,
    ``frequency_outliers``, ``repetition``, ``sensory_deficit``, ``essays``,
    ``rhythm_monotony``, ``dialogue_uniformity``, ``metaphor_saturation``
    """
    reports: dict[str, str] = {}

    dupes = detect_duplicate_passages(text)
    if dupes:
        reports["duplicates"] = format_duplicate_report(dupes)

    overexpl = detect_over_explanation(text)
    if overexpl:
        reports["over_explanation"] = format_over_explanation_report(overexpl)

    nouny_who = detect_nouny_who_pattern(text)
    nouny_report = format_nouny_who_report(nouny_who)
    if nouny_report:
        reports["nouny_who"] = nouny_report

    freq = detect_word_frequency_outliers(text)
    freq_report = format_word_frequency_report(freq)
    if freq_report:
        reports["frequency_outliers"] = freq_report

    reps = detect_within_chapter_repetition(text)
    if reps:
        reports["repetition"] = format_repetition_report(reps)

    sensory = detect_sensory_deficit(text)
    if sensory:
        reports["sensory_deficit"] = format_sensory_deficit_report(sensory)

    essays = detect_essay_passages(text)
    if essays:
        reports["essays"] = format_essay_report(essays)

    rhythm = detect_rhythm_monotony(text)
    rhythm_report = format_rhythm_monotony_report(rhythm)
    if rhythm_report:
        reports["rhythm_monotony"] = rhythm_report

    psychologizing = detect_narrator_psychologizing(text)
    psychologizing_report = format_narrator_psychologizing_report(psychologizing)
    if psychologizing_report:
        reports["narrator_psychologizing"] = psychologizing_report

    dialogue = detect_dialogue_uniformity(text)
    dialogue_report = format_dialogue_uniformity_report(dialogue)
    if dialogue_report:
        reports["dialogue_uniformity"] = dialogue_report

    metaphor = detect_metaphor_saturation(text)
    metaphor_report = format_metaphor_saturation_report(metaphor)
    if metaphor_report:
        reports["metaphor_saturation"] = metaphor_report

    jeopardy = detect_low_immediate_jeopardy(text)
    jeopardy_report = format_immediate_jeopardy_report(jeopardy)
    if jeopardy_report:
        reports["immediate_jeopardy"] = jeopardy_report

    surprise = detect_low_surprise_density(text)
    surprise_report = format_surprise_density_report(surprise)
    if surprise_report:
        reports["surprise_density"] = surprise_report

    emotional_control = detect_emotional_control_monotony(text)
    emotional_control_report = format_emotional_control_report(emotional_control)
    if emotional_control_report:
        reports["emotional_control_monotony"] = emotional_control_report

    opposition = detect_offstage_opposition_overuse(text)
    opposition_report = format_offstage_opposition_report(opposition)
    if opposition_report:
        reports["offstage_opposition"] = opposition_report

    ending_propulsion = detect_low_propulsion_endings(text)
    ending_propulsion_report = format_low_propulsion_endings_report(ending_propulsion)
    if ending_propulsion_report:
        reports["ending_propulsion"] = ending_propulsion_report

    exposition_drag = detect_exposition_drag(text)
    exposition_drag_report = format_exposition_drag_report(exposition_drag)
    if exposition_drag_report:
        reports["exposition_drag"] = exposition_drag_report

    return reports


def build_quality_snapshot(text: str) -> dict:
    """Build a structured quality snapshot with raw findings and normalized metrics.

    This is used for persistent per-chapter quality artifacts so quality trends
    can be compared across runs without re-parsing chapter files ad hoc.
    """
    word_count = len(text.split())
    denom_1k = max(word_count / 1000.0, 1e-9)
    denom_10k = max(word_count / 10000.0, 1e-9)

    duplicates = detect_duplicate_passages(text)
    over_explanation = detect_over_explanation(text)
    nouny_who = detect_nouny_who_pattern(text)
    frequency_outliers = detect_word_frequency_outliers(text)
    repetition = detect_within_chapter_repetition(text)
    sensory_deficit = detect_sensory_deficit(text)
    essays = detect_essay_passages(text)
    rhythm_monotony = detect_rhythm_monotony(text)
    narrator_psychologizing = detect_narrator_psychologizing(text)
    dialogue_uniformity = detect_dialogue_uniformity(text)
    metaphor_saturation = detect_metaphor_saturation(text)

    immediate_jeopardy = detect_low_immediate_jeopardy(text)
    surprise_density = detect_low_surprise_density(text)
    emotional_control_monotony = detect_emotional_control_monotony(text)
    offstage_opposition = detect_offstage_opposition_overuse(text)
    ending_propulsion = detect_low_propulsion_endings(text)
    exposition_drag = detect_exposition_drag(text)

    counts = {
        "duplicates": len(duplicates),
        "over_explanation": len(over_explanation),
        "nouny_who_instances": nouny_who["count"] if nouny_who else 0,
        "frequency_outlier_terms": len(frequency_outliers.get("outlier_words", [])),
        "frequency_watchlist_hits": len(frequency_outliers.get("watchlist_hits", [])),
        "repetition_patterns": len(repetition),
        "sensory_deficit_scenes": len(sensory_deficit),
        "essay_passages": len(essays),
        "narrator_psychologizing_flag": int(len(narrator_psychologizing) > 0),
        "dialogue_uniformity_flag": int(dialogue_uniformity is not None),
        "metaphor_saturated_families": len(metaphor_saturation),
        "immediate_jeopardy_deficit_scenes": len(immediate_jeopardy),
        "surprise_density_deficit_flag": int(surprise_density is not None),
        "emotional_control_monotony_runs": len(emotional_control_monotony),
        "offstage_opposition_overuse_flag": int(offstage_opposition is not None),
        "ending_propulsion_deficit_flag": int(ending_propulsion is not None),
        "exposition_drag_runs": len(exposition_drag),
        "rhythm_monotony_flag": int(rhythm_monotony is not None),
    }

    normalized = {
        "duplicates_per_10k_words": round(counts["duplicates"] / denom_10k, 4),
        "repetition_patterns_per_10k_words": round(
            counts["repetition_patterns"] / denom_10k, 4
        ),
        "immediate_jeopardy_deficit_scenes_per_10k_words": round(
            counts["immediate_jeopardy_deficit_scenes"] / denom_10k, 4
        ),
        "exposition_drag_runs_per_10k_words": round(
            counts["exposition_drag_runs"] / denom_10k, 4
        ),
        "sensory_deficit_scenes_per_10k_words": round(
            counts["sensory_deficit_scenes"] / denom_10k, 4
        ),
        "over_explanation_per_1k_words": round(
            counts["over_explanation"] / denom_1k, 4
        ),
        "nouny_who_instances_per_10k_words": round(
            counts["nouny_who_instances"] / denom_10k, 4
        ),
    }

    return {
        "word_count": word_count,
        "counts": counts,
        "normalized": normalized,
        "raw": {
            "duplicates": duplicates,
            "over_explanation": over_explanation,
            "nouny_who": nouny_who,
            "frequency_outliers": frequency_outliers,
            "repetition": repetition,
            "sensory_deficit": sensory_deficit,
            "essays": essays,
            "rhythm_monotony": rhythm_monotony,
            "narrator_psychologizing": narrator_psychologizing,
            "dialogue_uniformity": dialogue_uniformity,
            "metaphor_saturation": metaphor_saturation,
            "immediate_jeopardy": immediate_jeopardy,
            "surprise_density": surprise_density,
            "emotional_control_monotony": emotional_control_monotony,
            "offstage_opposition": offstage_opposition,
            "ending_propulsion": ending_propulsion,
            "exposition_drag": exposition_drag,
        },
    }


# ------------------------------------------------------------------
# Inter-pass quality delta tracking
# ------------------------------------------------------------------

def compute_quality_delta(
    before_text: str,
    after_text: str,
    tracked_metrics: tuple[str, ...] = (
        "repetition_patterns",
        "exposition_drag_runs",
        "immediate_jeopardy_deficit_scenes",
        "metaphor_saturated_families",
        "nouny_who_instances",
        "frequency_outlier_terms",
        "over_explanation",
        "sensory_deficit_scenes",
    ),
) -> dict:
    """Compare quality snapshots before and after a revision pass.

    Returns a dict with keys:
      - ``regressions``: list of dicts for metrics that got worse
      - ``improvements``: list of dicts for metrics that got better
      - ``has_regressions``: bool
      - ``before_snapshot``: full snapshot before
      - ``after_snapshot``: full snapshot after
    """
    before_snapshot = build_quality_snapshot(before_text)
    after_snapshot = build_quality_snapshot(after_text)
    before_counts = before_snapshot.get("counts", {})
    after_counts = after_snapshot.get("counts", {})

    regressions: list[dict] = []
    improvements: list[dict] = []

    for metric in tracked_metrics:
        before_val = before_counts.get(metric, 0)
        after_val = after_counts.get(metric, 0)
        delta = after_val - before_val
        if delta > 0:
            regressions.append({
                "metric": metric,
                "before": before_val,
                "after": after_val,
                "delta": delta,
            })
        elif delta < 0:
            improvements.append({
                "metric": metric,
                "before": before_val,
                "after": after_val,
                "delta": delta,
            })

    return {
        "regressions": regressions,
        "improvements": improvements,
        "has_regressions": len(regressions) > 0,
        "before_snapshot": before_snapshot,
        "after_snapshot": after_snapshot,
    }


def format_regression_report(delta: dict, pass_name: str) -> str:
    """Format quality regressions into a directive string for the next revision pass."""
    regressions = delta.get("regressions", [])
    if not regressions:
        return ""

    lines = [
        f"## REGRESSION WARNING — Issues Introduced by {pass_name} Pass",
        "",
        f"The {pass_name} revision pass WORSENED the following quality metrics. "
        "You MUST avoid introducing these same problems. Where possible, fix "
        "the regressions without reintroducing the issues the previous pass corrected.",
        "",
    ]
    for r in regressions:
        metric_label = r["metric"].replace("_", " ").title()
        lines.append(
            f"- **{metric_label}**: increased from {r['before']} to "
            f"{r['after']} (+{r['delta']})"
        )

    repetition_regressed = any(
        r["metric"] == "repetition_patterns" for r in regressions
    )
    if repetition_regressed:
        after_snapshot = delta.get("after_snapshot", {})
        raw_reps = after_snapshot.get("raw", {}).get("repetition", [])
        if raw_reps:
            lines.append("")
            lines.append("**New repetition patterns to eliminate:**")
            for rep in raw_reps[:10]:
                lines.append(f'- "{rep["pattern"]}" ({rep["count"]}x)')

    lines.append("")
    lines.append(
        "Do NOT add new instances of these patterns. If you see them in "
        "the current draft, eliminate them."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Phase 5: Voice differentiation — register uniformity check
# ------------------------------------------------------------------

_REGISTER_DICTION_FAMILIES: dict[str, tuple[str, ...]] = {
    "architectural": ("arch", "column", "vault", "facade", "portico", "elevation",
                      "foundation", "structure", "proportion", "symmetry", "chamber"),
    "botanical": ("root", "branch", "leaf", "soil", "cultivate", "harvest", "season",
                  "soil", "growth", "decay", "flora", "vine", "graft"),
    "latinate": ("pursuant", "wherein", "henceforth", "aforesaid", "herein",
                 "cognizant", "adumbrate", "promulgation", "aforementioned"),
    "legal": ("statute", "provision", "clause", "treaty", "jurisdiction",
              "precedent", "instrument", "ratif", "sovereign", "title", "warrant"),
    "commercial": ("trade", "cargo", "duty", "tariff", "ship", "cargo", "port",
                   "merchant", "credit", "debt", "currency", "exchange"),
    "numerical": ("figure", "sum", "total", "count", "number", "tally", "estimate",
                  "budget", "account", "balance", "column", "ledger"),
    "bureaucratic": ("requisition", "register", "file", "report", "memo", "dispatch",
                     "circular", "minutes", "committee", "commission", "procedure"),
    "military": ("flank", "position", "advance", "retreat", "terrain", "campaign",
                 "deploy", "garrison", "fortif", "artillery", "siege"),
    "naturalist": ("light", "shadow", "air", "wind", "stone", "water", "bird",
                   "sky", "cloud", "earth", "temperature", "damp", "clay"),
    "financial": ("arithmetic", "ledger", "calculation", "invest", "return",
                  "capital", "revenue", "expenditure", "cost", "price"),
    "ironic": ("naturally", "of course", "no doubt", "presumably", "one supposes",
               "evidently", "as it happened", "curiously"),
}


def detect_register_uniformity(
    scene_text: str,
    narrative_register: dict[str, str],
) -> dict | None:
    """Check whether scene prose reflects the declared narrative_register.

    Examines sentence length patterns (rhythm) and diction family keyword
    presence. Returns a findings dict if the prose appears generic relative
    to the declared register, or None if the register is plausibly realized.

    This is a soft contract check — it flags potential uniformity, not
    absolute failure, so the threshold is deliberately lenient.
    """
    if not narrative_register:
        return None

    lower = scene_text.lower()
    sentences = _split_sentences(scene_text)
    sentence_lengths = [len(re.findall(r"[a-zA-Z']+", s)) for s in sentences if s]

    failures: list[str] = []

    # Check rhythm signal from sentence_rhythm key
    sentence_rhythm = narrative_register.get("sentence_rhythm", "").lower()
    if sentence_lengths and sentence_rhythm:
        avg_len = sum(sentence_lengths) / len(sentence_lengths)
        if "short" in sentence_rhythm or "clipped" in sentence_rhythm or "declarative" in sentence_rhythm:
            if avg_len > 25:
                failures.append(
                    f"sentence_rhythm declares '{sentence_rhythm}' but avg sentence "
                    f"length is {avg_len:.1f} words — prose reads too long for this register"
                )
        elif "long" in sentence_rhythm or "periodic" in sentence_rhythm or "subordinat" in sentence_rhythm:
            if avg_len < 15 and len(sentence_lengths) >= 5:
                failures.append(
                    f"sentence_rhythm declares '{sentence_rhythm}' but avg sentence "
                    f"length is only {avg_len:.1f} words — prose reads too clipped for this register"
                )

    # Check diction family from diction_family key
    diction_family_str = narrative_register.get("diction_family", "").lower()
    if diction_family_str:
        # Extract recognized family names from the declared string
        matched_families: list[str] = []
        total_hits = 0
        for family_name, keywords in _REGISTER_DICTION_FAMILIES.items():
            if family_name in diction_family_str:
                hits = sum(
                    len(re.findall(rf"\b{re.escape(kw)}\b", lower))
                    for kw in keywords
                )
                if hits > 0:
                    matched_families.append(family_name)
                    total_hits += hits

        if diction_family_str and total_hits == 0 and len(sentence_lengths) > 10:
            # Only flag if we recognized at least one family name in our lookup table
            recognized = [f for f in _REGISTER_DICTION_FAMILIES if f in diction_family_str]
            if recognized:
                failures.append(
                    f"diction_family declares '{diction_family_str}' but no keywords "
                    f"from the {recognized[0]} domain found in scene prose — "
                    "narrative register may be too generic for this POV"
                )

    if not failures:
        return None

    return {
        "failures": failures,
        "declared_sentence_rhythm": narrative_register.get("sentence_rhythm", ""),
        "declared_diction_family": narrative_register.get("diction_family", ""),
    }


# ------------------------------------------------------------------
# Phase 5: Physical interruption — symbolic rationalization detector
# ------------------------------------------------------------------

_RATIONALIZATION_PATTERNS = re.compile(
    r"\b(?:as\s+if|like\s+the|a\s+reminder\s+that|seemed\s+to\s+echo|"
    r"seemed\s+to\s+mirror|not\s+unlike|as\s+though|in\s+the\s+way\s+that|"
    r"which\s+was\s+itself|which\s+was\s+a\s+kind\s+of|"
    r"the\s+weight\s+of|the\s+burden\s+of|the\s+cost\s+of|"
    r"it\s+occurred\s+to\s+him\s+that|it\s+occurred\s+to\s+her\s+that|"
    r"he\s+realized\s+that|she\s+realized\s+that|"
    r"he\s+thought\s+of|she\s+thought\s+of|"
    r"which\s+seemed\s+to\s+(?:speak|say|mean|suggest|represent|embody|capture))\b",
    re.IGNORECASE,
)


def detect_symbolic_rationalization(
    scene_text: str,
    interruption_text: str,
    window_sentences: int = 4,
) -> dict | None:
    """Detect whether a physical interruption was immediately turned into metaphor.

    Locates the interruption in the scene text via keyword matching, then
    scans the following ``window_sentences`` sentences for rationalization
    language that converts the physical interruption into symbolic meaning.

    Returns a findings dict if rationalization is detected, None if the
    interruption is left as irreducible texture.
    """
    if not interruption_text.strip():
        return None

    interruption_keywords = [
        w for w in re.findall(r"[a-z']+", interruption_text.lower())
        if w not in _STOP_WORDS and len(w) > 3
    ]
    if not interruption_keywords:
        return None

    sentences = _split_sentences(scene_text)
    lower_scene = scene_text.lower()

    # Find the sentence where the interruption occurs
    interruption_sentence_idx: int | None = None
    for idx, sent in enumerate(sentences):
        sent_lower = sent.lower()
        matches = sum(1 for kw in interruption_keywords if kw in sent_lower)
        if matches >= max(1, len(interruption_keywords) // 2):
            interruption_sentence_idx = idx
            break

    if interruption_sentence_idx is None:
        # Interruption not found in prose — that's a missing-content failure
        # but not a rationalization failure; report as not rationalized
        return None

    # Scan from the interruption sentence INCLUSIVE through the window after it,
    # because rationalization often appears in the same clause or the sentence
    # immediately following.
    window = sentences[
        interruption_sentence_idx : interruption_sentence_idx + 1 + window_sentences
    ]
    window_text = " ".join(window)
    rationalization_hits = list(_RATIONALIZATION_PATTERNS.finditer(window_text))

    if not rationalization_hits:
        return None

    examples = []
    for m in rationalization_hits[:3]:
        start = max(0, m.start() - 20)
        end = min(len(window_text), m.end() + 60)
        examples.append(re.sub(r"\s+", " ", window_text[start:end]).strip())

    return {
        "interruption_text": interruption_text[:80],
        "rationalization_hit_count": len(rationalization_hits),
        "examples": examples,
    }


# ------------------------------------------------------------------
# Phase 5: Pettiness rationalization detector + chapter contract check
# ------------------------------------------------------------------

_PETTINESS_RATIONALIZATION_RE = re.compile(
    r"\b(?:but\s+he\s+knew|but\s+she\s+knew|but\s+of\s+course|"
    r"it\s+was,?\s+of\s+course|the\s+strategic|he\s+reminded\s+himself|"
    r"she\s+reminded\s+herself|which\s+served|a\s+necessary|"
    r"after\s+all,?\s+it|this\s+was\s+(?:merely|only|just)|"
    r"he\s+caught\s+himself|she\s+caught\s+herself|"
    r"he\s+dismissed\s+the|she\s+dismissed\s+the|"
    r"he\s+was\s+(?:not|too)\s+(?:proud|vain|petty)|"
    r"she\s+was\s+(?:not|too)\s+(?:proud|vain|petty)|"
    r"it\s+did\s+not\s+(?:matter|serve|help)|"
    r"(?:more\s+important|there\s+were\s+larger)\s+(?:matters|concerns|things))\b",
    re.IGNORECASE,
)


def detect_pettiness_rationalization(
    text: str,
    petty_moment_text: str,
    window_sentences: int = 5,
) -> dict | None:
    """Detect whether a petty moment is immediately rationalized or redeemed.

    Locates the petty moment in the chapter text via keyword matching, then
    scans the following ``window_sentences`` sentences for rationalization
    patterns that explain away the pettiness as strategic, redirect to
    something nobler, or have the character dismiss/correct themselves.

    Returns findings dict if rationalization detected, None if pettiness
    is left unresolved.
    """
    if not petty_moment_text.strip():
        return None

    petty_keywords = [
        w for w in re.findall(r"[a-z']+", petty_moment_text.lower())
        if w not in _STOP_WORDS and len(w) > 3
    ]
    if not petty_keywords:
        return None

    sentences = _split_sentences(text)

    # Find the sentence containing the petty moment
    petty_sentence_idx: int | None = None
    for idx, sent in enumerate(sentences):
        sent_lower = sent.lower()
        matches = sum(1 for kw in petty_keywords if kw in sent_lower)
        if matches >= max(1, len(petty_keywords) // 3):
            petty_sentence_idx = idx
            break

    if petty_sentence_idx is None:
        return None

    # Include the petty-moment sentence itself because rationalization often
    # appears in the same clause ("...pleased him briefly before he reminded himself")
    window = sentences[
        petty_sentence_idx : petty_sentence_idx + 1 + window_sentences
    ]
    window_text = " ".join(window)
    rationalization_hits = list(_PETTINESS_RATIONALIZATION_RE.finditer(window_text))

    if not rationalization_hits:
        return None

    examples = []
    for m in rationalization_hits[:3]:
        start = max(0, m.start() - 20)
        end = min(len(window_text), m.end() + 80)
        examples.append(re.sub(r"\s+", " ", window_text[start:end]).strip())

    return {
        "petty_moment_preview": petty_moment_text[:80],
        "rationalization_hit_count": len(rationalization_hits),
        "examples": examples,
    }


def run_chapter_contract_checks(text: str, chapter_outline) -> dict:
    """Check a chapter's prose against chapter-level contract fields.

    Currently checks:
    - ``petty_moment``: verifies the moment appears and is not immediately rationalized.

    Returns a dict with keys ``passed`` (bool) and ``failures`` (list[str]).
    """
    failures: list[str] = []
    lower = text.lower()

    # --- Petty moment contract check ---
    petty_moment = (getattr(chapter_outline, "petty_moment", "") or "").strip()
    if petty_moment:
        petty_keywords = [
            w for w in re.findall(r"[a-z']+", petty_moment.lower())
            if w not in _STOP_WORDS and len(w) > 3
        ]
        if petty_keywords:
            matched = sum(1 for kw in petty_keywords if kw in lower)
            match_ratio = matched / len(petty_keywords)
            if match_ratio < 0.4:
                failures.append(
                    f"Petty moment not found in chapter — "
                    f"'{petty_moment[:80]}' appears absent "
                    f"({matched}/{len(petty_keywords)} content words matched)"
                )
            else:
                rationalization = detect_pettiness_rationalization(text, petty_moment)
                if rationalization:
                    failures.append(
                        f"Petty moment is immediately rationalized — "
                        f"found {rationalization['rationalization_hit_count']} rationalization "
                        f"pattern(s) after the petty beat. "
                        f"Example: '{rationalization['examples'][0] if rationalization['examples'] else ''}'"
                    )

    return {"passed": len(failures) == 0, "failures": failures}


# ------------------------------------------------------------------
# Phase 5: Scene ending tonal monotony detection and gate
# ------------------------------------------------------------------

_ENDING_DARK_MOTIFS = frozenset((
    "alone", "quiet", "silence", "dark", "darkness", "fire", "ember",
    "grate", "lamp", "candle", "reflection", "reflect", "shadow",
    "solitary", "sealed", "letter", "rain", "window", "night",
))

_ENDING_ACTION_VERBS = re.compile(
    r"\b(?:arrived|arriving|came|coming|opened|opening|entered|entering|"
    r"produced|delivering|summoned|summoning|seized|seizing|"
    r"interrupted|demanding|refused|refusing|acted|acting|"
    r"running|ran|chasing|signing|signed|sealed)\b",
    re.IGNORECASE,
)

_ENDING_QUESTION_RE = re.compile(r"\?")


def _compute_ending_fingerprint(ending_text: str) -> dict:
    """Compute a tonal fingerprint for the final portion of a chapter/scene."""
    words = re.findall(r"[a-z']+", ending_text.lower())
    if not words:
        return {}

    total = len(words)
    dark_hits = sum(1 for w in words if w in _ENDING_DARK_MOTIFS)
    dark_density = dark_hits / total

    action_hits = len(_ENDING_ACTION_VERBS.findall(ending_text))
    action_density = action_hits / max(total / 100, 1)

    sentences = _split_sentences(ending_text)
    sentence_lengths = [len(re.findall(r"[a-zA-Z']+", s)) for s in sentences if s]
    avg_sentence_len = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0

    question_count = len(_ENDING_QUESTION_RE.findall(ending_text))
    question_density = question_count / max(len(sentences), 1)

    return {
        "dark_density": round(dark_density, 3),
        "action_density": round(action_density, 3),
        "avg_sentence_len": round(avg_sentence_len, 2),
        "question_density": round(question_density, 3),
        "dark_hits": dark_hits,
    }


def _ending_fingerprints_similar(
    fp_a: dict,
    fp_b: dict,
    similarity_threshold: float = 0.70,
) -> bool:
    """Return True if two ending fingerprints are tonally similar.

    Uses dark_density as the primary signal. Two endings are "similar" when
    BOTH have dark/reflective motif density above the threshold-derived cutoff.
    The ``similarity_threshold`` parameter scales to a dark_density cutoff
    (0.70 → 0.07 density required in each ending).

    This is intentionally conservative: an ending must actively contain
    the dark/solitary/sealed-letter vocabulary to be flagged.
    """
    if not fp_a or not fp_b:
        return False

    dark_cutoff = similarity_threshold * 0.10  # 0.70 → 0.07
    return fp_a["dark_density"] >= dark_cutoff and fp_b["dark_density"] >= dark_cutoff


def detect_ending_tonal_monotony(
    chapter_texts: dict[int, str],
    ending_window_words: int = 250,
    similarity_threshold: float = 0.70,
) -> list[dict]:
    """Detect consecutive chapter endings that share the same tonal register.

    Takes a dict mapping chapter numbers to their full text. Extracts the
    final ``ending_window_words`` words from each chapter and computes a
    tonal fingerprint. Returns findings for consecutive pairs that are
    tonally similar.

    Returns a list of dicts (one per similar pair) with keys:
      - ``chapter_a``, ``chapter_b``: chapter numbers
      - ``fingerprint_a``, ``fingerprint_b``: computed fingerprints
    """
    if len(chapter_texts) < 2:
        return []

    sorted_chapters = sorted(chapter_texts.items())
    fingerprints: list[tuple[int, dict]] = []
    for ch_num, text in sorted_chapters:
        ending_words = re.findall(r"[a-z']+", text.lower())[-ending_window_words:]
        ending_text = " ".join(ending_words)
        fp = _compute_ending_fingerprint(ending_text)
        fingerprints.append((ch_num, fp))

    findings: list[dict] = []
    for i in range(len(fingerprints) - 1):
        ch_a, fp_a = fingerprints[i]
        ch_b, fp_b = fingerprints[i + 1]
        if _ending_fingerprints_similar(fp_a, fp_b, similarity_threshold):
            findings.append({
                "chapter_a": ch_a,
                "chapter_b": ch_b,
                "fingerprint_a": fp_a,
                "fingerprint_b": fp_b,
            })

    return findings


def format_ending_tonal_monotony_report(findings: list[dict]) -> str:
    """Format ending tonal monotony findings for correction context."""
    if not findings:
        return ""

    pairs = ", ".join(
        f"chapters {f['chapter_a']} and {f['chapter_b']}" for f in findings
    )
    lines = [
        "ENDING TONAL MONOTONY ALERT:",
        f"Consecutive chapter endings share the same tonal register ({pairs}). "
        "The 'alone in a dark room' / solitary-reflection shape is repeating. "
        "The current chapter MUST end differently.",
        "Use the assigned ending_mode and consult the ENDING MODE REFERENCE section "
        "for concrete examples of non-default ending shapes.",
    ]
    for item in findings[:4]:
        fp_a = item["fingerprint_a"]
        fp_b = item["fingerprint_b"]
        lines.append(
            f"- Ch {item['chapter_a']} dark density: {fp_a.get('dark_density', 0):.3f}, "
            f"action density: {fp_a.get('action_density', 0):.1f}"
        )
        lines.append(
            f"  Ch {item['chapter_b']} dark density: {fp_b.get('dark_density', 0):.3f}, "
            f"action density: {fp_b.get('action_density', 0):.1f}"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Acceptance gates — deterministic pass/fail wrappers
# ------------------------------------------------------------------

@dataclass
class GateResult:
    """Outcome of a single quality gate check."""

    gate_name: str
    passed: bool
    details: dict = dc_field(default_factory=dict)
    report: str = ""

    def to_dict(self) -> dict:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "details": self.details,
            "report": self.report,
        }


def gate_immediate_jeopardy(
    text: str,
    max_deficit_scenes: int = 1,
) -> GateResult:
    """Pass if the number of scenes lacking immediate jeopardy is within threshold."""
    findings = detect_low_immediate_jeopardy(text)
    passed = len(findings) <= max_deficit_scenes
    return GateResult(
        gate_name="immediate_jeopardy",
        passed=passed,
        details={
            "deficit_scenes": len(findings),
            "threshold": max_deficit_scenes,
        },
        report="" if passed else format_immediate_jeopardy_report(findings),
    )


def gate_offstage_opposition(text: str) -> GateResult:
    """Pass if offstage opposition does not dominate on-page conflict."""
    finding = detect_offstage_opposition_overuse(text)
    passed = finding is None
    return GateResult(
        gate_name="offstage_opposition",
        passed=passed,
        details=finding or {},
        report="" if passed else format_offstage_opposition_report(finding),
    )


def gate_ending_propulsion(text: str) -> GateResult:
    """Pass if the chapter ending sustains unresolved external pressure."""
    finding = detect_low_propulsion_endings(text)
    passed = finding is None
    return GateResult(
        gate_name="ending_propulsion",
        passed=passed,
        details=finding or {},
        report="" if passed else format_low_propulsion_endings_report(finding),
    )


def gate_exposition_drag(
    text: str,
    max_drag_runs: int = 1,
) -> GateResult:
    """Pass if exposition-drag runs are within threshold."""
    findings = detect_exposition_drag(text)
    passed = len(findings) <= max_drag_runs
    return GateResult(
        gate_name="exposition_drag",
        passed=passed,
        details={
            "drag_runs": len(findings),
            "threshold": max_drag_runs,
        },
        report="" if passed else format_exposition_drag_report(findings),
    )


def gate_rhythm_monotony(
    text: str,
    paragraph_cv_threshold: float = 0.45,
    short_sentence_ratio_threshold: float = 0.10,
) -> GateResult:
    """Pass if prose cadence shows sufficient paragraph/sentence length variance."""
    finding = detect_rhythm_monotony(
        text,
        paragraph_cv_threshold=paragraph_cv_threshold,
        short_sentence_ratio_threshold=short_sentence_ratio_threshold,
    )
    passed = finding is None
    return GateResult(
        gate_name="rhythm_monotony",
        passed=passed,
        details=finding or {},
        report="" if passed else format_rhythm_monotony_report(finding),
    )


def gate_narrator_psychologizing(
    text: str,
    max_per_1k_words: float = 5.0,
) -> GateResult:
    """Pass if narrator interior-state density is within threshold per scene."""
    findings = detect_narrator_psychologizing(text, max_per_1k_words=max_per_1k_words)
    passed = len(findings) == 0
    return GateResult(
        gate_name="narrator_psychologizing",
        passed=passed,
        details={
            "flagged_scenes": len(findings),
            "threshold_per_1k_words": max_per_1k_words,
        },
        report="" if passed else format_narrator_psychologizing_report(findings),
    )


def gate_ending_tonal_monotony(
    chapter_texts: dict[int, str],
    max_consecutive_similar: int = 2,
    ending_window_words: int = 250,
    similarity_threshold: float = 0.70,
) -> GateResult:
    """Pass if consecutive chapter endings do not share the same tonal register.

    This is a cross-chapter gate: it compares each chapter's ending against its
    immediate predecessor to detect the repeating 'dark room / sealed letter /
    solitary reflection' shape. In the pipeline, ``chapter_texts`` typically
    contains just two chapters (prior + current), so the gate fails when any
    consecutive pair is tonally similar.

    ``max_consecutive_similar`` controls how many similar pairs are tolerated
    before failure. Default is 2, meaning the gate fails when 2 or more
    consecutive pairs share the same dark/reflective register.
    """
    findings = detect_ending_tonal_monotony(
        chapter_texts,
        ending_window_words=ending_window_words,
        similarity_threshold=similarity_threshold,
    )
    passed = len(findings) < max_consecutive_similar
    return GateResult(
        gate_name="ending_tonal_monotony",
        passed=passed,
        details={
            "similar_consecutive_pairs": len(findings),
            "threshold": max_consecutive_similar,
        },
        report="" if passed else format_ending_tonal_monotony_report(findings),
    )


def run_scene_contract_checks(
    scene_text: str,
    contract,
    *,
    enable_physical_interruption_contracts: bool = True,
    enable_narrative_register: bool = True,
) -> dict:
    """Check a single scene's prose against its pressure contract fields.

    Returns a dict with keys ``passed`` (bool) and ``failures`` (list[str]).
    """
    failures: list[str] = []
    lower = scene_text.lower()
    profile = getattr(contract, "gate_profile", "external_collision") or "external_collision"

    is_internal = profile == "internal_conflict"

    if not is_internal:
        onstage_hits = len(_ONSTAGE_CONFLICT.findall(scene_text))
        if onstage_hits == 0:
            failures.append(
                "No on-page conflict markers found — opponent_move is not "
                "realized as concrete action"
            )

        offstage_hits = len(_OFFSTAGE_OPPOSITION.findall(scene_text))
        if offstage_hits > max(5, onstage_hits * 3):
            failures.append(
                f"Offstage opposition ({offstage_hits}) dominates on-page "
                f"conflict ({onstage_hits}) — dramatize the collision"
            )

        opponent_present_on_page = getattr(contract, "opponent_present_on_page", True)
        if opponent_present_on_page is None:
            opponent_present_on_page = True
        opponent_actor = (getattr(contract, "opponent_actor", "") or "").strip()
        if opponent_actor and opponent_actor.lower() != "self" and opponent_present_on_page:
            # Robust actor matching: allow multipart and accented names.
            actor_head = re.split(r"[—,;()]", opponent_actor)[0].strip().lower()
            actor_tokens = [
                t for t in re.findall(r"[a-zA-ZÀ-ÿ]+", actor_head)
                if len(t) >= 3 and t not in _STOP_WORDS
            ]
            candidate_tokens: set[str] = set(actor_tokens)
            matched_any = any(t in lower for t in candidate_tokens if t)
            if not matched_any:
                failures.append(
                    f"Opponent actor '{opponent_actor}' not found in scene "
                    "text — opponent must be present on page"
                )

    risk_hits = len(_IMMEDIATE_RISK_MARKERS.findall(scene_text))
    consequence_hits = len(_CONSEQUENCE_VERBS.findall(scene_text))
    if risk_hits == 0 and consequence_hits == 0:
        failures.append(
            "No immediate jeopardy markers or consequence verbs found"
        )

    required_end_hook = (getattr(contract, "required_end_hook", "") or "").strip()
    if required_end_hook:
        ending_words = re.findall(r"[a-z']+", lower)[-250:]
        ending_text = " ".join(ending_words)
        pressure_hits = len(_ENDING_PRESSURE.findall(ending_text))
        hook_words = [
            w for w in re.findall(r"[a-z']+", required_end_hook.lower())
            if w not in _STOP_WORDS and len(w) > 3
        ]
        hook_overlap = 0.0
        if hook_words:
            hook_overlap = sum(1 for w in hook_words if w in ending_text) / len(hook_words)
        reflection_hits = len(
            re.findall(
                r"\b(?:thought|wondered|reflected|remembered|alone|quiet)\b",
                ending_text,
            )
        )
        # Accept either explicit pressure markers OR substantial lexical overlap
        # with the required end-hook contract language.
        if pressure_hits < 1 and hook_overlap < 0.35:
            failures.append(
                f"Required end hook '{required_end_hook[:60]}' — ending "
                f"has only {pressure_hits} pressure markers and low hook overlap ({hook_overlap:.2f})"
            )
        if reflection_hits > 5:
            failures.append(
                "Ending is dominated by reflective deceleration despite "
                "required_end_hook obligation"
            )

    # --- Craft contract checks (Phase 4) ---

    dominant_sense = (getattr(contract, "dominant_sense", "") or "").strip().lower()
    if dominant_sense and dominant_sense in _SENSORY_KEYWORDS:
        sense_words = _SENSORY_KEYWORDS[dominant_sense]
        hits = sum(
            len(re.findall(rf"\b{re.escape(word)}\b", lower))
            for word in sense_words
        )
        # Allow weak sensory realization when adjacent generic sensory verbs exist.
        generic_sensory_hits = len(
            re.findall(r"\b(?:smell|scent|odor|taste|touch|hear|sound|feel|warm|cold)\b", lower)
        )
        if hits == 0 and generic_sensory_hits < 2:
            failures.append(
                f"Dominant sense '{dominant_sense}' not realized — no "
                f"{dominant_sense}-related sensory words found in scene"
            )

    externalization_gesture = (
        getattr(contract, "externalization_gesture", "") or ""
    ).strip()
    if externalization_gesture:
        gesture_content_words = [
            w for w in re.findall(r"[a-z']+", externalization_gesture.lower())
            if w not in _STOP_WORDS and len(w) > 2
        ]
        if gesture_content_words:
            matched = sum(1 for w in gesture_content_words if w in lower)
            match_ratio = matched / len(gesture_content_words)
            # Gesture contracts are often paraphrased in revision; require either
            # lexical overlap OR evidence of concrete physical action beats.
            action_hits = len(
                re.findall(
                    r"\b(?:set|placed|pushed|pulled|turned|crossed|stood|sat|moved|rolled|folded|opened|closed|reached)\b",
                    lower,
                )
            )
            if match_ratio < 0.5 and action_hits < 6:
                failures.append(
                    f"Externalization gesture not found in scene — "
                    f"'{externalization_gesture[:80]}' appears to be absent "
                    f"({matched}/{len(gesture_content_words)} content words matched)"
                )

    # --- Phase 5: Physical interruption contract check ---

    physical_interruption = (
        getattr(contract, "physical_interruption", "") or ""
    ).strip()
    if enable_physical_interruption_contracts and physical_interruption:
        interruption_content_words = [
            w for w in re.findall(r"[a-z']+", physical_interruption.lower())
            if w not in _STOP_WORDS and len(w) > 3
        ]
        if interruption_content_words:
            matched = sum(1 for w in interruption_content_words if w in lower)
            match_ratio = matched / len(interruption_content_words)
            interruption_event_hits = len(
                re.findall(
                    r"\b(?:interrupted|interruption|crack|knock|door|startled|stopped|paused|shifted|popped|burst|jolt)\b",
                    lower,
                )
            )
            if match_ratio < 0.4 and interruption_event_hits == 0:
                failures.append(
                    f"Physical interruption not found in scene — "
                    f"'{physical_interruption[:80]}' appears absent "
                    f"({matched}/{len(interruption_content_words)} content words matched)"
                )
            else:
                rationalization = detect_symbolic_rationalization(
                    scene_text, physical_interruption
                )
                if rationalization:
                    failures.append(
                        f"Physical interruption was turned into metaphor or symbol — "
                        f"found {rationalization['rationalization_hit_count']} rationalization "
                        f"pattern(s) immediately following the interruption. "
                        f"The body must interrupt without meaning. Remove the metaphor."
                    )

    # --- Phase 5: Narrative register contract check ---

    narrative_register = getattr(contract, "narrative_register", {}) or {}
    if enable_narrative_register and narrative_register:
        register_findings = detect_register_uniformity(scene_text, narrative_register)
        if register_findings:
            for failure in register_findings.get("failures", []):
                failures.append(f"Narrative register: {failure}")

    return {"passed": len(failures) == 0, "failures": failures}


def detect_incomplete_chapter_ending(text: str) -> dict:
    """Deterministic heuristics for truncated or incomplete chapter endings.

    Returns an empty dict if the ending looks complete, or a dict with keys:
    ``reasons`` (list[str]) and ``tail_preview`` (last 120 chars) if issues
    are detected.

    Detection heuristics (all deterministic, no LLM):
    - Unmatched open quotes, parentheses, or brackets in the tail
    - Final non-whitespace token ends with suspicious incomplete punctuation
      (e.g. a bare dash, comma, or mid-word break)
    - Abrupt last-line patterns: line ends with a pronoun, conjunction, or
      article that implies the sentence was cut (He, The, and, but, or, a, an)
    - Missing sentence-final punctuation in the last two lines (with
      exception for stylistic ellipsis ``...``)
    """
    if not text or not text.strip():
        return {}

    tail = text.strip()
    last_200 = tail[-200:]
    last_line = tail.splitlines()[-1].strip() if tail.splitlines() else ""
    second_last_line = (
        tail.splitlines()[-2].strip()
        if len(tail.splitlines()) >= 2
        else ""
    )

    reasons: list[str] = []

    # 1. Unmatched open quotes/parentheses/brackets
    quote_open = last_200.count('"') % 2
    paren_diff = last_200.count('(') - last_200.count(')')
    bracket_diff = last_200.count('[') - last_200.count(']')
    if quote_open:
        reasons.append("Unmatched double-quote in final 200 chars — likely unclosed dialogue")
    if paren_diff > 0:
        reasons.append(f"Unmatched open parenthesis in final 200 chars ({paren_diff} unclosed)")
    if bracket_diff > 0:
        reasons.append(f"Unmatched open bracket in final 200 chars ({bracket_diff} unclosed)")

    # 2. Final non-whitespace token ends with bare dash or comma
    last_token = re.split(r'\s+', tail.rstrip())[-1] if tail.strip() else ""
    if last_token.endswith('—') or last_token.endswith('–') or last_token == '-':
        reasons.append(f"Chapter ends with bare dash — suggests mid-sentence cut: '{last_token}'")
    elif last_token.endswith(','):
        reasons.append(f"Chapter ends with a comma — incomplete sentence: '{last_token}'")

    # 3. Abrupt last-line patterns: line ends with pronoun/conjunction/article
    _ABRUPT_ENDINGS = re.compile(
        r'\b(?:he|she|they|it|we|i|the|a|an|and|but|or|so|yet|for|nor|'
        r'that|which|who|what|when|where|why|how|this|these|those|then)$',
        re.IGNORECASE,
    )
    if last_line and _ABRUPT_ENDINGS.search(last_line):
        reasons.append(
            f"Last line ends with a dangling function word — sentence appears cut: "
            f"'{last_line[-60:]}'"
        )

    # 4. Missing sentence-final punctuation in last 1-2 non-blank lines
    _SENTENCE_FINAL = re.compile(r'[.!?…"\')\]—]$')
    _ELLIPSIS_OK = re.compile(r'\.\.\.\s*$')  # stylistic ellipsis is acceptable
    for line_text in [last_line, second_last_line]:
        if not line_text:
            continue
        if _ELLIPSIS_OK.search(line_text):
            continue
        if line_text.startswith('#') or line_text == '---':
            continue  # headers and scene breaks are not prose lines
        if not _SENTENCE_FINAL.search(line_text):
            reasons.append(
                f"Line lacks sentence-final punctuation: '{line_text[-80:]}'"
            )
        break  # only flag once (last substantive line is sufficient)

    if not reasons:
        return {}

    return {
        "reasons": reasons,
        "tail_preview": tail[-120:],
    }


def gate_complete_chapter_ending(
    text: str,
    thresholds: dict | None = None,
) -> GateResult:
    """Pass if the chapter ending shows no truncation or incompleteness signals."""
    finding = detect_incomplete_chapter_ending(text)
    passed = not bool(finding)
    report = ""
    if not passed:
        reasons_text = "\n".join(f"  - {r}" for r in finding.get("reasons", []))
        tail = finding.get("tail_preview", "")
        report = (
            "## CHAPTER COMPLETION FAILURE\n\n"
            "The chapter ending appears truncated or incomplete.\n\n"
            f"**Detected issues:**\n{reasons_text}\n\n"
            f"**Tail preview:**\n```\n{tail}\n```\n\n"
            "Complete the chapter's final scene naturally. Do not introduce new "
            "plot events — only finish the existing sentence/scene with proper "
            "punctuation and a clean narrative endpoint."
        )
    return GateResult(
        gate_name="complete_chapter_ending",
        passed=passed,
        details=finding or {},
        report=report,
    )


def run_chapter_gates(
    text: str,
    thresholds: dict[str, int | float] | None = None,
) -> dict[str, GateResult]:
    """Run all chapter-level acceptance gates and return keyed results."""
    t = thresholds or {}
    gates: dict[str, GateResult] = {
        "immediate_jeopardy": gate_immediate_jeopardy(
            text,
            max_deficit_scenes=t.get("max_jeopardy_deficit_scenes", 1),
        ),
        "offstage_opposition": gate_offstage_opposition(text),
        "ending_propulsion": gate_ending_propulsion(text),
        "exposition_drag": gate_exposition_drag(
            text,
            max_drag_runs=t.get("max_exposition_drag_runs", 1),
        ),
        "rhythm_monotony": gate_rhythm_monotony(
            text,
            paragraph_cv_threshold=t.get("rhythm_cv_threshold", 0.45),
            short_sentence_ratio_threshold=t.get("short_sentence_ratio_threshold", 0.10),
        ),
        "narrator_psychologizing": gate_narrator_psychologizing(
            text,
            max_per_1k_words=t.get("max_psychologizing_per_1k_words", 5.0),
        ),
        "complete_chapter_ending": gate_complete_chapter_ending(text, t),
    }
    return gates
