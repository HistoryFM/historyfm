"""Stage 1: Interactive Setup — gather user input to create the NovelSpec."""

from __future__ import annotations

import json
import logging

from sovereign_ink.models import NovelSpec
from sovereign_ink.pipeline.base import PipelineStage

logger = logging.getLogger(__name__)


class InteractiveSetupStage(PipelineStage):
    """Collect novel parameters interactively or accept a pre-built NovelSpec."""

    STAGE_NAME = "interactive_setup"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.novel_spec: NovelSpec | None = None

    def check_prerequisites(self) -> bool:
        return True

    def run(self) -> None:
        existing = self.state_manager.load_novel_spec()
        if existing and self.is_completed():
            logger.info("Novel spec already exists, skipping setup")
            return

        self._mark_started()

        try:
            if existing:
                spec = existing
                logger.info(
                    "Using existing NovelSpec from disk: %s",
                    spec.title or "Untitled",
                )
            elif self.novel_spec:
                spec = self.novel_spec
                logger.info(
                    "Using provided NovelSpec: %s", spec.title or "Untitled"
                )
            else:
                spec = self._interactive_setup()

            if spec.synopsis is None:
                spec = self._synopsis_selection(spec)

            self.state_manager.save_novel_spec(spec)
            logger.info("Novel spec saved successfully")
            self._mark_completed()

        except Exception as exc:
            self._mark_failed(str(exc))
            raise

    # ------------------------------------------------------------------
    # Interactive Q&A
    # ------------------------------------------------------------------

    def _interactive_setup(self) -> NovelSpec:
        """Run interactive Q&A to build the NovelSpec."""
        import questionary
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        console.print(
            Panel(
                "[bold cyan]Sovereign Ink — Novel Setup Wizard[/bold cyan]\n"
                "Let's define your historical novel.",
                expand=False,
            )
        )

        title = questionary.text(
            "Working title (leave blank to generate later):",
            default="",
        ).ask()

        era_start = int(
            questionary.text(
                "Era start year (1700-1900):",
                default="1789",
                validate=lambda x: x.isdigit() and 1700 <= int(x) <= 1900,
            ).ask()
        )

        era_end = int(
            questionary.text(
                "Era end year (1700-1900):",
                default="1799",
                validate=lambda x: x.isdigit() and 1700 <= int(x) <= 1900,
            ).ask()
        )

        region = questionary.text(
            "Region/Country:",
            default="France",
        ).ask()

        central_event = questionary.text(
            "Central historical event:",
            default="The French Revolution and the Terror",
        ).ask()

        tone = questionary.select(
            "Tone intensity:",
            choices=["dramatic", "highly_dramatic", "restrained_dramatic"],
            default="highly_dramatic",
        ).ask()

        pov_count = int(
            questionary.select(
                "Number of POV characters:",
                choices=["1", "2", "3", "4"],
                default="2",
            ).ask()
        )

        protagonist_type = questionary.select(
            "Protagonist type:",
            choices=["historical_figure", "fictional_character", "both"],
            default="both",
        ).ask()

        themes_input = questionary.text(
            "Thematic focus (comma-separated):",
            default="loyalty vs ambition, idealism vs pragmatism",
        ).ask()
        thematic_focus = [t.strip() for t in themes_input.split(",") if t.strip()]

        desired_length = questionary.select(
            "Desired length:",
            choices=["novella_50k", "novel_120k"],
            default="novella_50k",
        ).ask()

        additional_notes = questionary.text(
            "Additional notes (optional):",
            default="",
        ).ask()

        return NovelSpec(
            title=title or None,
            era_start=era_start,
            era_end=era_end,
            region=region,
            central_event=central_event,
            tone_intensity=tone,
            pov_count=pov_count,
            protagonist_type=protagonist_type,
            thematic_focus=thematic_focus,
            desired_length=desired_length,
            additional_notes=additional_notes or None,
        )

    # ------------------------------------------------------------------
    # Synopsis generation & selection
    # ------------------------------------------------------------------

    def _synopsis_selection(self, spec: NovelSpec) -> NovelSpec:
        """Generate 3 synopsis options and let the user pick one (or write their own)."""
        import questionary
        from rich.console import Console
        from rich.panel import Panel

        console = Console()

        while True:
            console.print(
                "\n[bold cyan]Generating 3 synopsis options...[/bold cyan]\n"
            )
            options = self._generate_synopsis_options(spec)

            if not options:
                console.print("[yellow]Could not generate synopsis options. "
                              "You can enter your own below.[/yellow]")
                custom = questionary.text(
                    "Enter your synopsis (or press Enter to retry):"
                ).ask()
                if custom and custom.strip():
                    spec.synopsis = custom.strip()
                    return spec
                continue

            for opt in options:
                console.print(Panel(
                    f"[bold]{opt['title']}[/bold]\n\n"
                    f"[cyan]Protagonists:[/cyan] {opt['protagonists']}\n"
                    f"[cyan]Central Conflict:[/cyan] {opt['central_conflict']}\n\n"
                    f"{opt['narrative_arc']}\n\n"
                    f"[dim italic]{opt['distinctive_angle']}[/dim italic]",
                    title=f"Option {opt['number']}",
                    expand=True,
                ))

            choice = questionary.select(
                "Choose a synopsis:",
                choices=[
                    "Option 1",
                    "Option 2",
                    "Option 3",
                    "Write my own",
                    "Regenerate (get 3 new options)",
                ],
            ).ask()

            if choice and choice.startswith("Option"):
                idx = int(choice.split()[1]) - 1
                chosen = options[idx]
                spec.synopsis = chosen["narrative_arc"]
                if not spec.title and chosen.get("title"):
                    spec.title = chosen["title"]
                console.print(f"\n[green]Selected: {chosen['title']}[/green]")
                return spec
            elif choice == "Write my own":
                custom = questionary.text(
                    "Enter your synopsis (150-300 words):"
                ).ask()
                if custom and custom.strip():
                    spec.synopsis = custom.strip()
                    return spec
            # else: "Regenerate" — loop continues

    def _generate_synopsis_options(self, spec: NovelSpec) -> list[dict]:
        """Call the LLM to produce 3 synopsis options."""
        system_prompt = self.prompts.render_system_prompt()
        user_prompt = self.prompts.render(
            "setup/synopsis_options.j2", novel_spec=spec
        )

        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_world_building,
            temperature=0.9,
            max_tokens=4096,
        )

        try:
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                lines = lines[1:] if lines[0].startswith("```") else lines
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)
            data = json.loads(content)
            return data.get("options", [])
        except (json.JSONDecodeError, Exception):
            logger.warning("Failed to parse synopsis options JSON")
            return []
