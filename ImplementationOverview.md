# Sovereign Ink — Implementation Overview

**Last updated:** March 28, 2026

Sovereign Ink is an autonomous historical novel generation system. It takes a user's creative brief (era, region, event, themes) and produces a full-length manuscript through a six-stage pipeline powered by Anthropic's Claude API. Each novel lives in its own project directory with persistent state, allowing incremental generation, resumption after failure, and multiple novels in parallel.

---

## Current State (March 2026)

### Latest Operational Update (March 28, 2026)

**Self-healing escalation** has been added to the `sovereign-ink next` convergence loop. The CLI now automatically relaxes quality constraints through 4 escalation levels when a chapter cannot converge, eliminating the need for manual config intervention.

- **Scene breakdown pre-flight**: Before entering the convergence loop, `_ensure_scene_breakdowns()` checks if the target chapter has a scene breakdown in `novel_structure.json`. If missing, it generates one on the fly by invoking `StructuralPlanningStage._build_scene_breakdowns()`. This prevents the "Missing scene breakdown for chapter" infinite failure loop that occurred when `max_chapters` was increased after initial structural planning.
- **4-level escalation**: When a chapter exhausts its convergence attempts or hits repeated identical failures, the CLI escalates to the next relaxation level instead of raising an error. Config is mutated in-memory (not on disk) via the shared `orchestrator.config` reference. After completion (success or final failure), original config is always restored via `finally` block.
- **Chapter state reset on escalation**: Each escalation level clears the chapter state file, convergence failure files, and in-progress drafts so the retry starts clean.
- **Validated in production**: Louisiana chapter 11 converged at escalation level 1 after failing at level 0.

Previous fix (March 25, 2026):

- Disabled semantic validation (`semantic_validator_enabled: false`) previously returned a failing result, making chapter acceptance impossible in Stage 4. It now behaves as a non-blocking no-op pass.
- Acceptance gating in Stage 4 no longer hard-fails solely because bypass flags are present; bypass flags remain persisted for reporting.
- Revision revalidation in Stage 5 was also updated to avoid false hard-fails from bypass-only conditions and to respect optional contract flags when scene contract checks run.

### Novel Generation Progress

| Project | Total chapters | Accepted (v3_polish) | Status |
|---------|---------------|---------------------|--------|
| `john_tyler_succession_12ch` | 12 | 12/12 | Complete |
| `louisiana_purchase_phase11_v2_3ch` | 12 | 10/12 (ch 1-10) | In progress — ch 11-12 remaining |

### Active Quality Program

The system can produce coherent, historically grounded prose, but quality remains inconsistent across chapters. Quality enforcement has evolved through multiple phases: prompt hardening, code-level detectors, A/B testing loops, pre-generation quality gates, pressure contracts, craft gates with Opus escalation tiering, and Phase 7 revision-regression controls.

Five project tracks exist on the Louisiana Purchase brief:

| Project | Chapters | Config | Purpose |
|---------|----------|--------|---------|
| `louisiana_purchase_gated` | 6 polished | 4 quality gates | Canary for gate system |
| `louisiana_purchase_loop_ab` | 8 polished | Gates off, detectors + revision | Track A baseline |
| `louisiana_purchase_opus_ab` | 4 polished | Gates off, Opus structural | Track B baseline |
| `louisiana_purchase_contracts` | 6 polished | 4 gates + pressure contracts | Pressure contract canary |
| `louisiana_purchase_craft_gates` | 4 polished | 6 gates + contracts + Opus tiering | Craft gates comparison |

### Latest Quality Comparison: Craft Gates vs Contracts (4 chapters each)

| Dimension | Contracts | Craft Gates | Verdict |
|-----------|-----------|-------------|---------|
| Total cost | ~$14.66 (6ch) | ~$9.50 (4ch) | Opus reduced |
| Opus calls | 61% of cost | Only on structural gate failures | **Improved** |
| Rhythm monotony | Not gated | Gated (all passed) | **New** |
| Narrator psychologizing | Not gated | Gated (all passed) | **New** |
| Sensory grounding | Visual-dominant | Multi-sensory via `dominant_sense` | **Improved** |
| Externalization | Inconsistent | Gesture-driven via contract | **Improved** |
| Scene structure (Ch3) | 7,221 words | 6,773 words (tighter, 0 retries) | **Improved** |

### Literary Assessment (March 2026)

A close reading of all polished chapters from both projects concluded: the craft gates version is **modestly better** in sensory grounding, externalization, and scene tightness, but the improvements are incremental. Neither version reaches the tier of great historical fiction (Mantel, Caro, Vidal). Six shortcomings remain: prose register monotony across POVs, decorative rather than contesting physicality, absent bodies, no unresolved pettiness, slavery anachronism, and scene ending monotony. See `NextSteps-Latest.md` for the original improvement plan.

**Phase 5: Literary Quality Elevation (implemented March 2026)** addresses four of these shortcomings with new upstream contracts, prompt directives, and detection logic. All four features are behind config flags (off by default). See the Quality System Architecture section below for implementation details.

### Phase 7 Canary Results (March 2026, Louisiana Purchase, 5 chapters)

Phase 7 was run in `louisiana_purchase_phase7` and compared against the Phase 6 baseline in `louisiana_purchase_phase6`.

| Metric | Phase 6 (v0_raw) | Phase 6 (v3_polish) | Phase 7 (v0_raw) | Phase 7 (v3_polish) | Outcome |
|--------|-------------------|---------------------|------------------|---------------------|---------|
| Repetition patterns (total) | 201 | 212 | 340 | 433 | Repetition regression remains severe |
| Frequency outlier terms (total) | 383 | 388 | 463 | 449 | Mixed; improved in aggregate in Phase 7 |
| Sensory deficit scenes (total) | 6 | 9 | 4 | 6 | Better baseline; still degrades during revision |
| Immediate jeopardy deficit scenes (total) | 1 | 4 | 5 | 7 | Degradation rate improved vs Phase 6, but still regresses |
| Ending propulsion deficit flags | 1/4 chapters | 1/4 chapters | 0/5 chapters | 1/5 chapters | Partial improvement only |

What improved:
- Stronger raw drafts in sensory grounding on this run.
- Some chapter-level reductions in frequency outliers.
- Lower jeopardy degradation rate compared with Phase 6.

What regressed or remains unsolved:
- Revision still increases repetition patterns substantially (the central failure).
- Ending propulsion still fails in one polished chapter.
- Chapter length variance remains severe (raw chapters reached 7k-12k words in a 3k-target canary).

Technical note:
- Stage 3 `estimated_word_count` controls are not reliably constraining Stage 4 prose length in practice. Chapter-level estimates may be clamped in planning, but generated chapter length can still overshoot significantly.

Next priority (Phase 8):
- Enforce chapter/scene word budgets at generation time (not only in planning metadata).
- Prevent revision-pass repetition inflation, especially in voice and polish.
- Strengthen ending-propulsion correction strategy so a failing ending is reliably recoverable.
- Keep sensory and jeopardy non-regression guarantees across revision passes.
- Preserve surgical scope: fix root causes in current architecture without a full pipeline redesign.

---

## Tech Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Language | Python 3.11+ | Everything |
| LLM Provider | Anthropic Claude API | All generation and revision |
| Models | Claude Sonnet 4.6 (default), Claude Opus 4.6 (selective structural), Claude Haiku 4.5 (utility) | Configurable per stage |
| CLI Framework | Click | Command-line interface |
| Data Models | Pydantic v2 | Schema validation, serialization |
| Templating | Jinja2 | Prompt construction |
| Interactive UI | Rich (display), Questionary (input) | Terminal UX |
| Token Counting | tiktoken (`cl100k_base`) | Budget management |
| Config | YAML (`generation_config.yaml`) | All tuneables, with project-local override support |
| Env | python-dotenv | API key management |

**Dependencies:** `anthropic`, `pydantic`, `rich`, `questionary`, `jinja2`, `pyyaml`, `python-dotenv`, `tiktoken`, `click`, `pytest`

---

## Architecture

### The Six-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SOVEREIGN INK PIPELINE                                  │
│                                                                                 │
│  Stage 1          Stage 2           Stage 3            Stage 4                  │
│  ┌──────────┐    ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐     │
│  │ Setup    │───▶│ World        │─▶│ Structural    │─▶│ Prose            │     │
│  │          │    │ Building     │  │ Planning      │  │ Generation       │     │
│  │ NovelSpec│    │              │  │               │  │                  │     │
│  │ Synopsis │    │ History      │  │ Acts          │  │ v0_raw drafts    │     │
│  └──────────┘    │ Characters   │  │ Chapters      │  │ Quality gates    │     │
│                  │ Institutions │  │ Scenes        │  │ Summaries        │     │
│                  │ Tone Guide   │  │ Continuity    │  │ Phrase tracking  │     │
│                  └──────────────┘  │ Validation    │  └────────┬─────────┘     │
│                                    └───────────────┘           │               │
│  Stage 6          Stage 5                                      │               │
│  ┌──────────┐    ┌──────────────────────────────────────┐      │               │
│  │ Assembly │◀───│ Revision Pipeline                    │◀─────┘               │
│  │ & Export │    │                                      │                      │
│  │          │    │ Gate escalation context (if failed)   │                      │
│  │ manuscript│   │ Pass 1: Structural (v0→v1)           │                      │
│  │ metadata │    │ Pass 2: Voice & Dialogue (v1→v2)     │                      │
│  └──────────┘    │ Pass 3: Polish (v2→v3)               │                      │
│                  └──────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Quality Gate Flow (Stage 4 → Stage 5)

```
  Stage 4: Prose Generation
  ─────────────────────────
  LLM generates chapter (streaming)
         │
         ▼
  ┌──────────────────────────┐
  │ Run 6 quality gates      │
  │  • jeopardy (structural) │
  │  • opposition (struct.)  │
  │  • ending                │
  │  • exposition            │
  │  • rhythm monotony       │
  │  • narrator psychologiz. │
  └─────────┬────────────────┘
            │
     All passed? ──YES──▶ Save v0_raw + gate results
            │
            NO
            │
            ▼
  ┌─────────────────────┐
  │ Correction retry    │  (up to gate_max_chapter_retries)
  │ with gate failure   │
  │ context injected    │
  └─────────┬───────────┘
            │
            ▼
  Save v0_raw + gate results (pass or fail)
            │
            ▼
  Stage 5: Revision Pipeline
  ──────────────────────────
  If gates still failed:
    → Build gate escalation context
    → Inject into Pass 1 as mandatory fix directives
```

### Two Execution Modes

**Batch mode** (`sovereign-ink run`): Generates all chapters as v0_raw drafts, then runs all revision passes across all chapters.

**Incremental mode** (`sovereign-ink next`): Generates one chapter, runs quality gates, runs all 3 revision passes, outputs a fully polished chapter. Run again for the next. This is the recommended mode.

### Self-Healing Escalation (`commands.py`)

The `next` command wraps the convergence loop with a 4-level escalation system that progressively relaxes quality constraints when a chapter cannot converge. This eliminates the need for manual config editing and retrying.

```
┌────────────────────────────────────────────────────────────────────┐
│  Pre-flight: _ensure_scene_breakdowns(ch_num)                      │
│  Snapshot original config                                          │
│                                                                    │
│  for escalation_level in 0..3:                                     │
│    ├─ Restore config snapshot                                      │
│    ├─ Apply _ESCALATION_LEVELS[level] overrides                    │
│    ├─ If level > 0: _reset_chapter_for_retry()                     │
│    │                                                               │
│    │  while attempts < max_attempts:                               │
│    │    ├─ generate_single_chapter(ch_num)                         │
│    │    ├─ revise_single_chapter(ch_num)                           │
│    │    ├─ If accepted → break (converged)                         │
│    │    ├─ If ContractEnforcementError → track signature           │
│    │    └─ If identical_failure_streak >= max → break (escalate)   │
│    │                                                               │
│    ├─ If converged → break                                         │
│    └─ Else → persist failure, escalate to next level               │
│                                                                    │
│  finally: restore original config snapshot                         │
│  If not converged after all levels → raise RuntimeError            │
└────────────────────────────────────────────────────────────────────┘
```

**Escalation levels** (`_ESCALATION_LEVELS` in `commands.py`):

| Level | Overrides | Rationale |
|-------|-----------|-----------|
| 0 | None (project config as-is) | Try with full quality enforcement first |
| 1 | `enable_pressure_contracts: false`, `stage4_scene_count_tolerance: 1` | Pressure contracts and strict scene counts cause most convergence failures |
| 2 | Level 1 + `semantic_validator_enabled: false`, `adversarial_verifier_enabled: false`, `stage4_max_total_repair_attempts: 20` | Disable expensive LLM-based validators, increase repair budget |
| 3 | Level 2 + `enable_quality_gates: false`, `next_max_convergence_attempts: 20`, `next_max_identical_failure_streak: 6` | Disable all gates, max retry budget — guaranteed convergence at quality cost |

**Key implementation details:**
- Config mutation is **in-memory only** via `setattr()` on the shared `orchestrator.config` Pydantic model (non-frozen). No YAML file I/O.
- `_save_config_snapshot()` / `_restore_config_snapshot()` capture and restore only the fields affected by escalation (`_ESCALATION_CONFIG_FIELDS` set).
- `_reset_chapter_for_retry()` clears: chapter state JSON, convergence failure JSON, and all draft `.md` files for the chapter across every draft directory.
- `_ensure_scene_breakdowns()` calls `StructuralPlanningStage._build_scene_breakdowns()` which iterates all chapter outlines and only generates breakdowns for chapters not already present — safe to call repeatedly.

### Configuration Hierarchy

The orchestrator loads config via a two-layer merge:

1. **Workspace root** `generation_config.yaml` — base defaults (gates off by default)
2. **Project-local** `<project>/generation_config.yaml` — overrides merged on top

This allows per-project gate settings (e.g., `louisiana_purchase_gated` has `enable_quality_gates: true`) without changing the root config.

### Project Directory Structure

```
<project_name>/
├── config/
│   └── novel_spec.json          # User's creative brief + chosen synopsis
├── world/
│   ├── historical_context.json  # Era, events, major_players (with date-ranged titles)
│   ├── characters.json          # Character profiles with voice patterns and arcs
│   ├── institutions.json        # Political/social institutions
│   └── era_tone_guide.json      # Prose style constraints, forbidden terms
├── structure/
│   └── novel_structure.json     # Acts, chapter outlines, scene breakdowns
├── state/
│   ├── pipeline_state.json      # Stage progress, token counts, cost
│   ├── continuity_ledger.json   # Character knowledge, relationships, open threads
│   ├── context_summaries.json   # Rolling per-chapter summaries
│   ├── banned_phrases.json      # Cross-chapter phrase deduplication
│   ├── chapter_states/
│   │   └── chapter_NN.json      # Per-chapter convergence state (accepted, attempt_count, etc.)
│   ├── convergence_failures/
│   │   └── chapter_NN_latest.json # Last convergence failure signature (used by escalation)
│   └── quality_reports/
│       ├── aggregate.json       # Aggregate quality metrics across all chapters
│       ├── chapter_NN.json      # Per-chapter quality report (v0_raw + v3_polish counts)
│       └── chapter_NN_gates.json # Stage 4 gate results (pass/fail + details per gate)
├── drafts/
│   ├── v0_raw/                  # Initial prose generation (post-gate)
│   ├── v1_structural/           # After structural revision
│   ├── v2_voice_and_dialogue/   # After voice/dialogue revision (or v2_creative/)
│   └── v3_polish/               # Final polished version
├── output/
│   ├── manuscript.md            # Assembled manuscript
│   └── metadata.json            # Generation metadata
├── generation_config.yaml       # (optional) Project-local config overrides
└── logs/
    └── sovereign_ink.jsonl      # Structured logs
```

---

## Pipeline Stages in Detail

### Stage 1: Interactive Setup

**What it does:** Resolves the novel brief and synopsis seed for downstream stages.

If `config/novel_spec.json` already exists, Stage 1 loads and uses it directly (non-interactive-safe path). Otherwise, it runs the terminal setup wizard, then generates 3 synopsis options via the LLM for user selection.

**Key model:** `NovelSpec` — `title`, `era_start/end`, `region`, `central_event`, `tone_intensity`, `pov_count`, `protagonist_type`, `thematic_focus`, `desired_length`, `synopsis`, `additional_notes`

### Stage 2: World Building

**What it does:** 4 sequential LLM calls build the novel's world, then assembles the composite `WorldState`.

**Sub-steps:**
1. **Historical context** — era description, key events (with dates), major players (with date-ranged titles via `TitleTenure`)
2. **Character profiles** — protagonist(s) and supporting cast with political objectives, fears, hidden motivations, moral conflicts, relationships, emotional arcs, voice patterns (speech style, class markers, verbal tics), `narrative_register` (Phase 5: sentence rhythm, diction family, consciousness style, signature lens), and backstory
3. **Institutions** — political/social institutions with power levels, constraints, factional pressures, plausible/implausible actions
4. **Era tone guide** — language register, vocabulary constraints, forbidden terms, dialogue style guide, narrative voice calibration, example dialogue snippets

**Resumability:** Each sub-step saves independently. If the stage fails mid-way, re-running resumes from the last incomplete sub-step.

### Stage 3: Structural Planning

**What it does:** Plans the novel's architecture through 4 sub-steps, then assembles and validates the structure.

**Sub-steps:**
1. **Act structure** — 3–4 acts with titles, descriptions, dramatic beats, stakes levels
2. **Chapter outlines** — per-chapter: title, POV character, setting, time period, political context, goal, conflict, turn, consequences, plus compulsion-planning fields (hard reveal, soft reversal, on-page opposing move, ending mode from `VALID_ENDING_MODES` taxonomy), `petty_moment` (Phase 5), estimated word count
3. **Scene breakdowns** — per-chapter: scene number, POV, setting, goal, opposition, immediate risk, irreversible failure cost, power-shift target, turn, consequences, emotional beat, complexity score, continuity notes, dialogue dynamics, supporting-cast pressure, `dominant_sense`, `externalization_gesture`, `physical_interruption` (Phase 5)
4. **Continuity ledger** — initialized with timeline, character knowledge, political capital, relationships, open threads

**Structure validation:** After assembly, `validate_pressure_architecture()` checks all chapter outlines and scenes for:
- Non-empty opposition and jeopardy fields
- Valid `ending_mode` values (from `VALID_ENDING_MODES` taxonomy)
- Valid `register` values (from `VALID_REGISTERS` taxonomy)
- Scene count within bounds (2–8 per chapter)
- Chapter estimate warnings for under/over target ranges

If `gate_strict_structure_validation` is enabled, validation failures raise a `RuntimeError` blocking generation. Otherwise, warnings are logged.

**Key model:** `NovelStructure` (composite of `ActStructure`, `ChapterOutline[]`, `SceneBreakdown[]`)

### Stage 4: Prose Generation

**What it does:** Generates chapter prose (v0_raw drafts) using streaming, runs quality gates, then runs post-generation bookkeeping.

**Per-chapter flow:**
1. Load chapter outline and scene breakdown
2. Gather character profiles, resolve historical figure titles for chapter year
3. Load continuity ledger, prior chapter summaries, banned phrases, upcoming chapter outlines
4. Render the `chapter.j2` prompt with all context
5. Stream the chapter from the LLM (Sonnet, temperature 0.85)
6. **Run quality gates** (if `enable_quality_gates` is true):
   - `gate_immediate_jeopardy` — deficit scenes ≤ `gate_max_jeopardy_deficit_scenes` **(structural — Opus-eligible)**
   - `gate_offstage_opposition` — offstage mentions must not dominate on-page conflict **(structural — Opus-eligible)**
   - `gate_ending_propulsion` — final 250 words must have unresolved external pressure **(craft — Sonnet-only)**
   - `gate_exposition_drag` — consecutive exposition runs ≤ `gate_max_exposition_drag_runs` **(craft — Sonnet-only)**
   - `gate_rhythm_monotony` — paragraph CV ≥ threshold, short sentence ratio ≥ threshold **(craft — Sonnet-only)**
   - `gate_narrator_psychologizing` — interior-state verb density ≤ threshold per 1k words **(craft — Sonnet-only)**
   - If any gate fails: run `_gate_correction_pass()` with failure context injected, up to `gate_max_chapter_retries` times
   - Opus escalation on retry only triggers for gates listed in `opus_eligible_gates` (default: `offstage_opposition`, `immediate_jeopardy`)
   - Save gate results to `chapter_NN_gates.json`
7. Save v0_raw draft
8. Generate chapter summary (Haiku utility call)
9. Update continuity ledger (Haiku utility call)
10. Extract notable phrases and update banned_phrases (Haiku utility call)

**The chapter prompt** (`chapter.j2`) includes: chapter outline, scene plan, THE FIVE LAWS (show don't tell, POV must act, sensory grounding, no repetition, match register), REGISTER REFERENCE, character profiles with voice patterns, continuity context, story-so-far summaries, banned phrases, and chapter-ending variety warnings.

**Additional enforced constraints:** THE SILENCE RULE, FALLIBILITY RULE, RHYTHM RULE, DIALOGUE NATURALNESS RULE, STRUCTURAL VARIETY RULE.

### Stage 5: Revision Pipeline

**What it does:** Runs 3 revision passes on each chapter, with gate-failure escalation awareness.

**Pre-Revision — Quality Audit (v0_raw analysis):**
1. **LLM Self-Audit** (`quality_audit.j2`) — Structured analysis of POV agency, sensory count, dialogue function, register compliance, duplicate detection.
2. **Code-Level Quality Checks** (`text_quality.py`) — 16+ detectors for duplicates, over-explanation, repetition, sensory deficits, rhythm monotony, dialogue uniformity, metaphor saturation, immediate jeopardy, offstage opposition, ending propulsion, exposition drag, narrator psychologizing, and more.

**Gate escalation:** If Stage 4 gates failed after retries, `_build_gate_escalation_context()` formats the specific gate failures into structured escalation directives injected into Pass 1. Failures are categorized as "STRUCTURAL FAILURES" (Opus-eligible gates) or "CRAFT FAILURES" (Sonnet-resolvable gates), giving revision actionable, tiered gate-failure information.

**Selective Opus trigger:** Pass 1 uses Claude Opus 4.6 instead of Sonnet only when structural-tier gates (those in `opus_eligible_gates`) show elevated failure. Craft-tier gate failures (rhythm, psychologizing, ending, exposition, dialogue, sensory) are always handled by Sonnet, regardless of severity. This tiering reduced Opus costs from 61% to a fraction of total generation cost.

**Pass 1 — Structural** (`v0_raw → v1_structural`):
- Quality audit violations + gate escalation context (mandatory fixes)
- Scene architecture, POV agency, pacing, stakes, turn impact, chapter ending strength
- Post-pass duplicate check with auto-retry

**Pass 2 — Voice & Dialogue** (`v1_structural → v2_creative`):
- Voice distinctiveness, dialogue as action, subtext, period authenticity
- Emotional restraint, interiority through action
- Optional targeted voice mode (diagnose paragraphs, then patch only flagged paragraphs)
- Optional regression-aware retry from pre-voice input when pass-level quality deltas regress
- Post-pass duplicate check with auto-retry

Known limitation from Phase 7 canary:
- Targeted voice revision reduced regression in some chapters but did not reliably prevent repetition inflation in long chapters; repetition remains the primary unresolved quality failure.

**Pass 3 — Polish** (`v2_creative → v3_polish`):
- Lexical/semantic repetition, cross-chapter phrase dedup
- Sentence structure variety, dead weight removal
- Thematic coherence, historical accuracy, continuity

**Quality aggregate:** After each chapter's revision, `aggregate.json` is updated with per-10k-word normalized metrics and flag rates for the 5 tracked quality metrics.

### Stage 6: Assembly & Export

**What it does:** Assembles polished chapters into a final manuscript with title page and table of contents. Saves metadata (generation stats, word counts, cost).

---

## Quality System Architecture

### Detectors (`text_quality.py`)

16+ deterministic Python functions that analyze prose text and return structured findings:

| Detector | What it checks |
|----------|---------------|
| `detect_duplicate_passages` | Near-duplicate paragraphs (SequenceMatcher, 60% threshold) |
| `detect_over_explanation` | Narrator annotation after loaded moments |
| `detect_syntactic_signature` | "The [noun] of a [person] who" overuse |
| `detect_frequency_outliers` | Word/phrase frequency anomalies |
| `detect_within_chapter_repetition` | Repeated n-grams (3/4/5-grams) |
| `detect_sensory_deficit` | Scenes missing non-visual sensory detail |
| `detect_essay_like_passages` | Consecutive abstract paragraphs |
| `detect_rhythm_monotony` | Paragraph/sentence length distribution |
| `detect_dialogue_uniformity` | Overlong, over-composed dialogue lines |
| `detect_metaphor_cluster_saturation` | Financial/mechanical/military metaphor overuse |
| `detect_immediate_jeopardy_deficit` | Scenes missing now-level risk markers + consequence verbs |
| `detect_offstage_opposition_overuse` | Reported opposition > on-page collision ratio |
| `detect_low_propulsion_endings` | Chapter endings lacking external pressure |
| `detect_exposition_drag` | Consecutive exposition blocks suppressing momentum |
| `detect_narrator_psychologizing` | Interior-state verb clusters ("He thought/suspected/realized that") |
| `detect_emotional_control_monotony` | Tactical cognition without vulnerable leakage |

### Gate Functions (`text_quality.py`)

Six `gate_*()` functions wrap detectors with explicit pass/fail thresholds, returning `GateResult` objects:

```python
@dataclass
class GateResult:
    gate_name: str
    passed: bool
    details: dict
    report: str  # Human-readable failure description
```

| Gate | Detector | Threshold config | Tier |
|------|----------|-----------------|------|
| `gate_immediate_jeopardy` | `detect_immediate_jeopardy_deficit` | `gate_max_jeopardy_deficit_scenes` | Structural (Opus-eligible) |
| `gate_offstage_opposition` | `detect_offstage_opposition_overuse` | — | Structural (Opus-eligible) |
| `gate_ending_propulsion` | `detect_low_propulsion_endings` | — | Craft (Sonnet-only) |
| `gate_exposition_drag` | `detect_exposition_drag` | `gate_max_exposition_drag_runs` | Craft (Sonnet-only) |
| `gate_rhythm_monotony` | `detect_rhythm_monotony` | `gate_rhythm_cv_threshold`, `gate_short_sentence_ratio_threshold` | Craft (Sonnet-only) |
| `gate_narrator_psychologizing` | `detect_narrator_psychologizing` | `gate_max_psychologizing_per_1k_words` | Craft (Sonnet-only) |

`run_chapter_gates(text, thresholds)` runs all six gates and returns `dict[str, GateResult]`.

### Opus Escalation Tiering

Gates are classified into two tiers controlled by the `opus_eligible_gates` config list:

- **Structural gates** (default: `offstage_opposition`, `immediate_jeopardy`): These represent scene-design problems that Sonnet struggles to fix. When these fail after retries, the system can escalate to Opus for correction in Stage 4 and structural revision in Stage 5.
- **Craft gates** (all others): These represent prose-execution problems (rhythm, psychologizing, endings, exposition, dialogue, sensory) that Sonnet can fix with proper correction context. They never trigger Opus escalation.

This tiering is enforced in `_apply_chapter_gates()` (Stage 4) and `_build_gate_escalation_context()` (Stage 5), where failures are categorized and labeled accordingly.

### Upstream Craft Contracts

Two original optional fields on the `Scene` model provide upstream enforcement of craft quality:

- **`dominant_sense`** (`str`, default `""`): Which non-visual sense anchors the scene (smell, taste, touch, sound, temperature). Forces sensory grounding beyond the visual default. Populated during scene breakdowns via `scene_breakdowns.j2`, injected into the chapter prompt via `chapter.j2`, verified by `run_scene_contract_checks()` (checks for presence of sensory keywords matching the declared sense).
- **`externalization_gesture`** (`str`, default `""`): The specific physical action revealing the POV character's emotional state without narrator explanation (e.g., "folds and refolds the letter", "sets the glass down without drinking"). Populated during scene breakdowns, injected into chapter prompts, verified by `run_scene_contract_checks()` (fuzzy keyword matching of content words).

### Phase 5: Literary Quality Elevation Contracts

Four new improvements implemented in March 2026, each following the upstream contract → prompt injection → downstream detection pattern. All are behind config flags (off by default) for canary testing.

#### Improvement 1: Voice Differentiation Per POV (`enable_narrative_register`)

**Goal:** Prose register shifts with POV character — Jefferson's expansive naturalism vs Livingston's clipped legalism vs Barbé-Marbois's dry numeracy.

- **Model**: `CharacterProfile.narrative_register` (`dict[str, str]`, default `{}`) — keys: `sentence_rhythm`, `diction_family`, `consciousness_style`, `signature_lens`. Populated by `characters.j2` during world-building.
- **Prompt**: `chapter.j2` renders the POV character's `narrative_register` as a `## NARRATIVE VOICE SPECIFICATION (BINDING)` section when the field is populated. Falls back to the existing hardcoded Polk/Sarah/Walker cases or the generic fallback.
- **Detection**: `detect_register_uniformity(scene_text, narrative_register)` — checks sentence rhythm (avg length vs declared rhythm) and diction family keywords. Added to `run_scene_contract_checks()` when `narrative_register` is on the contract.
- **Config flag**: `enable_narrative_register: false`

#### Improvement 2: Physical Interruption (`enable_physical_interruption_contracts`)

**Goal:** At least one moment per scene where the body intrudes on thought — not symbolic, just the texture of being alive.

- **Model**: `Scene.physical_interruption` (`str`, default `""`) — description of the bodily intrusion. Populated during scene breakdowns via `scene_breakdowns.j2`.
- **Prompt**: `chapter.j2` injects per-scene `physical_interruption` with explicit instructions: include it without rationalizing as symbolic.
- **Detection**: `run_scene_contract_checks()` verifies presence via keyword matching; `detect_symbolic_rationalization(scene_text, interruption_text)` scans the surrounding sentences for rationalization language ("as if", "like the weight of", "a reminder that", "seemed to echo") and flags if the interruption was immediately turned into metaphor.
- **Config flag**: `enable_physical_interruption_contracts: false`

#### Improvement 3: Unresolved Pettiness (`enable_petty_moment_contracts`)

**Goal:** At least one moment per chapter where a character is vain, jealous, or petty and the narrative does NOT rationalize it.

- **Model**: `ChapterOutline.petty_moment` (`str`, default `""`) — chapter-level (not scene-level) description of the petty/trivial moment. Populated during chapter outlines via `chapter_outlines.j2`.
- **Prompt**: `chapter.j2` injects `petty_moment` as a mandatory constraint with explicit anti-rationalization instructions: "Do NOT immediately explain it as strategic. Do NOT have the character reflect on its meaning. Let it sit."
- **Detection**: `detect_pettiness_rationalization(text, petty_moment_text)` locates the petty moment via keyword matching, then scans surrounding sentences for rationalization patterns ("but he knew", "the strategic value", "he reminded himself"). `run_chapter_contract_checks(text, chapter_outline)` is a new function (separate from `run_scene_contract_checks`) that operates at chapter level.
- **Config flag**: `enable_petty_moment_contracts: false`

#### Improvement 4: Scene Ending Variation (`enable_ending_variation_gate`)

**Goal:** Break the "rain, darkness, sealed letter" monotony. Different chapters end in genuinely different tonal registers.

- **Model**: `VALID_ENDING_MODES` in `structure.py` expanded with 5 new modes: `mid_action`, `mundane_detail`, `comic_beat`, `sensory_non_symbolic`, `bureaucratic_pivot`.
- **Prompt**: `chapter.j2` includes a full `## ENDING MODE REFERENCE` section with 2–3 sentence concrete exemplars for each of the 11 ending modes, plus an explicit anti-pattern calling out the "alone in a dark room" default.
- **Detection**: `detect_ending_tonal_monotony(chapter_texts, ...)` computes a "dark density" fingerprint from each chapter's final 250 words and flags consecutive chapters where both endings exceed the dark motif threshold. `gate_ending_tonal_monotony()` wraps this as a cross-chapter gate.
- **Pipeline integration**: `stage4_prose_generation.py` calls `_apply_ending_variation_gate()` after existing quality gates. It loads the prior chapter's v0_raw, builds a 2-chapter dict, runs the gate, and if it fails, runs a targeted ending correction pass.
- **Config flags**: `enable_ending_variation_gate: false`, `gate_max_consecutive_similar_endings: 2`, `gate_ending_similarity_threshold: 0.50`

#### New Functions in `text_quality.py`

| Function | What it checks |
|----------|---------------|
| `detect_register_uniformity(scene_text, narrative_register)` | Whether prose rhythm and diction match the declared narrative register |
| `detect_symbolic_rationalization(scene_text, interruption_text)` | Whether a physical interruption was immediately turned into metaphor |
| `detect_pettiness_rationalization(text, petty_moment_text)` | Whether a petty moment was immediately rationalized or redeemed |
| `run_chapter_contract_checks(text, chapter_outline)` | Chapter-level contract enforcement (currently: petty_moment presence + non-rationalization) |
| `detect_ending_tonal_monotony(chapter_texts)` | Consecutive chapter endings with the same dark/reflective tonal fingerprint |
| `gate_ending_tonal_monotony(chapter_texts)` | Gate wrapping ending tonal monotony detector |

#### New Config Flags (Phase 5)

| Flag | Default | Description |
|------|---------|-------------|
| `enable_narrative_register` | `false` | Inject narrative_register into chapter prompts and verify via contract checks |
| `enable_physical_interruption_contracts` | `false` | Enforce physical_interruption scene field and detect symbolic rationalization |
| `enable_petty_moment_contracts` | `false` | Enforce petty_moment chapter field and detect rationalization |
| `enable_ending_variation_gate` | `false` | Run cross-chapter ending tonal monotony gate after each chapter |
| `gate_max_consecutive_similar_endings` | `2` | How many similar consecutive endings to tolerate before gate fails |
| `gate_ending_similarity_threshold` | `0.50` | Dark motif density threshold for ending similarity (lower = more sensitive) |

### Loop Evaluator (`loop_evaluator.py`)

Codifies the convergence governance that was previously manual:

- **`LoopSnapshot`** — captures 5 metrics at end of a loop iteration
- **`LoopEvaluation`** — comparison result between two snapshots
- **`evaluate_loop()`** — applies 3-of-5 improvement rule, tracks consecutive passes, declares convergence at 2 consecutive passes
- **`compute_loop_metrics()`** — computes 5 core metrics from per-chapter quality reports

### 5 Tracked Quality Metrics

| Metric | Type | Direction |
|--------|------|-----------|
| `immediate_jeopardy_deficit_scenes_per_10k_words` | Normalized rate | Lower is better |
| `exposition_drag_runs_per_10k_words` | Normalized rate | Lower is better |
| `ending_propulsion_deficit_flag_rate` | Per-chapter flag | Lower is better |
| `offstage_opposition_overuse_flag_rate` | Per-chapter flag | Lower is better |
| `dialogue_uniformity_flag_rate` | Per-chapter flag | Lower is better |

---

## Key Design Decisions

### 1. Jinja2 Prompt Templates
All LLM prompts are Jinja2 templates in `sovereign_ink/prompts/templates/`. Separates prompt engineering from Python logic.

### 2. Pydantic Models for Everything
Every data structure is a Pydantic model. `generate_structured()` parses JSON responses directly into models with validation. Schema validation is the cheapest quality control.

### 3. Atomic Writes with File Locking
All state persistence uses temp-file-then-rename. Project-level advisory lock (`fcntl`) prevents concurrent runs.

### 4. Stage-Level Resumability
Each stage tracks progress through `StageProgress`. Re-running resumes from the last incomplete sub-step. World building saves each sub-component independently. Scene breakdowns save cumulatively chapter-by-chapter.

### 5. Configurable Model Assignment Per Stage
Each stage can use a different model (configured in `generation_config.yaml`). Current routing: Sonnet 4.6 for quality-critical work, Haiku 4.5 for utility tasks, selective Opus 4.6 for flagged structural tasks.

### 6. Cross-Chapter Continuity System
Continuity ledger tracks: timeline, character knowledge, political capital, relationships, open threads. Initialized in Stage 3, updated after each chapter in Stage 4.

### 7. Phrase Deduplication
After each chapter, notable phrases are extracted and banned. Subsequent chapters and polish revision receive these as "do not reuse" instructions.

### 8. Three Consolidated Revision Passes (Down from Seven)
Structural, voice/dialogue, polish — a 57% reduction in API calls, but quality coverage is not yet equivalent in practice. Phase 7 showed repetition regressions can still worsen after revision in long chapters.

### 9. Pre-Generation Quality Gates (New)
Shifts quality enforcement from post-hoc revision to pre-save acceptance gates in Stage 4. Gates detect → retry with correction context → persist results → escalate to revision if still failing. Configurable per-project via `generation_config.yaml`.

### 10. Project-Local Config Override
Orchestrator merges `<project>/generation_config.yaml` over workspace root config, enabling per-project tuning (e.g., gates enabled for one project, disabled for another).

### 11. Opus Escalation Tiering
Not all gate failures justify the cost of Opus. Structural gates (offstage opposition, immediate jeopardy) represent scene-design problems the LLM struggles to fix — these can escalate to Opus. Craft gates (rhythm, psychologizing, endings, exposition) represent prose-execution problems Sonnet can handle with proper correction context. The `opus_eligible_gates` config list controls which gates can trigger Opus, reducing Opus cost from 61% of total to a fraction.

### 12. Upstream Craft Contracts
Rather than only detecting craft problems after generation, the system now specifies craft constraints *before* generation at the scene level. `dominant_sense` and `externalization_gesture` fields on the Scene model are populated during structural planning, injected into generation prompts, and verified in prose. This shifts craft enforcement upstream — cheaper to prevent than to fix in revision.

### 13. Self-Healing Convergence Escalation
Rather than failing and requiring manual config intervention when a chapter cannot converge, the `next` command progressively relaxes constraints through 4 escalation levels. This guarantees every chapter eventually completes (at worst with quality gates disabled). Config mutation is in-memory only — the project's YAML is never modified, and original config is always restored after the chapter completes. This eliminates the operational burden of babysitting long generation runs.

### 14. Scene Breakdown Pre-Flight
When `max_chapters` is increased after initial structural planning (Stage 3), new chapters lack scene breakdowns. Rather than failing with an opaque "Missing scene breakdown" error, the `next` command now checks for a missing breakdown before entering the convergence loop and generates it on the fly. This makes the pipeline robust to post-hoc chapter count changes.

---

## LLM Integration

### Client Architecture (`llm/client.py`)

The `LLMClient` wraps the Anthropic Messages API with three generation methods:

- **`generate()`** — Synchronous, non-streaming. Structured outputs and revision.
- **`generate_structured()`** — Parses JSON into Pydantic models. Retries up to 3 times on parse failure with self-correction.
- **`generate_streaming()`** — Streaming with `on_chunk` callback. Used for prose generation.

### Retry Logic
Exponential backoff (`retry_base_delay * 2^attempt`), configurable max retries (default 3). Handles rate limits, 5xx errors, connection errors, timeouts.

### Cost Tracking
Cumulative input/output tokens tracked per-call with model-specific rates from config. Pipeline state persists cumulative cost.

---

## Configuration

All tuneables live in `generation_config.yaml`:

```yaml
# Models
model_structural_planning: "claude-opus-4-6"
model_prose_generation: "claude-sonnet-4-6"
model_revision_structural: "claude-sonnet-4-6"
model_revision_structural_opus: "claude-opus-4-6"
model_utility: "claude-haiku-4-5-20251001"

# Temperature
temperature_prose: 0.85
temperature_revision: 0.6

# Chapter targets
target_words_per_chapter: 3000
max_chapters: null

# Revision
num_revision_passes: 3
enable_selective_opus_structural_revision: true
immediate_jeopardy_opus_threshold_per_10k_words: 2.5

# Quality gates (pre-save acceptance) — off by default, on per-project
enable_quality_gates: false
gate_strict_structure_validation: false
gate_max_chapter_retries: 1
gate_max_ending_retries: 2
gate_max_jeopardy_deficit_scenes: 1
gate_max_exposition_drag_runs: 1
gate_rhythm_cv_threshold: 0.45
gate_short_sentence_ratio_threshold: 0.10
gate_max_psychologizing_per_1k_words: 5.0

# Opus escalation tiering — only structural gates can trigger Opus
opus_eligible_gates:
  - "offstage_opposition"
  - "immediate_jeopardy"

# Pressure contracts — scene-level structural enforcement
enable_pressure_contracts: false
strict_pressure_contract_validation: false
gate_max_scene_retries: 2
gate_opus_scene_escalation: true

# Quality checkpoint
enable_quality_checkpoint: false
checkpoint_after_chapters: [2]

# Convergence loop (used by `next` command)
next_max_convergence_attempts: 12     # Max attempts per escalation level
next_max_identical_failure_streak: 3  # Identical failures before escalating
stage4_scene_count_tolerance: 0       # Tolerance for scene count mismatch (0 = strict)
stage4_max_total_repair_attempts: 12  # Max repair attempts within a convergence attempt

# Validators (can be disabled by escalation)
semantic_validator_enabled: true
adversarial_verifier_enabled: true
```

---

## Cost Model

| Operation | Model | Approximate cost |
|-----------|-------|-----------------|
| Synopsis generation | Sonnet | $0.02 |
| World building (4 calls) | Sonnet | $0.18 |
| Structural planning (15+ calls) | Sonnet | $0.40 |
| Chapter generation (1 chapter) | Sonnet 4.6 (streaming) | $0.11 |
| Chapter bookkeeping (3 calls) | Haiku | $0.04 |
| Quality audit | Sonnet 4.6 | $0.08 |
| Quality gates (deterministic) | None (Python only) | $0.00 |
| Gate correction retry (if triggered) | Sonnet 4.6 | $0.10 |
| Revision pass 1: structural | Sonnet 4.6 (or Opus if flagged) | $0.13–$0.50 |
| Revision pass 2: voice/dialogue | Sonnet 4.6 | $0.14 |
| Revision pass 3: polish | Sonnet 4.6 | $0.10 |
| **Total per chapter (with gates, no Opus spike)** | | **~$0.50–$0.80** |
| **Total per chapter (with gates + Opus structural)** | | **~$0.80–$1.20** |

### Comparative Cost Data (Louisiana Purchase)

| Project | Chapters | Total cost | Cost/ch | Opus % of cost |
|---------|----------|-----------|---------|----------------|
| `contracts` (4 gates + pressure) | 6 | ~$14.66 | ~$2.44 | ~61% |
| `craft_gates` (6 gates + tiering) | 4 | ~$9.50 | ~$2.38 | Reduced (structural-only) |

Opus tiering eliminated unnecessary Opus calls for craft-level failures, saving significant cost without measurable quality regression.

**Self-healing escalation cost note:** When escalation triggers, a chapter may be generated multiple times across levels. Louisiana chapter 11 cost ~$10.30 total (level 0 failed 3 times, level 1 succeeded). Worst case (escalating to level 3 with quality gates disabled) could cost 4-5x a normal chapter. This is an acceptable trade-off for guaranteed convergence without manual intervention.

---

## CLI Reference

```bash
# Create a new project (interactive setup + synopsis selection)
sovereign-ink new -p <project_dir>

# Generate the next polished chapter (auto-runs stages 1-3 if needed)
sovereign-ink next -p <project_dir>

# Run the full batch pipeline
sovereign-ink run -p <project_dir>

# Check pipeline progress
sovereign-ink status -p <project_dir>

# Assemble manuscript from polished chapters
sovereign-ink export -p <project_dir>

# Publish polished chapters into repo-level published/ (requires novels: mapping)
sovereign-ink publish -p <project_dir>
sovereign-ink publish --all
```

---

## Web App Publication Workflow (HistoryFM)

The frontend reads static content from `frontend/content/novels`, which is synced from repo-level `published/`.

For a new or updated chapter to appear on the web app:

```bash
# 1) Generate (or continue generating) polished chapters
sovereign-ink next -p <project_dir>

# 2) Ensure the novel exists in generation_config.yaml -> novels:
#    (project_dir, slug, title, description), then publish
sovereign-ink publish -p <project_dir>
# or publish all configured novels:
# sovereign-ink publish --all

# 3) Sync published content into frontend/content/novels
bash scripts/sync-content.sh

# 4) Rebuild/start frontend
cd frontend
npm run build
npm run start
# (or npm run dev during development)
```

Notes:
- The sync script lives at repo root: `scripts/sync-content.sh`.
- If the novel is not listed under `novels:` in `generation_config.yaml`, `publish` will skip/fail for that project.
- For Tyler, uncomment/add the `john_tyler_succession_12ch` mapping under `novels:` before publishing.

---

## Codebase Map

```
sovereign_ink/
├── cli/commands.py              # 6 CLI commands (new, run, next, status, export, publish)
├── llm/client.py                # Anthropic API client (generate, streaming, structured, retry, cost)
├── models/
│   ├── novel_spec.py            # NovelSpec (user input)
│   ├── world_state.py           # HistoricalContext, CharacterProfile, Institution, EraToneGuide, WorldState
│   ├── structure.py             # ActStructure, ChapterOutline, Scene, SceneBreakdown, NovelStructure
│   │                            # + VALID_ENDING_MODES, VALID_REGISTERS, validate_pressure_architecture()
│   │                            # + Scene.dominant_sense, Scene.externalization_gesture (craft contracts)
│   ├── continuity.py            # ContinuityLedger (timeline, knowledge, relationships, threads)
│   └── pipeline.py              # PipelineState, StageProgress, ChapterDraft, RevisionResult
├── pipeline/
│   ├── base.py                  # PipelineStage abstract base (state management, resumability)
│   ├── orchestrator.py          # 6-stage pipeline driver + _load_merged_config() for project-local overrides
│   └── stages/
│       ├── stage1_setup.py      # Interactive setup + synopsis selection
│       ├── stage2_world_building.py   # 4-call world construction
│       ├── stage3_structural_planning.py  # Act/chapter/scene planning + continuity init + validation
│       ├── stage4_prose_generation.py     # Chapter writing + quality gates + gate retries + bookkeeping
│       ├── stage5_revision.py             # 3-pass revision + gate escalation context + selective Opus
│       └── stage6_assembly.py             # Manuscript assembly + metadata
├── prompts/
│   ├── renderer.py              # Jinja2 template loader/renderer
│   └── templates/
│       ├── system_prompt.j2     # Master novelist persona
│       ├── setup/synopsis_options.j2
│       ├── world_building/{historical_context,characters,institutions,era_tone_guide}.j2
│       ├── structure/{act_structure,chapter_outlines,scene_breakdowns}.j2
│       ├── generation/chapter.j2   # Main chapter generation prompt (Five Laws + constraints)
│       ├── revision/{structural,voice_and_dialogue,polish,quality_audit}.j2
│       └── utility/{chapter_summary,continuity_update,consistency_check}.j2
├── state/manager.py             # All disk I/O (atomic writes, file locking, save/load, gate results)
└── utils/
    ├── config.py                # GenerationConfig (YAML loader, defaults, gate thresholds)
    ├── text_quality.py          # 16+ detectors + GateResult + 6 gate_*() functions + run_chapter_gates() + run_scene_contract_checks()
    ├── loop_evaluator.py        # LoopSnapshot, LoopEvaluation, evaluate_loop(), convergence logic
    ├── phrase_tracker.py        # Cross-chapter phrase extraction and deduplication
    ├── token_counter.py         # tiktoken-based counting and cost estimation
    └── logging.py               # Structured logging setup
```
