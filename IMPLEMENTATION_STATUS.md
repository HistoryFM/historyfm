# Sovereign Ink — Implementation Status

**Last updated:** March 2, 2026  
**Status:** `the_dark_horse_ab` is complete (12/12) and frozen for reference. Active work has shifted to a Louisiana Purchase quality-recovery reset with a two-track loop strategy (continue current run + start fresh A/B reboot).

---

## Changes - March 2, 2026 (Program Reset for New Chat)

### 1. Loop Program Reframed

Planning was reset from single-track continuation to a controlled two-track execution model:

- **Track A:** continue `louisiana_purchase_loop_ab` with targeted compulsion fixes.
- **Track B:** create a fresh project `louisiana_purchase_opus_ab` using the same synopsis constraints for direct A/B comparison.

### 2. New Priority Backlog Activated

`NextSteps-Latest.md` has been cleared and rewritten with a new priority stack:

1. On-page opposition hardening and flagged-scene targeted retry.
2. Immediate jeopardy reliability (prompt realization + detector expansion).
3. Ending propulsion stabilization (including stronger retry fallback).
4. Exposition drag relapse prevention.
5. Repetition family suppression in diplomatic chapters.

### 3. Model Allocation Policy Updated

Selective Opus usage is now part of the official plan for high-leverage tasks only:

- structural planning on the fresh B-track,
- flagged structural-revision interventions,
- critic diagnosis quality pass.

No always-on Opus rollout is approved by default.

### 4. Loop Governance and Stop Criteria Reconfirmed

- Standard loop size remains +2 chapters whenever possible.
- Plateau stop requires two consecutive loops with:
  - net compulsion-proxy improvement < 5%, and
  - no material movement in at least 3/5 core metrics.
- +1 loop closure is allowed only with explicit chapter-boundary deviation note.

---

## Changes - March 2, 2026 (Loop Execution: A3 + B1)

### 1. Loop A3 Executed on Track A (`louisiana_purchase_loop_ab`)

Generated and polished:
- `drafts/v3_polish/chapter_05.md` (7,098 words)
- `drafts/v3_polish/chapter_06.md` (5,567 words)

Metric delta vs A2 baseline (chapters 01-04 aggregate):

| Metric | A2 baseline | A3 (chapters 01-06 aggregate) | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 3.5960 | 4.5830 | +0.9870 (regressed) |
| exposition_drag_runs_per_10k_words | 1.3485 | 2.5779 | +1.2294 (regressed) |
| ending_propulsion_deficit_flag rate | 0.5000 | 0.3333 | -0.1667 (improved) |
| offstage_opposition_overuse_flag rate | 1.0000 | 1.0000 | 0.0000 (flat) |
| dialogue_uniformity_flag rate | 0.0000 | 0.1667 | +0.1667 (regressed) |

Interpretation: R0/R1 reliability did not converge in A3; opposition realization and jeopardy consistency remain unstable despite ending gains.

### 2. Track B Reboot Created and Loop B1 Executed (`louisiana_purchase_opus_ab`)

Initialisation and outputs:
- fresh project created with the same constrained Louisiana synopsis seed
- structural planning completed with Opus on B-track
- generated and polished `chapter_01.md` (5,121 words) and `chapter_02.md` (8,443 words)

Comparison vs A1 baseline (chapters 01-02 on Track A):

| Metric | A1 | B1 | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 1.7119 | 4.4235 | +2.7116 (regressed) |
| exposition_drag_runs_per_10k_words | 2.5678 | 1.4745 | -1.0933 (improved) |
| ending_propulsion_deficit_flag rate | 0.5000 | 0.0000 | -0.5000 (improved) |
| offstage_opposition_overuse_flag rate | 1.0000 | 1.0000 | 0.0000 (flat) |
| dialogue_uniformity_flag rate | 0.0000 | 0.0000 | 0.0000 (flat) |

Comparison vs A2 baseline (chapters 01-04 on Track A):

| Metric | A2 | B1 | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 3.5960 | 4.4235 | +0.8275 (regressed) |
| exposition_drag_runs_per_10k_words | 1.3485 | 1.4745 | +0.1260 (regressed) |
| ending_propulsion_deficit_flag rate | 0.5000 | 0.0000 | -0.5000 (improved) |
| offstage_opposition_overuse_flag rate | 1.0000 | 1.0000 | 0.0000 (flat) |
| dialogue_uniformity_flag rate | 0.0000 | 0.0000 | 0.0000 (flat) |

Interpretation: B1 improves ending reliability and controls dialogue drift, but does not yet solve opposition realization or jeopardy density.

### 3. Engineering Sprint Landed During Loop Execution

Three scoped changes were implemented:

1. **Stage 1 non-interactive setup hardening** (`stage1_setup.py`)  
   Existing `NovelSpec` on disk is now consumed directly, preventing terminal prompt failures in unattended runs.
2. **Selective Opus structural revision trigger** (`stage5_revision.py`, `config.py`, `generation_config.yaml`)  
   Structural pass now escalates to Opus only on flagged chapters (`offstage_opposition` and/or high immediate-jeopardy deficit rate).
3. **Model/cost policy alignment** (`generation_config.yaml`, `config.py`)  
   Added explicit Opus model/rate support and activated B-track structural-planning Opus assignment.

### 4. Gate/Plateau Status

- A3 acceptance gate (3-of-5 improve-or-target): **not met**
- B1 startup loop: **mixed** (ending gains, core compulsion blockers unresolved)
- Plateau criteria: **not evaluated as met** (insufficient consecutive-loop evidence)

---

## Changes - March 3, 2026 (Loop Execution: A4 + B2)

### 1. Loop A4 Executed on Track A (`louisiana_purchase_loop_ab`)

Generated and polished:
- `drafts/v3_polish/chapter_07.md` (5,663 words)
- `drafts/v3_polish/chapter_08.md` (4,337 words)

Metric delta vs A3 baseline (chapters 01-06 aggregate):

| Metric | A3 baseline | A4 (chapters 01-08 aggregate) | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 4.5830 | 4.6758 | +0.0928 (regressed) |
| exposition_drag_runs_per_10k_words | 2.5779 | 2.2266 | -0.3513 (improved) |
| ending_propulsion_deficit_flag rate | 0.3333 | 0.3750 | +0.0417 (regressed) |
| offstage_opposition_overuse_flag rate | 1.0000 | 0.8750 | -0.1250 (improved) |
| dialogue_uniformity_flag rate | 0.1667 | 0.1250 | -0.0417 (improved) |

Acceptance-gate call (3-of-5 improve-or-target): **met** (3 improved, 2 regressed).

### 2. Loop B2 Executed on Track B (`louisiana_purchase_opus_ab`)

Generated and polished:
- `drafts/v3_polish/chapter_03.md` (5,155 words)
- `drafts/v3_polish/chapter_04.md` (6,151 words)

Metric delta vs B1 baseline (chapters 01-02 aggregate):

| Metric | B1 baseline | B2 (chapters 01-04 aggregate) | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 4.4235 | 3.2167 | -1.2068 (improved) |
| exposition_drag_runs_per_10k_words | 1.4745 | 2.0105 | +0.5360 (regressed) |
| ending_propulsion_deficit_flag rate | 0.0000 | 0.2500 | +0.2500 (regressed) |
| offstage_opposition_overuse_flag rate | 1.0000 | 1.0000 | 0.0000 (flat) |
| dialogue_uniformity_flag rate | 0.0000 | 0.0000 | 0.0000 (flat) |

Reference comparisons:

- **B2 vs A2 baseline:** improved immediate jeopardy and ending-propulsion rate, regressed exposition drag, flat on offstage opposition/dialogue.
- **B2 vs A3 baseline:** improved on 4/5 metrics, flat on offstage opposition.

Acceptance-gate call (3-of-5 improve-or-target): **not met** (1 improved, 2 regressed, 2 flat).

### 3. Observed Runtime Notes

1. Selective Opus structural trigger fired for all newly generated A4/B2 chapters as intended.
2. `louisiana_purchase_loop_ab` chapter 08 logged a continuity-update parse failure; fallback kept prior ledger (no schema break observed).
3. Ending-only polish retry remains active and fired in all four newly generated chapters.

### 4. Decision / Continuation

- Winner-track decision: **deferred** (B2 gate not met).
- Protocol outcome: **continue both tracks** for one additional loop.
- Next loop targets:
  - **A5:** `louisiana_purchase_loop_ab` chapters 09-10
  - **B3:** `louisiana_purchase_opus_ab` chapters 05-06

---

## Changes — February 25, 2026

### 1. P0–P9 Enforcement Layer Implemented

The previously planned second-generation quality fixes (P0–P9) are now implemented across prompt + code + generation context.

**Implemented detectors in `text_quality.py`:**
- `detect_over_explanation()` (P0)
- `detect_nouny_who_pattern()` (P1)
- `detect_word_frequency_outliers()` (P2)
- `detect_sensory_deficit()` (P4)
- `build_chapter_ending_warning()` / generation-time ending motif warning support (P5)
- `detect_rhythm_monotony()` (P7)
- `detect_dialogue_uniformity()` (P8)
- `detect_metaphor_saturation()` (P9)

### 2. Generation Prompt Upgrades (P0, P3, P5, P6, P7, P8)

`generation/chapter.j2` now includes:
- POV-specific narrative voice specification (Polk / Sarah / Walker + fallback)
- THE SILENCE RULE
- FALLIBILITY RULE
- RHYTHM RULE
- DIALOGUE NATURALNESS RULE
- STRUCTURAL VARIETY RULE
- Optional chapter-ending similarity warning context block

### 3. Revision Prompt Upgrades

Added non-negotiable Silence Rule reinforcement in:
- `revision/structural.j2`
- `revision/voice_and_dialogue.j2`
- `revision/polish.j2`

Added rhythm-audit reinforcement in polish pass.

### 4. Generation-Time Anti-Crutch Baseline

`stage4_prose_generation.py` now injects baseline banned phrases (`particular`, `which was`) in addition to tracked banned phrases/constructions.

### 5. Production Validation

Recent `the_dark_horse` incremental runs show the new detector families actively firing during structural revision (e.g., `nouny_who`, `frequency_outliers`, `sensory_deficit`, `metaphor_saturation`), confirming enforcement is operational.

---

## Changes — February 26, 2026

### 1. A/B Validation Complete (`the_dark_horse` vs `the_dark_horse_ab`, Chapters 1–5)

We ran a direct chapter-level A/B comparison using the same story/synopsis to isolate engineering impact from premise variance.

| Metric (Ch 1–5) | Original | New |
|---|---:|---:|
| Total words | 28,376 | 29,432 |
| Immediate jeopardy deficit scenes | 24 | 18 |
| Surprise-density deficit chapters | 0 | 1 |
| Ending-propulsion deficit chapters | 2 | 1 |
| Exposition-drag runs | 3 | 7 |
| Offstage-opposition deficit chapters | 4 | 1 |
| Dialogue-uniformity deficit chapters | 3 | 0 |

**Interpretation:**  
- Clear gains in dialogue naturalness and on-page antagonist pressure.  
- Jeopardy and ending propulsion improved but are not yet stable.  
- Exposition drag is now the dominant residual bottleneck.

### 2. Post-Implementation Roadmap Reframed

`NextSteps-Latest.md` is now refreshed to focus on **calibration and reliability** problems (C0–C8), not new detector family rollout.

New top-priority engineering items:
1. Per-chapter quality artifact persistence (C0)
2. Exposition drag control and rewrite targeting (C2)
3. Ending propulsion stabilization with optional ending-only retry (C3)
4. Immediate jeopardy consistency hardening (C1)
5. Reveal realization verification (C4)
6. Automated A/B regression harness (C8)

### 3. Current Acceptance Targets

For next merge window:
- Reduce exposition-drag runs by >=30% vs current A/B baseline
- Zero ending-propulsion deficits in newly generated chapters
- Maintain duplicate passage protections (no regression)
- Preserve revision word-count floor behavior
- Add no new always-on LLM calls per chapter without explicit approval

---

## Changes — March 1, 2026 (Loop 1: Chapters 06-07)

### 1. Loop Execution Complete (+2 Chapters)

Generated two new polished chapters for `the_dark_horse_ab`:
- `drafts/v3_polish/chapter_06.md` (5,175 words)
- `drafts/v3_polish/chapter_07.md` (5,484 words)

Per-chapter and aggregate quality artifacts are now present:
- `state/quality_reports/chapter_06.json`
- `state/quality_reports/chapter_07.json`
- `state/quality_reports/aggregate.json`

### 2. Loop Metrics vs Prior Baseline (A/B Ch 01-05)

| Metric | Prior Baseline | Loop 1 (Ch 06-07) | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 6.1158 | 8.4436 | +2.3278 (regressed) |
| exposition_drag_runs_per_10k_words | 2.3784 | 0.0000 | -2.3784 (improved) |
| ending_propulsion_deficit_flag rate | 0.20 | 0.00 | -0.20 (improved) |
| offstage_opposition_overuse_flag rate | 0.20 | 0.00 | -0.20 (improved) |
| dialogue_uniformity_flag rate | 0.00 | 0.50 | +0.50 (regressed) |

**Interpretation:** quality continues to improve in exposition control, ending propulsion, and on-page opposition pressure, but compulsion reliability is still constrained by immediate-jeopardy realization and dialogue-uniformity drift in chapter 07.

### 3. Engineering Fixes Implemented In-Loop

Addressed the highest-impact bottlenecks with a tightly scoped sprint:

1. **Quality audit parse hardening** (`stage5_revision.py`)  
   - Added fallback extraction of first balanced JSON object when model responses include preamble/fences.  
   - Expected impact: more reliable structured audit injection into structural revision.

2. **Immediate jeopardy detector expansion** (`text_quality.py`)  
   - Broadened consequence verb lexicon.  
   - Added conditional consequence pattern matching (`if/unless ... will ... cost/lose/...`).  
   - Expected impact: lower false positives and better alignment between true scene stakes and detector output.

3. **Prompt-level constraint tightening**  
   - `revision/structural.j2`: explicit immediate-risk + consequence beat now mandatory per scene.  
   - `revision/voice_and_dialogue.j2`: anti-`said`-storm / attribution-overuse constraint added for conflict exchanges.

### 4. Guardrail Check

No regressions observed in protected invariants:
- Stage resumability and skip behavior preserved
- Revision word-count floor behavior preserved
- Synopsis-aligned POV behavior preserved
- Historical title/date correctness untouched
- Duplicate passage auto-retry behavior preserved
- Continuity ledger schema flow untouched
- No new always-on LLM calls added

### 5. Current Remaining Blockers

Top blockers after Loop 1:
1. Immediate jeopardy consistency in polished output
2. Dialogue uniformity in high-pressure political confrontations
3. Surprise cadence density (especially mid-chapter turn distribution)

---

## Changes — March 1, 2026 (Loop 2: Chapters 08-09)

### 1. Loop Execution Complete (+2 Chapters)

Generated:
- `drafts/v3_polish/chapter_08.md` (5,527 words)
- `drafts/v3_polish/chapter_09.md` (6,158 words)

### 2. Metrics Delta vs Loop 1 (Ch 06-07 -> Ch 08-09)

| Metric | Loop 1 | Loop 2 | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 8.4436 | 8.5580 | +0.1144 (regressed) |
| exposition_drag_runs_per_10k_words | 0.0000 | 0.0000 | 0.0000 (flat) |
| ending_propulsion_deficit_flag rate | 0.00 | 0.00 | 0.00 (flat) |
| offstage_opposition_overuse_flag rate | 0.00 | 0.00 | 0.00 (flat) |
| dialogue_uniformity_flag rate | 0.50 | 1.00 | +0.50 (regressed) |

**Interpretation:** Loop 2 improved audit reliability and maintained drag/ending/opposition stability, but compulsion trend did not improve due to persistent jeopardy realization deficits and dialogue-uniformity pressure.

### 3. Sprint Implemented In-Loop

1. `stage5_revision.py`: quality-audit `max_tokens` increased from 4096 to 8192 to prevent truncated JSON responses.
2. `text_quality.py`: `_split_scenes()` now ignores heading-only pseudo-scenes that were inflating jeopardy deficit counts.
3. `text_quality.py`: `detect_dialogue_uniformity()` trailing-ratio threshold recalibrated (`0.08 -> 0.0`) to reduce false positives.

### 4. Runtime Validation Signal

- Chapter 08 still showed audit-parse failure (old token cap path).
- Chapter 09 succeeded in parsing quality-audit output after token-budget increase, confirming the wiring fix is effective.

### 5. Plateau Progress

Loop 2 satisfies the plateau condition once (net compulsion proxy did not improve and >=3 key metrics did not improve), but stop criteria require two consecutive loops. One additional loop is required for confirmation.

---

## Changes — March 1, 2026 (Loop 3: Chapters 10-11)

### 1. Loop Execution Complete (+2 Chapters)

Generated:
- `drafts/v3_polish/chapter_10.md` (6,403 words)
- `drafts/v3_polish/chapter_11.md` (6,173 words)

### 2. Metrics Delta vs Loop 2 (Ch 08-09 -> Ch 10-11)

| Metric | Loop 2 | Loop 3 | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 8.5580 | 3.9758 | -4.5822 (improved) |
| exposition_drag_runs_per_10k_words | 0.0000 | 1.5903 | +1.5903 (regressed) |
| ending_propulsion_deficit_flag rate | 0.00 | 0.50 | +0.50 (regressed) |
| offstage_opposition_overuse_flag rate | 0.00 | 0.00 | 0.00 (flat) |
| dialogue_uniformity_flag rate | 1.00 | 0.50 | -0.50 (improved) |

**Interpretation:** Loop 3 produced substantial compulsion-proxy recovery via jeopardy and dialogue gains, but exposed a renewed ending/drag reliability issue.

### 3. Plateau Determination Status

- Loop 2 met plateau condition once.
- Loop 3 did **not** meet plateau condition (compulsion proxy improved strongly, with two key metrics improving).
- Therefore plateau criteria are currently **not satisfied**.

### 4. Process Constraint

Only one chapter remains unfinished (`chapter_12`), which blocks another strict +2 loop under the current protocol. The next operational step is final single-chapter generation followed by an explicit end-of-run assessment noting this loop-size deviation.

---

## Changes — March 1, 2026 (Loop 4 Closure: Chapter 12)

### 1. Final Chapter Execution Complete (+1, Protocol Deviation)

Generated:
- `drafts/v3_polish/chapter_12.md` (7,791 words)

Deviation from loop protocol:
- The loop framework requires `+2 chapters` per cycle, but only one unfinished chapter remained after Loop 3. Closure was executed as a documented `+1` loop.

### 2. Metrics Delta vs Loop 3 Baseline (Ch 10-11 -> Ch 12)

| Metric | Loop 3 | Loop 4 (Ch 12) | Delta |
|---|---:|---:|---:|
| immediate_jeopardy_deficit_scenes_per_10k_words | 3.9758 | 3.8506 | -0.1252 (improved) |
| exposition_drag_runs_per_10k_words | 1.5903 | 1.2835 | -0.3068 (improved) |
| ending_propulsion_deficit_flag rate | 0.50 | 0.00 | -0.50 (improved) |
| offstage_opposition_overuse_flag rate | 0.00 | 1.00 | +1.00 (regressed) |
| dialogue_uniformity_flag rate | 0.50 | 0.00 | -0.50 (improved) |

**Interpretation:** Closure chapter improved 4/5 tracked compulsion metrics, especially ending propulsion and dialogue uniformity, but regressed on offstage-opposition overuse.

### 3. End-State Assessment

**Stabilized in this run:**
- quality-audit parse/wiring reliability,
- jeopardy and dialogue burden trend vs Loop 2 peak,
- ending-only retry capability with successful closure recovery.

**Remaining reliability gaps:**
- offstage opposition still intermittently off-page,
- exposition drag still non-zero under long-form closeout chapters.

### 4. Plateau Rule Outcome

Strict two-consecutive-loop plateau confirmation was not possible at run end due to chapter-count boundary (`12/12`). Run termination is therefore completion-based with explicit protocol deviation note, not plateau-based.

### 5. Recommended Next Branch Scope

Keep changes narrowly targeted to:
1. on-page opposition enforcement and validation,
2. anti-drag rewrite enforcement in late-chapter sections,
3. jeopardy consequence semantic calibration.

---

## Changes — February 23–24, 2026

### 1. Model Upgrade: Sonnet 4 → Sonnet 4.6

All quality-critical pipeline stages upgraded from `claude-sonnet-4-20250514` to `claude-sonnet-4-6`. Haiku 4.5 retained for utility tasks.

**Files changed:**
- `generation_config.yaml` — all model references updated, cost rates added for `claude-sonnet-4-6`
- `sovereign_ink/utils/config.py` — default model values and cost dictionaries updated

### 2. Code-Level Quality Checks (New)

New `sovereign_ink/utils/text_quality.py` module with Python-based quality detection that runs after prose generation and catches issues LLMs cannot self-police:

| Function | What it detects |
|----------|----------------|
| `detect_duplicate_passages()` | Near-duplicate paragraphs via `SequenceMatcher` (threshold 60% similarity, min 15 words) |
| `detect_within_chapter_repetition()` | Repeated 3/4/5-grams appearing 3+ times (filters common English) |
| `detect_essay_passages()` | 3+ consecutive paragraphs without dialogue, action, or sensory detail |
| `run_all_quality_checks()` | Runs all three, returns combined report |

Results are injected into the first revision pass as mandatory fix directives.

### 3. Structured LLM Quality Audit (New)

New template `sovereign_ink/prompts/templates/revision/quality_audit.j2` — a pre-revision LLM audit that analyzes the v0_raw draft and produces a structured JSON report covering:
- POV character agency (active vs passive verbs per scene)
- Sensory detail count per scene
- Dialogue function (each line classified as action, exposition, or filler)
- Register compliance per scene
- Duplicate detection

Audit results are injected into the structural revision pass as mandatory fixes.

**Files changed:**
- `sovereign_ink/pipeline/stages/stage5_revision.py` — added `_run_quality_audit()` method, integrated code-level checks and audit into `revise_single_chapter()`, added post-revision duplicate check with auto-retry

### 4. Prompt Consolidation: THE FIVE LAWS

The chapter generation prompt (`chapter.j2`) was refactored:
- 14 "Craft Warnings" consolidated into **THE FIVE LAWS** (absolute priorities):
  1. Show, don't tell
  2. POV must act
  3. Sensory grounding
  4. No within-chapter repetition
  5. Match register
- Remaining warnings moved to SECONDARY GUIDELINES at lower priority
- Added **REGISTER REFERENCE** with examples for each tonal register
- Reduces cognitive load on the LLM — fewer, clearer rules produce better compliance

### 5. Dialogue Dynamics (New)

Added structured dialogue guidance to scene breakdowns:

- **New model:** `DialogueDynamics` (Pydantic) with fields: `character_wants`, `hidden_motivation`, `power_shift`, `subtext`
- Added optional `dialogue_dynamics` field to `Scene` model
- Updated `scene_breakdowns.j2` to instruct LLM to generate dialogue dynamics for dialogue-heavy scenes
- Updated `chapter.j2` to display dialogue dynamics in the scene plan

**Files changed:**
- `sovereign_ink/models/structure.py` — new `DialogueDynamics` model, updated `Scene`
- `sovereign_ink/models/__init__.py` — re-exports `DialogueDynamics`
- `sovereign_ink/prompts/templates/structure/scene_breakdowns.j2`
- `sovereign_ink/prompts/templates/generation/chapter.j2`

### 6. POV Character Alignment Fix

**Bug:** World building `characters.j2` template never included the synopsis. The LLM invented fictional POV characters that contradicted the synopsis's named protagonists (e.g., "Colonel Nathaniel Hartwell" instead of Polk). Chapter outlines template had a hard-coded directive forcing fictional POV characters.

**Fix:**
- `characters.j2` — now renders `novel_spec.synopsis` and includes a **SYNOPSIS CHARACTER MANDATE** making synopsis-named POV characters non-negotiable
- `chapter_outlines.j2` — fictional POV directive replaced with conditional: **SYNOPSIS POV MANDATE** when synopsis exists, fictional character suggestion only when no synopsis provided

### 7. Synopsis-POV Alignment Check (New)

Added `_check_synopsis_pov_alignment()` to `stage3_structural_planning.py` — warns at generation time if POV characters in chapter outlines don't match characters named in the synopsis. Runs after chapter outlines are built.

### 8. POV Agency Enforcement in Revision

The structural revision template (`structural.j2`) now includes:
- Quality audit results displayed as mandatory fixes
- **MANDATORY AGENCY INSERTION** — rule-based check with explicit actions the LLM must take if a scene's POV character is passive (agent must decide, act, risk, or change something)

---

## Current Test Run: `the_dark_horse` v3

| Metric | Value |
|--------|-------|
| Novel | The Dark Horse — The Polk Presidency (1844–1849) |
| POV Characters | James K. Polk, Sarah Childress Polk, Robert J. Walker |
| Model | Claude Sonnet 4.6 |
| Planned chapters | 11 (3 acts) |
| Generated chapters | 6 polished chapters (ongoing) |
| Status | Incremental generation active |

### Quality Assessment (v2 vs v1)

| Dimension | v1 (Sonnet 4) | v2 (Sonnet 4.6 + fixes) |
|-----------|---------------|------------------------|
| POV characters | Wrong (fictional) | Correct (Polk/Sarah/Walker) |
| POV agency | Passive observers | Active drivers |
| Duplicate passages | Catastrophic (whole scenes duplicated) | None detected |
| Political detail | Generic | Specific and vivid |
| Prose quality | Historical summary | Genuinely literary |
| Word count preservation | 70% loss in revision | Stable through revision |

### Remaining Problems (Post P10–P17 rollout)

| ID | Problem | Severity | Status |
|----|---------|----------|--------|
| C0 | Metric persistence + quality artifacts | High | Planned (Sprint A) |
| C1 | Immediate jeopardy consistency | High | Planned (Sprint A) |
| C2 | Exposition drag control | Very High | Planned (Sprint A) |
| C3 | Ending propulsion reliability | High | Planned (Sprint A) |
| C4 | Reveal realization checks | High | Planned |
| C5 | Repetition-density recalibration | Medium | Planned |
| C6 | On-page opposition hardening | Medium | Planned |
| C7 | Detector threshold calibration framework | Medium | Planned |
| C8 | Automated A/B regression harness | High | Planned |

Detailed priorities and acceptance gate are tracked in `NextSteps-Latest.md`.

---

## Non-Regression Requirements

Any upcoming implementation from `NextSteps-Latest.md` (P10–P17) must preserve these invariants:

1. **Do not regress resumability** — stage artifacts and sub-step recovery must remain intact.
2. **Do not regress word-count preservation** — revision passes must continue honoring existing word-count floors.
3. **Do not regress POV correctness** — synopsis-aligned POV enforcement remains mandatory.
4. **Do not regress title/date correctness** — `TitleTenure` resolution behavior must remain unchanged.
5. **Do not regress duplicate protection** — duplicate passage checks + auto-retry remain active.
6. **Do not regress continuity state integrity** — continuity ledger updates and chapter summaries must remain schema-valid.
7. **Do not regress cost envelope unexpectedly** — new checks should avoid introducing large additional LLM calls per chapter without explicit approval.

---

## How to Run

```bash
cd /Users/dhrumilparekh/NovelGen
source .venv/bin/activate
```

### Option A: One chapter at a time (recommended)

```bash
# 1. Create a new project (interactive setup + synopsis selection)
sovereign-ink new -p my_novel

# 2. Generate the next polished chapter (runs stages 1-3 automatically on first run)
sovereign-ink next -p my_novel

# 3. Read the polished chapter at my_novel/drafts/v3_polish/chapter_01.md

# 4. Generate the next chapter
sovereign-ink next -p my_novel

# 5. Repeat until all chapters are done, then assemble
sovereign-ink export -p my_novel
```

Each `next` invocation:
1. Ensures stages 1–3 are complete (setup, world building, structural planning)
2. Finds the next chapter without a `v3_polish` draft
3. Generates the v0_raw draft (~3,000–5,000 words)
4. Runs quality audit (LLM + code-level checks)
5. Runs 3 revision passes: structural → voice/dialogue → polish (with auto-retry on duplicate detection)
6. Saves all versions and exits
7. Reports word count, remaining chapters, and cost

### Option B: Full batch pipeline (original behavior)

```bash
sovereign-ink new -p my_novel
sovereign-ink run -p my_novel
```

### Other commands

```bash
sovereign-ink status -p my_novel    # Check pipeline progress
sovereign-ink export -p my_novel    # Assemble manuscript from polished chapters
```

### Multiple novels

Each novel lives in its own directory. Run as many in parallel as you want:

```bash
sovereign-ink new -p french_revolution
sovereign-ink new -p the_dark_horse
sovereign-ink next -p french_revolution
sovereign-ink next -p the_dark_horse
```

---

## Architecture

### Project Structure

```
<project_name>/
├── config/
│   └── novel_spec.json          # NovelSpec (includes synopsis)
├── world/
│   ├── historical_context.json  # Era, key events, major_players (with date-ranged titles)
│   ├── characters.json          # Character profiles with voice patterns
│   ├── institutions.json        # Political/social institutions
│   └── era_tone_guide.json      # Prose style constraints
├── structure/
│   └── novel_structure.json     # Acts, chapter outlines, scene breakdowns (with dialogue dynamics)
├── state/
│   ├── pipeline_state.json      # Stage progress, tokens, cost
│   ├── continuity_ledger.json   # Character knowledge, relationships, open threads
│   ├── context_summaries.json   # Rolling chapter summaries
│   └── banned_phrases.json      # Cross-chapter phrase tracking
├── drafts/
│   ├── v0_raw/                  # Initial prose generation
│   ├── v1_structural/           # After structural revision (+ quality audit fixes)
│   ├── v2_voice_and_dialogue/   # After voice/dialogue revision
│   └── v3_polish/               # Final polished version (ready to read)
├── output/
│   ├── manuscript.md            # Assembled manuscript
│   └── metadata.json            # Generation metadata
└── logs/
```

### Pipeline Stages

| Stage | What it does |
|-------|-------------|
| 1. Interactive Setup | Collects novel parameters + generates 3 synopsis options for user selection |
| 2. World Building | Historical context (with date-ranged titles), characters (synopsis-aligned), institutions, era tone guide |
| 3. Structural Planning | Act structure, chapter outlines (synopsis POV mandate), scene breakdowns (with dialogue dynamics), synopsis-POV alignment check |
| 4. Prose Generation | Chapter writing with THE FIVE LAWS, register reference, continuity tracking, phrase dedup |
| 5. Revision Pipeline | Quality audit (LLM + code) → 3 passes: structural → voice/dialogue → polish (with duplicate auto-retry) |
| 6. Assembly & Export | Combines polished chapters into final manuscript |

### Key Configuration (`generation_config.yaml`)

- `model_prose_generation: "claude-sonnet-4-6"` — Main prose model
- `model_utility: "claude-haiku-4-5-20251001"` — Utility tasks
- `temperature_prose: 0.85` — Higher = more creative
- `temperature_revision: 0.6` — Lower for analytical revision
- `target_words_per_chapter: 3000` — Target chapter length
- `max_chapters: 3` — Testing limit (set to `null` for all chapters)
- `num_revision_passes: 3` — 3 consolidated passes

### Tips

- Set `num_revision_passes: 1` for quick test runs (structural only)
- If any stage fails, delete `.lock` and re-run; resume logic handles everything
- The `next` command ignores `max_chapters` — it always processes the next planned chapter
- Write your own synopsis for best POV control — name your POV characters explicitly

---

## Full Change History

### February 23–24, 2026
- Model upgrade: Sonnet 4 → Sonnet 4.6 (all quality stages)
- New: `text_quality.py` — code-level duplicate, repetition, essay detection
- New: `quality_audit.j2` — LLM self-audit before revision
- New: `DialogueDynamics` model for structured dialogue guidance
- Fix: POV character alignment (synopsis in `characters.j2`, mandate in `chapter_outlines.j2`)
- Fix: Synopsis-POV alignment check in structural planning
- Refactor: 14 craft warnings → THE FIVE LAWS + secondary guidelines
- Added: REGISTER REFERENCE with tonal examples
- Added: POV agency enforcement in structural revision
- Added: Post-revision duplicate detection with auto-retry

### February 22, 2026
- Historical title accuracy system (`TitleTenure` model, date-ranged title resolution)
- Synopsis selection flow (3 LLM-generated options + write-your-own)
- Incremental chapter-at-a-time generation (`sovereign-ink next`)

### February 21, 2026
- Bug fixes: wrong default model, continuity ledger truncation, JSON parsing, streaming timeout
- Consolidated revision pipeline: 7 passes → 3
- Cross-chapter phrase tracker
- CRAFT WARNINGS in prose generation prompt
- Quality checkpoint after early chapters

### February 16–20, 2026
- Initial implementation of all 6 pipeline stages
- First test run: `nullification_crisis` (12 chapters, 40,937 words, ~$1.66)
