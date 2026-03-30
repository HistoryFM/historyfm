# Tech Blog Outline — Building Sovereign Ink

**Working title:** "From Pipeline to Prose: Building an Autonomous Historical Novel Generator with Claude"

**Alternate titles:**
- "Can an LLM Write Great Historical Fiction? What We Learned Building Sovereign Ink"
- "Detection, Gates, and Contracts: Engineering Quality into AI-Generated Novels"

---

## Thesis

We built a system that generates full-length historical novels autonomously. It works. The prose is coherent, historically grounded, and sometimes impressive. But getting from "works" to "great" required nine phases of architectural iteration, and each phase taught us something about the fundamental gap between detecting quality problems and fixing them. This is the story of what we tried, what failed, what worked, and what remains stubbornly out of reach.

---

## Current Program Status (March 2026)

**Execution state:**
- `louisiana_purchase_phase6` complete (baseline canary)
- `louisiana_purchase_phase7` complete (5 chapters)
- `louisiana_purchase_phase8` complete (5 chapters)
- `louisiana_purchase_phase9` not started yet (next recovery canary)

**Phase 8 measured outcomes vs Phase 7:**
- Repetition improved significantly (`103.7449 -> 52.0087` per 10k words)
- Immediate jeopardy deficits improved (`1.6772 -> 1.2286` per 10k words)
- Sensory deficits improved (`6 -> 5` total)
- Ending propulsion regressed (`0.2 -> 0.4` flag rate)
- Exposition drag regressed strongly (`0.7188 -> 2.4571` per 10k words)
- Chapter length mean dropped (`8347 -> 4884`) but variance quality remains unstable

**Current release verdict:**
- Not release quality yet.
- Two release blockers remain: chapter completion integrity (truncation-like endpoints in some polished chapters) and unreliable ending propulsion recovery.
- Phase 9 is a deterministic completion + momentum recovery iteration (surgical fixes, then a new 5-chapter canary and re-evaluation).

**Blog positioning update:**
- The narrative should explicitly include that major aggregate gains can coexist with new regressions.
- Emphasize that quality work is not monotonic: one metric can improve while another collapses unless non-regression constraints are enforced.

---

## Phase 0: Design and Bootstrap (Feb 16, 2026)

**What happened:** Designed and implemented the entire system from product requirements to working code in a single session.

**Architecture decisions:**
- 6-stage pipeline: Interactive Setup → World Building → Structural Planning → Prose Generation → Revision Pipeline → Assembly & Export
- Vanilla Python + Anthropic SDK — no LangGraph, no CrewAI, no agent frameworks. The reasoning: novel generation is a sequential pipeline with well-defined stages, not a graph of autonomous agents. Frameworks would add complexity without benefit.
- Pydantic models for every data structure — schema validation as the cheapest quality control
- Jinja2 templates for all prompts — separates prompt engineering from Python logic
- Atomic state persistence with file locking — temp-file-then-rename for crash safety
- Stage-level resumability — each stage tracks progress independently, can resume after failure

**The original revision pipeline:** 7 passes (structural, escalation, emotional, dialogue, repetition, thematic, ending). This would later prove to be a significant problem.

**Model strategy:** Opus/Sonnet for creative work, Sonnet for structural planning, Haiku for utility tasks (summaries, continuity updates, phrase extraction).

**Blog angle:** The decision to use vanilla Python instead of an agent framework. What a 6-stage sequential pipeline looks like vs. what an agent graph would look like. Why Pydantic models matter for LLM output parsing.

**Key transcript:** [Initial Design and Planning](f843477f-ddad-4bb1-a557-2ad6783f6661), [Full Implementation](bf83f12c-1b96-4cfc-bebe-38b25a2d7a9e)

---

## Phase 1: First Run and Bug Fixing (Feb 17-18, 2026)

**What happened:** Ran the pipeline end-to-end for the first time. Everything broke in instructive ways.

**Bug 1 — ERA_TONE_GUIDE JSON parsing:**
Claude returned malformed `forbidden_terms` like `"impact" as verb` instead of `"impact (as verb)"`. The JSON parser choked. Fix: added `_repair_json()` regex cleanup and tightened the prompt to specify exact format.

**Bug 2 — Wrong Haiku model name:**
Used `claude-haiku-4-20250414` which returned 404. The correct model ID was `claude-haiku-4-5-20251001`. Anthropic's model naming convention is not intuitive.

**Bug 3 — Stage 4 resume logic:**
When prose generation was interrupted, chapters with existing prose but missing summaries/continuity updates were skipped on resume instead of completing the missing bookkeeping steps. Fix: check for each sub-step independently.

**Bug 4 — No graceful shutdown:**
Killing the process mid-chapter left corrupted state. Fix: SIGINT handler that completes the current chapter before stopping.

**Blog angle:** The gap between "the pipeline works in theory" and "the pipeline survives contact with the API." JSON parsing fragility with LLMs. Model naming gotchas. The importance of sub-step resumability.

**Key transcript:** [First Run Bug Fixes](8f056b1d-df80-4ff5-af87-84175a8f6aa0)

---

## Phase 2: First Quality Assessment — "The Dark Horse" (Feb 21-25, 2026)

**What happened:** Generated a full novel about the Polk presidency ("The Dark Horse") to assess output quality. The results were sobering.

**The word-count catastrophe:**
Revision Pass 1 (structural) cut Chapter 1 by ~70%. The revision prompt told the LLM to "tighten" and "remove filler" — the LLM interpreted this as permission to gut the chapter. The prose went from 3,000+ words to under 1,000. This was a fundamental problem: revision passes designed to improve quality were destroying content.

**Essay-like prose:**
Chapters read like analytical essays about history rather than narrative fiction. Characters explained their situations to the reader instead of living through them. The prose was intelligent and accurate but had zero narrative drive.

**Historical title inaccuracy:**
Characters were referred to by titles they hadn't held yet. "Vice President Adams" in scenes set before his vice presidency. "Secretary Madison" in scenes before his appointment. Fix: structured `TitleTenure` model with date ranges, resolved per-chapter based on the chapter's year.

**Created `sovereign-ink next`:**
Realized that batch mode (generate all chapters, then revise all chapters) made debugging impossible. Created incremental mode: generate one chapter, run all gates and revisions, output a fully polished chapter. This became the recommended workflow.

**Blog angle:** The first honest quality assessment. When revision makes things worse. The title accuracy problem as a case study in temporal reasoning failures. Why incremental generation beats batch.

**Key transcripts:** [Polk Novel Proxy Run](d22872e8-1a05-4abe-a2e6-2160765ad617), [NextSteps Implementation](4dd05db2-5b88-47f7-ba8f-0f39b1326642), [Pipeline Run with max_chapters](4ff77ca8-43a5-4edd-a818-d5d3b17a0454)

---

## Phase 3: Revision Pipeline Overhaul (Feb 21-23, 2026)

**What happened:** Consolidated 7 revision passes down to 3. Added cross-chapter phrase tracking.

**7 → 3 passes:**
The original 7 passes (structural, escalation, emotional, dialogue, repetition, thematic, ending) were causing cumulative quality degradation. Each pass gave the LLM an opportunity to introduce new problems while fixing old ones. The prose got shorter and blander with each pass. Consolidated to 3 focused passes: Structural → Voice & Dialogue → Polish. This was a 57% reduction in API calls with equivalent or better quality.

**Cross-chapter phrase tracking:**
The LLM reuses distinctive phrases across chapters — the same metaphor, the same character gesture, the same atmospheric description. Built a phrase extraction system (Haiku call after each chapter) that maintains a "banned phrases" list injected into subsequent chapter prompts and the polish revision pass.

**Quality checkpoint system:**
Added optional pause-and-assess checkpoints after configurable chapter counts (e.g., after chapter 2). Allows human review before committing to the full novel.

**Blog angle:** When more revision passes make prose worse. The counterintuitive insight that fewer, more focused passes outperform comprehensive multi-pass editing. The phrase deduplication problem in long-form generation.

**Key transcript:** [Quality Improvement Plan](1a5cd8e2-83f5-493b-9f51-099fc40be6ff)

---

## Phase 4: Building the Detector Arsenal (Feb 26, 2026)

**What happened:** Built 15+ deterministic Python detectors to identify specific prose quality problems.

**The detectors:**
- `detect_duplicate_passages` — near-duplicate paragraphs (SequenceMatcher, 60% threshold)
- `detect_over_explanation` — narrator explaining after loaded moments ("He realized that what she had said meant...")
- `detect_syntactic_signature` — "The [noun] of a [person] who" overuse (a distinctive LLM tic)
- `detect_frequency_outliers` — vocabulary crutches
- `detect_sensory_deficit` — scenes lacking non-visual sensory detail
- `detect_rhythm_monotony` — uniform paragraph/sentence length distribution
- `detect_dialogue_uniformity` — overlong, over-composed dialogue lines
- `detect_metaphor_cluster_saturation` — financial/mechanical/military metaphor overuse
- And 7+ more covering repetition, essay-like passages, emotional control monotony

**How they were used (initially):**
Detector outputs were injected into the structural revision prompt as mandatory fix context. The revision pass received a structured report of exactly what was wrong and where.

**Key insight — detection ≠ correction:**
The detectors worked beautifully. They reliably identified the exact problems. But telling the LLM "fix this" in a revision prompt often produced the same structural patterns with surface-level rewording. The LLM's default mode for political historical fiction is narration *about* conflict rather than dramatization *of* conflict, and no amount of "fix the offstage opposition" in a revision prompt changed that default.

**Blog angle:** Building a quality measurement system for prose. The regex-and-statistics approach to literary analysis. The fundamental gap between detection and correction — the most important lesson of the entire project.

**Key transcript:** [P0-P9 Quality Detectors](8080510e-2928-4420-b934-9c891a2af61d)

---

## Phase 5: A/B Testing and the Compulsion Schema (Mar 1-2, 2026)

**What happened:** Ran a formal A/B test with a "compulsion schema" designed to force narrative drive.

**The compulsion schema:**
Added structured fields to chapter outlines and scene breakdowns: `immediate_risk`, `on_page_opposing_move`, `emotional_blind_spot`, `hard_reveal`, `soft_reversal`, etc. The idea: if the structural plan explicitly specifies what the opposing force does on-page and what the immediate risk is, the generated prose should dramatize it rather than report it.

**The dual-track experiment:**
- Track A (`louisiana_purchase_loop_ab`): Continuity track — 8 chapters, iterating in 2-chapter loops
- Track B (`louisiana_purchase_opus_ab`): Reboot track — 4 chapters, Opus for structural planning
- Each loop: generate 2 chapters → recompute 5 metrics → compare → implement 1-3 fixes → repeat
- Acceptance gate: 3 of 5 metrics must improve or hold

**The 3-of-5 rule:**
Codified the acceptance criteria. Five metrics tracked: immediate jeopardy deficit, exposition drag, ending propulsion deficit, offstage opposition overuse, dialogue uniformity. An iteration "passes" if at least 3 metrics improve or hold. Convergence declared after 2 consecutive passes.

**Selective Opus policy:**
Enabled Opus only for targeted high-leverage tasks: structural planning on fresh track initialization, structural revision on flagged chapters. Avoided always-on Opus.

**Results — no stable winner:**
Track A met the loop gate on iteration A4 (3/5 improved). Track B did not meet it on B2. No stable winner. The same structural blockers (offstage opposition, jeopardy inconsistency) persisted across both tracks. Opus helped individual chapters but did not resolve system-level convergence. Cost increases were significant without proportional quality gains.

**Blog angle:** Formal A/B testing for novel generation. Why the compulsion schema was necessary but insufficient. The 3-of-5 convergence rule as a governance mechanism. The Opus cost-quality tradeoff. When architectural solutions do not converge.

**Key transcripts:** [A3/B1 Loop Execution](64c2e75a-b15b-4185-9cdc-e5fd2dfeb7e4), [P10-P17 Schema + Sprint A](67881564-0783-4015-a025-b0dc18e07c4a), [Quality Loop for dark_horse_ab](1126de61-687c-4ea2-9a8a-300eb80a143c)

---

## Phase 6: Pre-Generation Quality Gates (Mar 3-4, 2026)

**What happened:** Architectural pivot from post-hoc revision to pre-generation enforcement.

**The insight:**
Revision-based quality control hits a ceiling because the LLM rewrites in the same patterns it originally generated. The alternative: gate the output *before* saving it, and if it fails, retry generation with correction context that tells the LLM exactly what went wrong.

**Four acceptance gates:**
- `gate_immediate_jeopardy` — scenes must have concrete now-level risk markers and consequence verbs
- `gate_offstage_opposition` — offstage mentions must not dominate on-page conflict markers
- `gate_ending_propulsion` — final 250 words must have unresolved external pressure
- `gate_exposition_drag` — consecutive exposition-heavy paragraphs must not exceed threshold

**The gate flow:**
1. Generate chapter via streaming
2. Run 4 deterministic gates on the raw text
3. If any fail: inject failure context and regenerate (up to `gate_max_chapter_retries`)
4. Save the best version (pass or fail) as v0_raw
5. If gates still failed after retries: format failures as escalation directives for Stage 5 revision

**Correction exemplars:**
Gate failure reports describe *what's wrong* but the LLM needs *what right looks like*. Added before/after passage pairs in `_GATE_CORRECTION_EXEMPLARS` showing the transformation from problematic to corrected prose.

**Results — Louisiana Purchase gated canary (6 chapters):**

| Gate | Gated (6ch) | Baseline (6ch) | Verdict |
|------|-------------|----------------|---------|
| Ending Propulsion | 5/6 (83%) | 4/6 (66%) | Improved |
| Offstage Opposition | 1/6 (16%) | 0/6 (0%) | Improved |
| Exposition Drag | 4/6 (66%) | 4/6 (66%) | Same |
| Immediate Jeopardy | 1/6 (16%) | 2/6 (33%) | Regressed |
| **Overall** | **11/24 (45%)** | **10/24 (41%)** | **+4pp** |

**Key learning:**
The gating infrastructure works mechanically — it detects, retries, escalates, and persists. But the LLM's ability to *fix* what the gates detect is limited. The retry produces similar patterns. +4pp improvement is real but modest.

**Blog angle:** The shift from "fix it after" to "don't accept it until it's right." Why correction exemplars matter more than correction instructions. The limits of retry-based quality improvement. The 4pp result — is it worth the engineering?

**Key transcript:** [Novel Quality Convergence Plan](0abc4c7f-ef77-4f79-9c97-3efc0b1a1ffe)

---

## Phase 7: Pressure Contracts (Mar 5-6, 2026)

**What happened:** Moved quality enforcement further upstream — from prose generation (Stage 4) to scene architecture (Stage 3).

**The architectural insight:**
Offstage opposition is a scene *design* problem, not a prose *execution* problem. The scene breakdown says "opposition: Talleyrand's evasion" but the LLM narrates about Talleyrand instead of putting him in the room. The fix needs to happen at scene design, not prose generation. If the scene plan explicitly says "Talleyrand is physically present and does X on-page," the generated prose is far more likely to dramatize it.

**Pressure contract fields on the Scene model:**
- `opponent_present_on_page` — is the antagonist physically in the scene?
- `opponent_move` — the specific action the opponent takes
- `pov_countermove` — the POV character's response
- `deadline_or_clock` — the time pressure forcing action
- `required_end_hook` — how the scene must end to pull the reader forward

**Contract-constrained generation:**
`chapter.j2` injects pressure contract fields per-scene as binding constraints. `run_scene_contract_checks()` in `text_quality.py` verifies that contract elements actually appear in the generated prose.

**Political jeopardy calibration:**
The jeopardy detector was calibrated for physical danger (risk markers like "blade," "threat," "death"). Political/diplomatic chapters have real stakes (careers, alliances, constitutional crises) that don't register as jeopardy. Expanded the detector to recognize institutional/political risk language. This was a recurring calibration challenge.

**The cost problem emerges:**
Analysis of `louisiana_purchase_contracts` (6 chapters, $14.66 total) revealed that 61% of generation cost came from Opus escalation. Every chapter with *any* gate failure triggered Opus for structural revision — even when the failures were craft-level issues (rhythm, exposition) that Sonnet could fix. This motivated Phase 8.

**Blog angle:** The upstream principle — quality is cheaper to enforce before generation than to fix after. Scene-level contracts as a design pattern. The political jeopardy calibration problem: when detectors are genre-biased. The Opus cost surprise.

**Key transcript:** [Pressure Contracts + Dual-Gate Plan](42e206bb-4582-48d3-969d-0001a616e25d), [Contracts Cost Analysis](d83be8db-d0cf-45c8-999f-dda85bbd991b)

---

## Phase 8: Craft Gates and Opus Tiering (Mar 7-8, 2026)

**What happened:** Added two new quality gates, split gates into structural vs. craft tiers, and added upstream craft contracts.

**Two new gates:**
- `gate_rhythm_monotony` — wraps the existing `detect_rhythm_monotony` detector. Checks paragraph length coefficient of variation (≥ 0.45) and short sentence ratio (≥ 0.10). Enforces that prose isn't all uniform-length analytical paragraphs.
- `gate_narrator_psychologizing` — new detector + gate. Pattern-matches narrator interior-state verb clusters ("He thought/suspected/realized/understood that", "He was not certain whether", "It occurred to him that"). Counts density per 1k words. Enforces that the narrator shows rather than tells psychology.

**Opus escalation tiering:**
Gates classified into two tiers:
- **Structural** (Opus-eligible): `offstage_opposition`, `immediate_jeopardy` — scene-design problems Sonnet struggles to fix
- **Craft** (Sonnet-only): `rhythm_monotony`, `narrator_psychologizing`, `ending_propulsion`, `exposition_drag`, `dialogue_uniformity`, `sensory_deficit` — prose-execution problems Sonnet handles with proper correction context

Controlled by `opus_eligible_gates` config list. Enforced in `_apply_chapter_gates()` (Stage 4) and `_build_gate_escalation_context()` (Stage 5) where failures are categorized as "STRUCTURAL FAILURES" or "CRAFT FAILURES."

**Upstream craft contracts:**
Two new optional fields on the Scene model:
- `dominant_sense` — which non-visual sense anchors this scene (smell, taste, touch, sound, temperature)
- `externalization_gesture` — the specific physical action that reveals POV emotional state without narrator explanation

Populated during scene breakdowns, injected into chapter prompts, verified by `run_scene_contract_checks()`.

**Comparison run — craft gates vs contracts (4 chapters each):**
Modest improvement in sensory grounding (multi-sensory vs visual-dominant), externalization consistency (gesture-driven vs inconsistent), and scene tightness (Ch3: 6,773 words with 0 retries vs 7,221 words). Opus cost reduced from 61% of total to structural-only. Total: ~$9.50 for 4 chapters vs ~$14.66 for 6 chapters.

**Test debugging:**
The rhythm monotony gate initially had a test failure: `detect_rhythm_monotony()` returned `None` because the test fixture had insufficient sentences (7 vs. required minimum of 20). The detector's precondition silently returned `None` for short texts. Rewrote the test fixture with helper functions to generate sufficient uniform prose. A reminder that detector preconditions need explicit documentation.

**Blog angle:** The tiering principle — not all quality failures are equal in cost to fix. Upstream craft contracts as pre-generation sensory enforcement. The test debugging story as a case study in detector preconditions. Cost impact of model selection tiering.

**Key transcript:** [Craft Gates Implementation](64b2c3ab-83b0-404c-a628-e3d0f2e25294)

---

## Phase 9: Literary Assessment — "Good but Not Great" (Mar 8, 2026)

**What happened:** Close reading of all polished chapters from both projects. Honest assessment of where the system stands.

**The question:** Is this great historical fiction?

**The answer:** No. It is good. It is competent, occasionally impressive historical fiction. But it is not in the tier of Hilary Mantel, Robert Caro's narrative sections, or Gore Vidal's Narratives of Empire.

**Six shortcomings identified:**

1. **Prose register monotony.** Every chapter is written in the same controlled, analytical, slightly portentous voice. Jefferson sounds like Livingston sounds like Barbé-Marbois. The diction varies slightly but the underlying sensibility is identical. In Wolf Hall, Cromwell's mind is quick, concrete, financial. More's is rhetorical, theological, circling. The prose itself changes gears. The system has one voice and applies it to every POV character.

2. **Decorative physicality.** Scenes contain sensory detail — coal smoke, tallow, wet stone — but these details arrive as inventory items, not as experiences that modify or interrupt thought. In Mantel, rain literally changes what Cromwell does next. In the generated novel, rain *decorates* the intellectual moment rather than *contesting* it.

3. **Absent bodies.** Characters do not eat with pleasure, sweat, fidget, scratch, feel irrelevant pain, or catch themselves in undignified postures. They are minds in period costume. Physicality is always symbolic (cold knuckles = weight of decision). Great historical fiction includes irreducible, meaningless, embarrassing *body*.

4. **No unresolved pettiness.** Every character operates at peak intelligence and moral seriousness. No one does something genuinely stupid or selfish in a way the narrative does not immediately contextualize as strategic. This produces admiration without recognition.

5. **Slavery anachronism.** Characters think about slavery with 21st-century moral consciousness. Barbé-Marbois meditates on "the two hundred thousand souls whose condition the treaty would transfer" rather than framing it as a policy concern about Haitian precedent destabilizing Louisiana. The LLM defaults to how a modern reader wants historical characters to think, not how they probably actually thought.

6. **Scene ending monotony.** Every chapter closes on the same note: a character alone in a dark room, contemplating a sealed letter or the rain or the gap between knowledge and action. Each ending is well-written, but they are all the *same kind* of well-written. No sentence-level gate can detect this.

**Blog angle:** The honest reckoning. Comparing generated prose to the best of the genre. What "good" looks like vs. what "great" looks like, and why the gap is architectural rather than incremental. The LLM's one-voice problem. The slavery anachronism as a case study in LLM temporal perspective.

**Key transcript:** [Craft Gates Implementation](64b2c3ab-83b0-404c-a628-e3d0f2e25294)

---

## Phase 10: Outline Compliance Failure (Chapter 6 Postmortem) (Mar 2026)

**What happened:**  
During full Phase 11 generation, chapter 6 passed through the pipeline despite missing required outline-level beats and scene-contract integrity. This exposed a core architectural gap: we had quality gates, but not strict outline-compliance enforcement.

**Concrete failure case (chapter 6):**
- Required chapter beats from outline were not reliably realized (hard reveal, on-page opposing move timing, petty moment fidelity).
- Scene architecture drifted beyond planned structure (extra unplanned extension scene behavior).
- Scene contract checks reported failure for scene 4.
- Chapter gate retries exhausted with failures still present.
- Pipeline still proceeded and saved output.

**What gates ran (and why they were insufficient):**
- Pre-save chapter gates (jeopardy/offstage opposition/ending propulsion/exposition drag/rhythm/psychologizing/completion).
- Scene pressure-contract checks with rewrite retries.
- Revision pass regression guards.

These mechanisms were mostly **heuristic + retry loops**:
- They measured patterns and thresholds.
- They invoked LLM rewrites to attempt corrections.
- They re-checked the same heuristics.
- They did **not** act as strict, final outline-adherence adjudicators.

**Root cause:**  
The system used LLMs primarily as repair workers, not as strict semantic judges tied to executable outline contracts. In addition, failure policy allowed progression after retry exhaustion in non-strict modes.

**Architectural lesson:**  
“Good gate coverage” is not equivalent to “contract compliance.”  
If outline fidelity is non-negotiable, the pipeline must treat contract violations as compile errors, not quality warnings.

**Planned direction (for blog narrative continuity):**
- Introduce executable chapter/scene contracts.
- Enforce scene count/order exactness.
- Add strict chapter-level beat verification (hard reveal, soft reversal, on-page move, petty moment, ending mode) with evidence spans.
- Add deterministic + semantic dual validator.
- Remove “proceed anyway” behavior for contract failures.

**Blog angle:**  
This is the pivotal shift from *quality heuristics* to *spec compliance architecture*.  
It reframes the system from “AI writes then we inspect” to “AI must satisfy a machine-checkable narrative contract before acceptance.”

---

## Cross-Cutting Themes (for the blog narrative)

### Theme 1: The Detection-vs-Correction Gap
The single most important lesson. Building detectors that reliably identify prose quality problems is a solved problem — regex, statistics, and careful calibration work. Getting the LLM to *fix* what the detectors find is an unsolved problem. The LLM rewrites in the same patterns. Telling it "don't do X" often produces X with different words. This gap shaped every phase of the project.

### Theme 2: The Upstream Principle
Quality problems are cheaper to prevent than to fix in revision. The project moved enforcement steadily upstream:
1. Post-hoc revision (Phase 2-3) → least effective
2. Code-level detectors injected into revision (Phase 4) → marginally better
3. Pre-generation gates with correction retry (Phase 6) → better
4. Scene-level pressure contracts in structural planning (Phase 7) → most effective
5. Upstream craft contracts populated before generation (Phase 8) → extending the pattern

Each move upstream was more effective and less costly than the last.

### Theme 3: Cost Management as Architecture
Model selection has enormous cost impact. Opus is 5-10x the cost of Sonnet. In Phase 7, Opus was 61% of total cost for marginal quality improvement. Phase 8's tiering — only using Opus for structural problems Sonnet genuinely can't fix — reduced cost substantially with no measurable quality regression. The lesson: model routing is an architectural decision, not a quality decision.

### Theme 4: The Irreducible Ceiling
Some aspects of great fiction — voice differentiation, embodied physicality, moral complexity, temporal perspective — may be beyond what prompt engineering, detection, and upstream contracts can achieve. These are not "bugs" in the pipeline; they may be properties of the underlying model's training and capabilities. The system can enforce *what* the prose contains (sensory detail, physical gestures, on-page opposition) but not *how* it feels (the distinctive consciousness of a specific character in a specific historical moment).

### Theme 5: Compound Improvement
No single intervention was transformative. Each phase improved quality by 2-10%. The compound effect — from the essay-like word-count-gutted prose of Phase 2 to the competent historical fiction of Phase 9 — is substantial. The journey from 0 to "good" was achievable through iterative engineering. The journey from "good" to "great" may require a different approach entirely.

---

## Proposed Blog Structure

### Section 1: Introduction
What if you could generate a full historical novel with a single command? We built that system. Here's what happened when we actually read the output.

### Section 2: Architecture (Phase 0)
The 6-stage pipeline. Why vanilla Python beats agent frameworks for this problem. The Pydantic-Jinja2-YAML stack.

### Section 3: The Quality Journey (Phases 1-8)
Structured as a narrative of escalating interventions. Each phase: what we tried, what we learned, what failed. Diagrams of the gate flow, the revision pipeline, the upstream-vs-downstream principle.

### Section 4: The Reckoning (Phase 9)
Reading the output honestly. Side-by-side comparison with Mantel/Vidal/Caro. The six shortcomings. What "good AI fiction" looks like vs. what "great fiction" looks like.

### Section 5: The Lessons
The five cross-cutting themes. What this tells us about LLM capabilities, engineering for quality, and the future of AI-assisted creative writing.

### Section 6: What's Next
The four improvements we're planning (voice differentiation, physical interruption, unresolved pettiness, ending variation) and whether they can close the gap.

---

## Key Numbers for the Blog

| Metric | Value |
|--------|-------|
| Total phases of iteration | 9 |
| Lines of Python | ~5,000+ |
| Jinja2 prompt templates | 15+ |
| Quality detectors | 16+ |
| Quality gates | 6 |
| Revision passes (original) | 7 |
| Revision passes (final) | 3 |
| Louisiana Purchase project variants | 5 |
| Chapters generated across all projects | 28+ |
| Total API cost (contracts project, 6ch) | ~$14.66 |
| Opus cost share before tiering | 61% |
| Opus cost share after tiering | Structural-only |
| Gate pass rate (gated vs baseline) | 45% vs 41% (+4pp) |
| Quality verdict | Good, not great |

---

## Appendix: Chat Session Index

| UUID | Date | Summary |
|------|------|---------|
| [Initial Planning](f843477f-ddad-4bb1-a557-2ad6783f6661) | Feb 16 | Product requirements → high-level plan + tech spec |
| [Full Implementation](bf83f12c-1b96-4cfc-bebe-38b25a2d7a9e) | Feb 16 | Complete pipeline implementation from tech spec |
| [First Run Bug Fixes](8f056b1d-df80-4ff5-af87-84175a8f6aa0) | Feb 17 | ERA_TONE_GUIDE JSON, Haiku model name, resume bug, SIGINT |
| [Polk Novel Proxy Run](d22872e8-1a05-4abe-a2e6-2160765ad617) | Feb 25 | "The Dark Horse" quality assessment, word-count catastrophe |
| [Quality Improvement Plan](1a5cd8e2-83f5-493b-9f51-099fc40be6ff) | Feb 21 | 7→3 revision passes, phrase tracker, checkpoint |
| [NextSteps Implementation](4dd05db2-5b88-47f7-ba8f-0f39b1326642) | Feb 22 | Historical title accuracy, synopsis selection, `sovereign-ink next` |
| [Pipeline Run](4ff77ca8-43a5-4edd-a818-d5d3b17a0454) | Feb 23 | Pipeline run with max_chapters, fixed killed-run leftovers |
| [Dark Horse Rerun](08549a9f-112e-453d-b00c-42e892b13884) | Feb 23 | Quality fixes, duplicate detection, register differentiation |
| [P0-P9 Quality Detectors](8080510e-2928-4420-b934-9c891a2af61d) | Feb 26 | 15+ detector implementation |
| [Quality Loop](1126de61-687c-4ea2-9a8a-300eb80a143c) | Mar 1 | A/B loop execution, quality-audit JSON parsing |
| [P10-P17 Schema + Sprint](67881564-0783-4015-a025-b0dc18e07c4a) | Mar 2 | Compulsion schema, new detectors, Sprint A comparison |
| [A3/B1 Loop Execution](64c2e75a-b15b-4185-9cdc-e5fd2dfeb7e4) | Feb 21 | Track A/B dual experiment, selective Opus |
| [Quality Convergence Plan](0abc4c7f-ef77-4f79-9c97-3efc0b1a1ffe) | Mar 3 | Pre-generation gates, loop evaluator, gate infrastructure |
| [Pressure Contracts](42e206bb-4582-48d3-969d-0001a616e25d) | Mar 6 | Scene-level contracts, political jeopardy calibration |
| [Contracts Cost Analysis](d83be8db-d0cf-45c8-999f-dda85bbd991b) | Mar 6 | $14.66 total, 61% Opus cost identified |
| [Craft Gates + Assessment](64b2c3ab-83b0-404c-a628-e3d0f2e25294) | Mar 7-8 | Craft gates, Opus tiering, literary assessment |
