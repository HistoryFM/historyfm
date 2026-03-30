"""PromptRenderer — renders Jinja2 prompt templates with context injection."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class PromptRenderer:
    """Renders prompt templates with context injection."""

    def __init__(self) -> None:
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_name: str, **context) -> str:
        """Render a template with the given context variables."""
        template = self.env.get_template(template_name)
        return template.render(**context)

    # ------------------------------------------------------------------
    # Convenience methods for each stage
    # ------------------------------------------------------------------

    def render_system_prompt(self, era_tone_guide=None) -> str:
        """Render the master novelist system prompt."""
        return self.render("system_prompt.j2", era_tone_guide=era_tone_guide)

    def render_world_building(self, sub_task: str, novel_spec=None, **kwargs) -> str:
        """Render world-building prompts.

        *sub_task* is one of: ``historical_context``, ``characters``,
        ``institutions``, ``era_tone_guide``.
        """
        return self.render(
            f"world_building/{sub_task}.j2", novel_spec=novel_spec, **kwargs
        )

    def render_structure(self, sub_task: str, **kwargs) -> str:
        """Render structural planning prompts.

        *sub_task* is one of: ``act_structure``, ``chapter_outlines``,
        ``scene_breakdowns``.
        """
        return self.render(f"structure/{sub_task}.j2", **kwargs)

    def render_generation(self, **kwargs) -> str:
        """Render the prose generation prompt for a chapter."""
        return self.render("generation/chapter.j2", **kwargs)

    def render_revision(self, pass_name: str, **kwargs) -> str:
        """Render a revision-pass prompt.

        *pass_name* is one of: ``structural``, ``voice_and_dialogue``,
        ``polish``.
        """
        return self.render(f"revision/{pass_name}.j2", **kwargs)

    def render_utility(self, task: str, **kwargs) -> str:
        """Render a utility prompt.

        *task* is one of: ``chapter_summary``, ``continuity_update``,
        ``consistency_check``.
        """
        return self.render(f"utility/{task}.j2", **kwargs)

    def render_validation(self, task: str, **kwargs) -> str:
        """Render a validation prompt.

        *task* is one of: ``semantic_contract``, ``adversarial_contract``.
        """
        return self.render(f"validation/{task}.j2", **kwargs)
