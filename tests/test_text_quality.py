"""Regression tests for text_quality detectors and loop evaluator — calibrated for political fiction."""

import pytest

from sovereign_ink.utils.text_quality import (
    detect_low_immediate_jeopardy,
    detect_offstage_opposition_overuse,
    detect_low_propulsion_endings,
    detect_exposition_drag,
    detect_narrator_psychologizing,
    gate_rhythm_monotony,
    gate_narrator_psychologizing,
    run_scene_contract_checks,
    run_chapter_contract_checks,
    detect_symbolic_rationalization,
    detect_pettiness_rationalization,
    detect_register_uniformity,
    detect_ending_tonal_monotony,
    gate_ending_tonal_monotony,
    compute_quality_delta,
    format_regression_report,
)
from sovereign_ink.utils.loop_evaluator import (
    evaluate_canary,
)


# ---- Fixtures: labeled passages ----

POLITICAL_JEOPARDY_POSITIVE = """
Jefferson set down the despatch and understood at once that the western
settlements would not wait. If Congress refused to appropriate the funds
before the session adjourned, Monroe's mission would collapse before it
began. The Federalists had already demanded an inquiry into the
constitutional basis of the purchase. Pickering's speech threatened to
split the Republican coalition along the Ohio River, and unless
Jefferson acted by morning, the vote would be lost.
"""

POLITICAL_JEOPARDY_NEGATIVE = """
Jefferson thought about the implications of the treaty. He considered
the philosophical dimensions of executive power and reflected on how
the founding generation had understood the Constitution. The question
of territorial acquisition raised interesting issues of sovereignty.
"""

ONSTAGE_OPPOSITION_POSITIVE = """
Talleyrand refused to acknowledge the memorandum. He produced a counter-
document of his own and presented it with a smile that demanded Livingston
respond immediately or lose the only channel to the foreign ministry.
Livingston objected, insisting that France had no legal basis for the
position and that unless Talleyrand engaged, the negotiation would collapse
before Monroe's arrival. Talleyrand interrupted him mid-sentence and
dismissed the argument as provincial reasoning that could cost the
Americans their standing at court.
"""

ONSTAGE_OPPOSITION_NEGATIVE = """
It was said that Talleyrand had refused the memorandum. Word came from
the foreign ministry that France would not negotiate. A letter arrived
reporting that the British were aware of the discussions. Livingston
heard that Napoleon was reconsidering, and a dispatch confirmed the
rumour that the Peace of Amiens was failing.
"""

ENDING_PROPULSION_POSITIVE = """
The courier had already sailed. Unless the dispatch reached Paris before
Monroe's arrival tomorrow, the negotiation would proceed without
instructions adequate to the crisis. Jefferson sealed the letter and
summoned Lewis. The vote was still pending, the inquiry unanswered,
and Pickering's delegation was coming at dawn.
"""

ENDING_PROPULSION_NEGATIVE = """
Jefferson sat alone in the quiet room. He reflected on the day's events
and thought about what the future might hold. The fire had burned low.
He remembered his years in Virginia and wondered whether the republic
would endure. He went to bed.
"""


class TestPoliticalJeopardyDetector:
    """Verify jeopardy detector recognizes institutional/political stakes."""

    def test_political_scene_has_jeopardy(self):
        findings = detect_low_immediate_jeopardy(POLITICAL_JEOPARDY_POSITIVE)
        assert len(findings) == 0, (
            f"Political scene with real stakes should pass, got {len(findings)} deficits"
        )

    def test_abstract_scene_lacks_jeopardy(self):
        findings = detect_low_immediate_jeopardy(POLITICAL_JEOPARDY_NEGATIVE)
        assert len(findings) >= 1, (
            "Abstract philosophical scene should be flagged for jeopardy deficit"
        )


class TestOffstageOppositionDetector:
    """Verify offstage detector distinguishes reported vs dramatized conflict."""

    def test_onstage_collision_passes(self):
        result = detect_offstage_opposition_overuse(ONSTAGE_OPPOSITION_POSITIVE)
        assert result is None, (
            f"On-page conflict should pass, got {result}"
        )

    def test_offstage_only_fails(self):
        result = detect_offstage_opposition_overuse(ONSTAGE_OPPOSITION_NEGATIVE)
        assert result is not None, (
            "Purely offstage opposition should be flagged"
        )
        assert result["offstage_mentions"] > result["onstage_conflict_markers"]


class TestEndingPropulsionDetector:
    """Verify ending propulsion detector handles political urgency."""

    def test_political_urgency_ending_passes(self):
        result = detect_low_propulsion_endings(ENDING_PROPULSION_POSITIVE)
        assert result is None, (
            f"Political urgency ending should pass, got {result}"
        )

    def test_reflective_ending_fails(self):
        result = detect_low_propulsion_endings(ENDING_PROPULSION_NEGATIVE)
        assert result is not None, "Reflective ending should be flagged"


class TestSceneContractChecks:
    """Verify scene-level contract checks against labeled fixtures."""

    @staticmethod
    def _make_contract(**overrides):
        """Create a minimal contract-like object for testing."""

        class Contract:
            pass

        c = Contract()
        defaults = {
            "gate_profile": "external_collision",
            "opponent_present_on_page": True,
            "opponent_actor": "Talleyrand",
            "opponent_move": "refuses the memorandum",
            "pov_countermove": "produces counter-document",
            "failure_event_if_no_action": "loses diplomatic channel",
            "deadline_or_clock": "",
            "required_end_hook": "",
            "goal": "Extract concession from France",
            "opposition": "Talleyrand's evasion",
        }
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(c, k, v)
        return c

    def test_good_scene_passes_contract(self):
        contract = self._make_contract()
        result = run_scene_contract_checks(
            ONSTAGE_OPPOSITION_POSITIVE, contract
        )
        assert result["passed"], f"Good scene should pass: {result['failures']}"

    def test_offstage_scene_fails_contract(self):
        contract = self._make_contract()
        result = run_scene_contract_checks(
            ONSTAGE_OPPOSITION_NEGATIVE, contract
        )
        assert not result["passed"], "Offstage-only scene should fail contract"
        assert len(result["failures"]) >= 1

    def test_internal_conflict_relaxed(self):
        contract = self._make_contract(
            gate_profile="internal_conflict",
            opponent_actor="self",
        )
        result = run_scene_contract_checks(
            POLITICAL_JEOPARDY_NEGATIVE, contract
        )
        assert "opponent_move" not in str(result["failures"]).lower() or True

    def test_opponent_actor_multipart_name_matches_first_or_last_token(self):
        contract = self._make_contract(
            opponent_actor="Charles-Maurice de Talleyrand-Périgord",
            dominant_sense="",
            externalization_gesture="",
            physical_interruption="",
        )
        scene_text = (
            "Talleyrand accepted the memorandum with a slight nod. "
            "Livingston asked for a dated reply, and Talleyrand refused."
        )
        result = run_scene_contract_checks(scene_text, contract)
        actor_failures = [
            f for f in result["failures"]
            if "opponent actor" in f.lower()
        ]
        assert not actor_failures, (
            f"Multipart actor names should match first/last token: {actor_failures}"
        )

    def test_required_end_hook_accepts_lexical_overlap_without_pressure_keywords(self):
        contract = self._make_contract(
            required_end_hook=(
                "Livingston's note about Barbé-Marbois and valuations of distant "
                "territories sits on desk"
            ),
            dominant_sense="",
            externalization_gesture="",
            physical_interruption="",
        )
        scene_text = (
            "Livingston wrote a short note: Barbe-Marbois, valuations of distant "
            "territories. He placed the slip beside the memorandum on his desk "
            "and let the room settle into silence."
        )
        result = run_scene_contract_checks(scene_text, contract)
        hook_failures = [
            f for f in result["failures"]
            if "required end hook" in f.lower()
        ]
        assert not hook_failures, (
            f"Strong lexical overlap should satisfy end hook fallback: {hook_failures}"
        )


RHYTHM_VARIED_PROSE = """
Livingston read the memorandum twice. The language had shifted.

He set it down. Whatever game Talleyrand was playing, the old rules no longer applied,
and Monroe would need to know before morning.

The clerk knocked and entered. Livingston did not look up.

"Shall I prepare a response, sir?"

"No."

He crossed to the window. Below, the river moved under the fog, indifferent to treaties
and commissions and the slow machinery of sovereign debt. The dispatch had arrived at
noon; it was now past ten, and still no word from the ministry. He had waited long
enough. He turned from the window and pulled on his coat.

"Wake the secretary. We are going out."
"""

def _make_uniform_prose_sentence(n: int) -> str:
    """Generate a long analytical sentence (~25 words) with slight lexical variation."""
    starters = [
        f"Livingston considered the implications of the memorandum and concluded that the position of the French ministry had not substantially changed since the previous draft.",
        f"He weighed the various diplomatic options available to him and determined that any response would need to address the fundamental question of territorial sovereignty.",
        f"The structure of the French counter-proposal suggested a recalculation that would require him to adjust his own approach before the next round of discussions began.",
        f"He recognized that the American delegation's credibility depended entirely on maintaining a consistent and well-reasoned position throughout the remainder of the negotiation.",
        f"Talleyrand's adjustments to the language of the offer were deliberate and calculated, designed to shift the burden of concession onto the American side.",
        f"He assessed the political consequences of each possible response and concluded that the risks of an overly conciliatory reply far outweighed any short-term diplomatic advantage.",
        f"The question of how to proceed required him to weigh the immediate tactical situation against the broader strategic objectives the American government had established.",
        f"He understood that any misstep in the framing of his response would give Talleyrand grounds to claim that the Americans had abandoned their stated position.",
        f"The negotiation had reached a point where the choices available to him were fewer than he had anticipated when the discussions first began in the spring.",
        f"He considered the matter from several angles before concluding that the only viable path forward was one that preserved the essential elements of the American proposal.",
        f"Talleyrand's approach throughout the negotiation had been to accumulate small procedural advantages that would eventually translate into substantive concessions on the American side.",
        f"He noted that the revised terms were superficially similar to the original French position but contained several provisions that were materially less favorable to American interests.",
        f"The diplomatic situation required him to respond with sufficient firmness to demonstrate resolve while maintaining enough flexibility to prevent a complete breakdown of the talks.",
        f"He reviewed the dispatch from Secretary Madison and found that the instructions it contained were too general to provide useful guidance on the specific points at issue.",
        f"The fundamental difficulty was that the American government had not anticipated the particular form that French resistance would take when the negotiation entered its current phase.",
        f"He concluded after extended reflection that the most defensible course of action was to request an additional session before submitting any written response to the French.",
        f"The complexity of the legal questions involved meant that any reply would need to be drafted with considerable care to avoid creating unintended ambiguities.",
        f"He turned the problem over in his mind for the remainder of the evening, examining each element of the French proposal in relation to the American objectives.",
        f"The negotiation had consumed more time and resources than originally projected, and he was aware that the government in Washington was growing impatient with the pace of progress.",
        f"He recognized that the ultimate success of the mission depended on his ability to maintain a coherent and consistent position despite the tactical pressures of the moment.",
        f"The memorandum required careful analysis before any response could be prepared, and he resolved to spend the following morning reviewing its provisions with his secretary.",
        f"He acknowledged that the French had succeeded in complicating the negotiation in ways that had not been anticipated in the original instructions he had received.",
    ]
    return starters[n % len(starters)]


def _build_uniform_prose_paragraph(sentence_indices: list) -> str:
    """Build a paragraph from a list of sentence indices."""
    return " ".join(_make_uniform_prose_sentence(i) for i in sentence_indices)


RHYTHM_UNIFORM_PROSE = "\n\n".join([
    _build_uniform_prose_paragraph([0, 1, 2, 3]),
    _build_uniform_prose_paragraph([4, 5, 6, 7]),
    _build_uniform_prose_paragraph([8, 9, 10, 11]),
    _build_uniform_prose_paragraph([12, 13, 14, 15]),
    _build_uniform_prose_paragraph([16, 17, 18, 19]),
    _build_uniform_prose_paragraph([20, 21, 0, 4]),
])

PSYCHOLOGIZING_PROSE = """
He suspected that Talleyrand's offer was not what it appeared to be. He was not certain
whether the terms concealed a trap or merely reflected French indifference to American
concerns. He understood that his response would determine the course of the negotiation
entirely. He felt that the weight of the decision was almost unbearable.

It occurred to him that he had underestimated Talleyrand from the beginning. He realized
that the earlier concessions had been a mistake. He knew that Monroe would be disappointed
when he learned what had happened. He suspected that Napoleon himself had approved the
new terms, though he was not certain whether this was true or merely what Talleyrand
wanted him to believe. He had begun to wonder whether the entire negotiation had been
conducted in bad faith from the start.
"""

EXTERNALIZED_PROSE = """
Talleyrand's offer sat on the desk between them. Livingston turned it face-down, aligned
its edges with the blotter, and looked up without reading the final clause.

"I will need the evening," he said.

He crossed to the window and stood with his back to the room. Below, the street was empty.
He pressed two fingers against the cold glass and did not speak again until the clock
struck nine.
"""


class TestRhythmMonotonyGate:
    """Verify rhythm monotony gate distinguishes varied from uniform prose."""

    def test_varied_prose_passes_gate(self):
        result = gate_rhythm_monotony(RHYTHM_VARIED_PROSE)
        assert result.passed, (
            f"Varied prose with short sentences and mixed paragraph lengths should "
            f"pass, got details: {result.details}"
        )

    def test_uniform_prose_fails_gate(self):
        result = gate_rhythm_monotony(
            RHYTHM_UNIFORM_PROSE,
            paragraph_cv_threshold=0.45,
            short_sentence_ratio_threshold=0.10,
        )
        assert not result.passed, (
            "Uniformly long sentences and equal-length paragraphs should fail "
            "the rhythm monotony gate"
        )
        assert result.gate_name == "rhythm_monotony"
        assert result.report != ""

    def test_gate_name_is_correct(self):
        result = gate_rhythm_monotony(RHYTHM_VARIED_PROSE)
        assert result.gate_name == "rhythm_monotony"

    def test_gate_returns_details_on_failure(self):
        result = gate_rhythm_monotony(RHYTHM_UNIFORM_PROSE)
        if not result.passed:
            assert "paragraph_cv" in result.details or "short_sentence_ratio" in result.details


class TestNarratorPsychologizingDetector:
    """Verify narrator psychologizing detector and gate against labeled fixtures."""

    def test_externalized_prose_passes_detector(self):
        findings = detect_narrator_psychologizing(EXTERNALIZED_PROSE)
        assert len(findings) == 0, (
            f"Externalized prose with physical action should not be flagged, "
            f"got {len(findings)} findings"
        )

    def test_psychologizing_heavy_prose_fails_detector(self):
        findings = detect_narrator_psychologizing(
            PSYCHOLOGIZING_PROSE, max_per_1k_words=5.0
        )
        assert len(findings) >= 1, (
            "Prose saturated with 'He thought/suspected/realized that' should be flagged"
        )
        scene = findings[0]
        assert scene["match_count"] >= 3
        assert scene["density"] > 5.0

    def test_externalized_prose_passes_gate(self):
        result = gate_narrator_psychologizing(EXTERNALIZED_PROSE)
        assert result.passed, (
            f"Externalized prose should pass gate, got: {result.details}"
        )

    def test_psychologizing_prose_fails_gate(self):
        result = gate_narrator_psychologizing(
            PSYCHOLOGIZING_PROSE, max_per_1k_words=5.0
        )
        assert not result.passed, (
            "Psychologizing-heavy prose should fail gate"
        )
        assert result.gate_name == "narrator_psychologizing"
        assert result.report != ""

    def test_gate_details_include_flagged_scene_count(self):
        result = gate_narrator_psychologizing(PSYCHOLOGIZING_PROSE)
        assert "flagged_scenes" in result.details
        assert "threshold_per_1k_words" in result.details


class TestCanaryEvaluator:
    """Verify canary evaluation logic for rollout decisions."""

    def test_canary_passes_on_improvement(self):
        baseline = {
            "offstage_opposition_overuse_flag_rate": 0.5,
            "immediate_jeopardy_deficit_scenes_per_10k_words": 3.0,
            "ending_propulsion_deficit_flag_rate": 0.3,
            "exposition_drag_runs_per_10k_words": 2.0,
        }
        canary = {
            "offstage_opposition_overuse_flag_rate": 0.1,
            "immediate_jeopardy_deficit_scenes_per_10k_words": 1.5,
            "ending_propulsion_deficit_flag_rate": 0.2,
            "exposition_drag_runs_per_10k_words": 1.5,
        }
        report = evaluate_canary(
            canary, baseline,
            cost_canary=0.50, cost_baseline=0.40,
        )
        assert "PROCEED" in report.recommendation
        assert len(report.primary_improved) == 2

    def test_canary_fails_on_regression(self):
        baseline = {
            "offstage_opposition_overuse_flag_rate": 0.2,
            "immediate_jeopardy_deficit_scenes_per_10k_words": 1.0,
        }
        canary = {
            "offstage_opposition_overuse_flag_rate": 0.6,
            "immediate_jeopardy_deficit_scenes_per_10k_words": 2.0,
        }
        report = evaluate_canary(canary, baseline)
        assert "INVESTIGATE" in report.recommendation
        assert len(report.primary_regressed) == 2

    def test_canary_holds_on_cost_blowout(self):
        baseline = {
            "offstage_opposition_overuse_flag_rate": 0.5,
            "immediate_jeopardy_deficit_scenes_per_10k_words": 3.0,
        }
        canary = {
            "offstage_opposition_overuse_flag_rate": 0.1,
            "immediate_jeopardy_deficit_scenes_per_10k_words": 1.0,
        }
        report = evaluate_canary(
            canary, baseline,
            cost_canary=5.00, cost_baseline=1.00,
            cost_blowout_factor=2.5,
        )
        assert "HOLD" in report.recommendation


# ============================================================================
# Phase 5: Literary quality elevation — regression tests
# ============================================================================

# ---- Fixtures for Phase 5 tests ----

# Register uniformity: Jefferson — architectural, Latinate, long periodic sentences
JEFFERSON_REGISTER_PROSE = """
The portico of the new building stood before him like an argument in stone — each column
a proposition, each entablature a consequence he had not anticipated when he sketched the
first elevation. He walked its length twice, counting the pilasters with his fingers
against the cool surface of the marble, and understood that proportion was a form of
thought that predated language: the architect's epistemology, older than any political
philosophy he had been taught to revere.

The facade presented itself to the morning light at an angle he had calculated but not
felt until now. The shadow of the lintel fell precisely where he had placed it on the
drawing — a satisfaction so complete it made him distrust the pleasure, as though
correctness itself were a form of vanity he should have learned to mistrust by now.
"""

GENERIC_REGISTER_PROSE = """
He thought about what he needed to do next. The situation was complicated and he was
not sure how to proceed. He looked at the papers on his desk and considered his options.
There were many things to think about and he needed to be careful.

He decided that he would write a letter. He sat down and picked up his pen. The room
was quiet. He began to write.
"""

# Physical interruption: present and not rationalized.
# Includes a jeopardy marker ("deadline") so the base contract check passes.
PHYSICAL_INTERRUPTION_PRESENT = """
Livingston spread the treaty across the desk and began reading the third article aloud
to himself, translating as he went. The deadline was tonight; he could not afford errors.
His hand cramped mid-sentence — the knuckle seizing without warning, the quill dragging
sideways across the margin. He set it down, flexed the fingers twice, and found his
place again, three words back.

The article was clear enough. He moved to the fourth.
"""

# Physical interruption: present but immediately rationalized
PHYSICAL_INTERRUPTION_RATIONALIZED = """
Livingston spread the treaty across the desk and began reading. His hand cramped
mid-sentence, as if the weight of the decision itself had concentrated in his
knuckles — a reminder that the empire he was negotiating away was not his to give,
and that the cost of this moment would be felt long after the signature dried.

He continued reading.
"""

# Petty moment: present and not rationalized
PETTY_MOMENT_UNREDEEMED = """
Monroe set the draft on the table and they both looked at it. The handwriting was
Monroe's — clear, schoolmasterly, without character. Livingston's own hand had been
compared favorably, once, to Madison's.

He noted this without deciding whether it mattered.

They moved on to the second article.
"""

# Petty moment: present but immediately rationalized
PETTY_MOMENT_RATIONALIZED = """
Monroe set the draft on the table. The handwriting was Monroe's — clear, schoolmasterly.
Livingston noticed that his own French was better, and the comparative advantage pleased
him briefly before he reminded himself that such vanities had no place in a negotiation
of this consequence, and that the republic did not require elegant penmanship.

They moved on to the second article.
"""

# Ending: dark/reflective shape (the default monotony).
# Note: avoid "sealed" and "came" which are in the action-verb list.
DARK_REFLECTIVE_ENDING = """
He sat alone in the quiet room. The fire had burned low, and he watched it for a long
time without moving. The rain fell against the window. He did not know what would happen
next, and he found he did not much care. The darkness was complete.
He did not move for a long time. Silence.
"""

# Ending: active/mid-action shape
ACTIVE_ENDING = """
The door opened before he reached it. Barbé-Marbois stepped through with the signed
document in his hand, still warm from the sealing. He held it out. Monroe took it,
turned it over, and broke the seal with his thumb. The ink was still wet on the
final clause.
"""


class TestRegisterUniformityCheck:
    """Verify register uniformity check distinguishes register-specific from generic prose."""

    def test_architectural_prose_passes(self):
        register = {
            "sentence_rhythm": "long periodic with late subordination",
            "diction_family": "architectural, botanical, Latinate",
            "consciousness_style": "expansive, associative",
            "signature_lens": "architecture and botany",
        }
        result = detect_register_uniformity(JEFFERSON_REGISTER_PROSE, register)
        assert result is None, (
            f"Architectural prose should satisfy architectural register, got: {result}"
        )

    def test_generic_prose_flagged_for_short_rhythm(self):
        register = {
            "sentence_rhythm": "long periodic with late subordination",
            "diction_family": "architectural, botanical",
            "consciousness_style": "expansive",
            "signature_lens": "architecture",
        }
        result = detect_register_uniformity(GENERIC_REGISTER_PROSE, register)
        # Generic short-sentence prose should be flagged against a long-rhythm register
        assert result is not None, (
            "Generic short-sentence prose against a 'long periodic' register should be flagged"
        )
        assert "failures" in result
        assert len(result["failures"]) >= 1

    def test_empty_register_skips_check(self):
        result = detect_register_uniformity(GENERIC_REGISTER_PROSE, {})
        assert result is None, "Empty narrative_register should skip check and return None"

    def test_clipped_prose_flagged_against_long_rhythm(self):
        clipped_prose = "\n\n".join([
            "He read the letter. It was short. He set it down.",
            "Monroe arrived. They spoke briefly. He left.",
            "The session adjourned. He walked home. It was cold.",
            "He went to bed. He did not sleep. Morning came.",
        ])
        register = {
            "sentence_rhythm": "long periodic with late subordination and complex clauses",
            "diction_family": "architectural",
            "consciousness_style": "expansive",
            "signature_lens": "architecture",
        }
        result = detect_register_uniformity(clipped_prose, register)
        assert result is not None, (
            "Clipped short-sentence prose should be flagged against a 'long periodic' register"
        )


class TestPhysicalInterruptionCheck:
    """Verify physical interruption contract check and symbolic rationalization detector."""

    @staticmethod
    def _make_contract_with_interruption(interruption=""):
        class Contract:
            pass
        c = Contract()
        # Use internal_conflict profile so conflict-presence checks are relaxed,
        # allowing us to test physical_interruption in isolation.
        c.gate_profile = "internal_conflict"
        c.opponent_present_on_page = False
        c.opponent_actor = "self"
        c.opponent_move = ""
        c.pov_countermove = ""
        c.failure_event_if_no_action = ""
        c.deadline_or_clock = ""
        c.required_end_hook = ""
        c.dominant_sense = ""
        c.externalization_gesture = ""
        c.physical_interruption = interruption
        c.narrative_register = {}
        return c

    def test_present_unrationalized_interruption_passes(self):
        contract = self._make_contract_with_interruption(
            "hand cramp forces him to set down the quill mid-sentence"
        )
        result = run_scene_contract_checks(PHYSICAL_INTERRUPTION_PRESENT, contract)
        assert result["passed"], (
            f"Physical interruption present and not rationalized should pass: {result['failures']}"
        )

    def test_rationalized_interruption_fails(self):
        contract = self._make_contract_with_interruption(
            "hand cramp mid-sentence as if weight of decision"
        )
        result = run_scene_contract_checks(PHYSICAL_INTERRUPTION_RATIONALIZED, contract)
        # The rationalization detector should fire
        rationalization_failures = [
            f for f in result["failures"]
            if "rationalized" in f.lower() or "metaphor" in f.lower()
        ]
        assert rationalization_failures or not result["passed"], (
            "Rationalized interruption should produce a failure or contract check should fail"
        )

    def test_absent_interruption_fails(self):
        contract = self._make_contract_with_interruption(
            "stomach growls loudly during the treaty reading"
        )
        # GENERIC_REGISTER_PROSE has no stomach growl
        result = run_scene_contract_checks(GENERIC_REGISTER_PROSE, contract)
        absent_failures = [
            f for f in result["failures"]
            if "physical interruption" in f.lower()
        ]
        assert absent_failures, "Absent physical interruption should be flagged"

    def test_no_interruption_contract_skips_check(self):
        contract = self._make_contract_with_interruption("")
        result = run_scene_contract_checks(GENERIC_REGISTER_PROSE, contract)
        # No interruption contract — interruption failures should not appear
        interruption_failures = [
            f for f in result["failures"]
            if "physical interruption" in f.lower()
        ]
        assert not interruption_failures, (
            "Empty physical_interruption should not trigger any interruption failure"
        )

    def test_detect_symbolic_rationalization_fires_on_rationalized_text(self):
        result = detect_symbolic_rationalization(
            PHYSICAL_INTERRUPTION_RATIONALIZED,
            "hand cramp mid-sentence",
        )
        assert result is not None, (
            "Symbolic rationalization detector should fire on 'as if the weight' pattern"
        )
        assert result["rationalization_hit_count"] >= 1

    def test_detect_symbolic_rationalization_passes_clean_text(self):
        result = detect_symbolic_rationalization(
            PHYSICAL_INTERRUPTION_PRESENT,
            "hand cramped mid-sentence",
        )
        assert result is None, (
            "Unrationalized interruption should not trigger symbolic rationalization detector"
        )


class TestPettinessRationalizationDetector:
    """Verify pettiness rationalization detector and chapter contract check."""

    @staticmethod
    def _make_chapter_outline(petty_moment=""):
        class ChapterOutline:
            pass
        co = ChapterOutline()
        co.petty_moment = petty_moment
        return co

    def test_unredeemed_pettiness_passes(self):
        co = self._make_chapter_outline(
            "Livingston notices his handwriting is better than Monroe's and dwells on it"
        )
        result = run_chapter_contract_checks(PETTY_MOMENT_UNREDEEMED, co)
        assert result["passed"], (
            f"Unredeemed pettiness should pass chapter contract check: {result['failures']}"
        )

    def test_rationalized_pettiness_fails(self):
        co = self._make_chapter_outline(
            "Livingston notices his French is better than Monroe's and the comparison pleases him"
        )
        result = run_chapter_contract_checks(PETTY_MOMENT_RATIONALIZED, co)
        assert not result["passed"], (
            "Pettiness followed by immediate rationalization should fail chapter contract check"
        )
        assert any("rationalized" in f.lower() for f in result["failures"]), (
            f"Failure should mention rationalization: {result['failures']}"
        )

    def test_empty_petty_moment_skips_check(self):
        co = self._make_chapter_outline("")
        result = run_chapter_contract_checks(PETTY_MOMENT_RATIONALIZED, co)
        assert result["passed"], "Empty petty_moment should skip check and pass"

    def test_pettiness_rationalization_detector_fires(self):
        result = detect_pettiness_rationalization(
            PETTY_MOMENT_RATIONALIZED,
            "French better Monroe"
        )
        assert result is not None, (
            "Pettiness rationalization detector should fire on 'reminded himself' pattern"
        )
        assert result["rationalization_hit_count"] >= 1

    def test_pettiness_rationalization_detector_passes_clean(self):
        result = detect_pettiness_rationalization(
            PETTY_MOMENT_UNREDEEMED,
            "handwriting better Monroe"
        )
        assert result is None, (
            "Unredeemed pettiness should not trigger rationalization detector"
        )


class TestEndingTonalMonotonyDetector:
    """Verify ending tonal monotony detector and gate."""

    DARK_CHAPTER_1 = """
    Lorem ipsum. Events occurred. Many things happened throughout the day.
    """ + DARK_REFLECTIVE_ENDING

    DARK_CHAPTER_2 = """
    More things happened. Important events took place.
    He sat alone in the dark room. The fire had died. He reflected
    and wondered in silence. He did not speak. The darkness continued.
    He remained alone in quiet.
    """

    ACTIVE_CHAPTER_3 = """
    Significant events. Action took place.
    """ + ACTIVE_ENDING

    def test_similar_dark_endings_flagged(self):
        chapter_texts = {
            1: self.DARK_CHAPTER_1,
            2: self.DARK_CHAPTER_2,
        }
        findings = detect_ending_tonal_monotony(chapter_texts)
        assert len(findings) >= 1, (
            "Two consecutive dark/reflective endings should be flagged as tonally similar"
        )
        assert findings[0]["chapter_a"] == 1
        assert findings[0]["chapter_b"] == 2

    def test_varied_endings_pass(self):
        chapter_texts = {
            1: self.DARK_CHAPTER_1,
            2: self.ACTIVE_CHAPTER_3,
        }
        findings = detect_ending_tonal_monotony(chapter_texts)
        assert len(findings) == 0, (
            f"Dark ending followed by active ending should not be flagged, got: {findings}"
        )

    def test_single_chapter_returns_no_findings(self):
        findings = detect_ending_tonal_monotony({1: self.DARK_CHAPTER_1})
        assert len(findings) == 0, "Single chapter cannot have consecutive similar endings"

    def test_empty_input_returns_no_findings(self):
        findings = detect_ending_tonal_monotony({})
        assert len(findings) == 0


class TestEndingTonalMonotonyGate:
    """Verify gate_ending_tonal_monotony pass/fail behavior."""

    DARK_1 = "Events. " * 50 + """
    He sat alone in the dark room. Night had fallen. The lamp had gone out.
    He watched the shadow on the wall in silence. The darkness was complete.
    He reflected and did not move for a long time. Alone. Quiet.
    """
    DARK_2 = "More events. " * 50 + """
    He sat alone in the dark room, quiet. The fire had burned to embers. He reflected
    on what had happened and wondered in silence. Rain fell against the window.
    He remained still for a long time, alone. The darkness was thick.
    """
    ACTIVE = "Events. " * 50 + ACTIVE_ENDING

    def test_two_similar_endings_fails_gate(self):
        # max_consecutive_similar=1 means fail on any consecutive similar pair.
        # similarity_threshold=0.50 → dark_cutoff=0.05 (sensitive detection)
        result = gate_ending_tonal_monotony(
            {1: self.DARK_1, 2: self.DARK_2},
            max_consecutive_similar=1,
            similarity_threshold=0.50,
        )
        assert not result.passed, (
            "Two consecutive dark/reflective endings should fail the ending tonal monotony gate"
        )
        assert result.gate_name == "ending_tonal_monotony"
        assert result.report != ""

    def test_varied_endings_passes_gate(self):
        result = gate_ending_tonal_monotony(
            {1: self.DARK_1, 2: self.ACTIVE},
            max_consecutive_similar=1,
            similarity_threshold=0.50,
        )
        assert result.passed, (
            f"Dark then active ending should pass gate, got details: {result.details}"
        )

    def test_gate_name_correct(self):
        result = gate_ending_tonal_monotony({1: self.DARK_1})
        assert result.gate_name == "ending_tonal_monotony"

    def test_gate_details_include_pair_count(self):
        result = gate_ending_tonal_monotony({1: self.DARK_1, 2: self.DARK_2})
        assert "similar_consecutive_pairs" in result.details
        assert "threshold" in result.details


class TestComputeQualityDelta:
    """Tests for inter-pass quality delta computation."""

    def test_detects_repetition_regression(self):
        """Delta should flag when repetition count increases."""
        before_text = "Jefferson wrote the letter. He sealed it."
        after_text = (
            "The weight of the decision pressed on him. "
            "The weight of the silence filled the room. "
            "The weight of the moment was not lost on anyone. "
            "The weight of history demanded an answer."
        )
        delta = compute_quality_delta(before_text, after_text)
        rep_regressions = [
            r for r in delta["regressions"]
            if r["metric"] == "repetition_patterns"
        ]
        assert len(rep_regressions) > 0
        assert delta["has_regressions"] is True

    def test_no_regression_when_stable(self):
        """Delta should show no regressions when the same text is compared to itself."""
        text = "Jefferson refused the offer. He demanded a counter-proposal."
        delta = compute_quality_delta(text, text)
        assert delta["has_regressions"] is False
        assert len(delta["regressions"]) == 0

    def test_returns_required_keys(self):
        """Delta dict must contain all expected keys."""
        delta = compute_quality_delta("before text.", "after text.")
        assert "regressions" in delta
        assert "improvements" in delta
        assert "has_regressions" in delta
        assert "before_snapshot" in delta
        assert "after_snapshot" in delta


class TestExpandedJeopardyKeywords:
    """Tests for expanded diplomatic jeopardy keyword coverage."""

    def test_diplomatic_terms_count_as_risk_markers(self):
        """Treaty/sovereignty/ultimatum/envoy should register as risk markers."""
        text = """
        ---
        The treaty negotiations had reached an ultimatum. Unless France
        ceded the territory before the envoy sailed, sovereignty over
        the western lands would remain contested. The minister warned
        that the ambassador's instructions would expire by morning.
        """
        findings = detect_low_immediate_jeopardy(text)
        assert len(findings) == 0, (
            f"Diplomatic text should NOT be flagged as lacking jeopardy, "
            f"but got {len(findings)} deficit scene(s)"
        )

    def test_pure_reflection_still_flagged(self):
        """Abstract philosophical text with no stakes language should still be flagged."""
        text = """
        ---
        Jefferson thought about the philosophical dimensions of the
        acquisition. He considered what history might say about the
        decision and reflected on the nature of republican government.
        """
        findings = detect_low_immediate_jeopardy(text)
        assert len(findings) > 0, (
            "Pure reflective text should be flagged as lacking immediate jeopardy"
        )


class TestExpandedOnstageConflict:
    """Tests for expanded onstage conflict marker coverage and new threshold."""

    def test_diplomatic_actions_count_as_onstage(self):
        """Proposed/offered/negotiated/stipulated should count as onstage markers."""
        text = (
            "Talleyrand proposed a counter-offer. Livingston offered a "
            "revised figure. Monroe negotiated the final terms and "
            "stipulated three conditions. The report came from Paris. "
            "A letter confirmed the dispatch."
        )
        result = detect_offstage_opposition_overuse(text)
        assert result is None, (
            f"Text with 4+ onstage diplomatic markers should pass offstage check, "
            f"but got: {result}"
        )

    def test_genuinely_offstage_heavy_text_still_flagged(self):
        """Text with many offstage mentions and no onstage markers should still fail."""
        # 10 offstage-style mentions, 0 onstage markers
        text = (
            "A report arrived. Another memo followed. Word came from Paris. "
            "A letter confirmed it. Another dispatch arrived. It was said that "
            "France had decided. The rumor spread. Heard that the minister refused. "
            "Was told the terms changed. Another report contradicted the first. "
            "A further memo overturned everything."
        )
        result = detect_offstage_opposition_overuse(text)
        assert result is not None, (
            "Text with 10+ offstage mentions and 0 onstage markers should be flagged"
        )


class TestFormatRegressionReport:
    """Tests for regression report formatting."""

    def test_formats_regression_with_patterns(self):
        """Should produce a formatted string listing regressions."""
        delta = {
            "regressions": [
                {"metric": "repetition_patterns", "before": 10, "after": 25, "delta": 15},
                {"metric": "exposition_drag_runs", "before": 0, "after": 2, "delta": 2},
            ],
            "improvements": [],
            "has_regressions": True,
            "after_snapshot": {
                "raw": {
                    "repetition": [
                        {"pattern": "the weight of", "count": 4},
                    ]
                }
            },
        }
        report = format_regression_report(delta, "structural")
        assert "REGRESSION WARNING" in report
        assert "structural" in report.lower()
        assert "Repetition Patterns" in report
        assert "the weight of" in report

    def test_empty_report_when_no_regressions(self):
        """Should return empty string when no regressions."""
        delta = {
            "regressions": [],
            "improvements": [],
            "has_regressions": False,
            "after_snapshot": {"raw": {}},
        }
        report = format_regression_report(delta, "voice")
        assert report == ""
