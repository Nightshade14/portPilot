"""Core tools available in every STP (lane-a.md build step 5).

Built as closures over a per-step `StepContext` so each STP's executor `Agent` gets a
fresh, independently-stateful set of `@tool` functions (see `agent/executor.py`, which
builds one `StepContext` per `execute_step` call). `agent/guard.py`'s `StepPolicy`
computes the allowed-tool set from `StepContext.core_tool_names()` plus the selected
and mid-step-loaded tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from strands import tool

from portpilot.core.interfaces import NotFound
from portpilot.core.models import (
    KnowledgeItem,
    KnowledgeSource,
    Run,
    ShortTermPlan,
    ToolPick,
    new_id,
)

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

CORE_TOOL_NAMES: tuple[str, ...] = (
    "complete_step",
    "search_knowledge",
    "search_tools",
    "load_tool",
    "create_tool",
    "check_environment",
    "install_cli_tool",
    "record_lesson",
    "record_gotcha",
)


@dataclass
class StepContext:
    """Mutable state one executor `Agent` invocation shares across its core tools."""

    deps: AgentDeps
    run: Run
    step: ShortTermPlan
    mid_step_loads: int = 0
    mid_step_loaded_names: set[str] = field(default_factory=set)
    tools_created: int = 0
    step_complete: bool = False
    completion_summary: str = ""
    tools_used: dict[str, bool] = field(default_factory=dict)  # name -> helped?
    _agent_ref: Any = field(default=None, repr=False)  # set by executor after Agent() construction

    def mark_used(self, name: str, ok: bool) -> None:
        # First failure sticks unless a later success overrides -- "helped" is generous
        # (any successful use counts), matching lane-a.md step 11's usage-stats intent.
        self.tools_used[name] = self.tools_used.get(name, False) or ok


def build_core_tools(ctx: StepContext) -> list[Any]:
    """Return the ~11 `@tool` functions for this step's executor agent."""

    deps = ctx.deps
    run = ctx.run
    step = ctx.step

    @tool
    def complete_step(summary: str) -> str:
        """Signal that the step's work is done and ready for the harness to verify.

        Args:
            summary: A short account of what was changed and why, for the digest.
        """
        ctx.step_complete = True
        ctx.completion_summary = summary
        return "Recorded. The harness will now run the acceptance checks."

    @tool
    def search_knowledge(
        query: str,
        kinds: list[str] | None = None,
        mode: Literal["hybrid", "vector", "text"] = "hybrid",
    ) -> str:
        """Search recorded lessons, gotchas and other knowledge relevant to the current work.

        Args:
            query: What to search for.
            kinds: Restrict to these knowledge kinds (e.g. ["lesson", "gotcha"]). Omit for all kinds.
            mode: "hybrid" (default), "vector", or "text".
        """
        hits = deps.knowledge.search(query, kinds=kinds, mode=mode, limit=8)  # type: ignore[arg-type]
        if not hits:
            return "No matching knowledge found."
        return "\n".join(f"- [{h.item.kind}] {h.item.title}: {h.item.body}" for h in hits)

    @tool
    def search_tools(query: str) -> str:
        """Search the tool library for tools that might help with the current step.

        Args:
            query: What capability you are looking for.
        """
        if deps.tool_library is None:
            return "No tool library is configured for this run."
        cards = deps.tool_library.candidates(query, limit=10)
        if not cards:
            return "No matching tools found."
        return "\n".join(
            f"- {c.name}@{c.version}: {c.description} ({c.when_to_use})" for c in cards
        )

    @tool
    def load_tool(name: str, reason: str) -> str:
        """Load an additional library tool mid-step, beyond the ones already selected.

        Args:
            name: The tool's name (as returned by search_tools).
            reason: Why this tool is needed now.
        """
        if deps.tool_library is None:
            return "unavailable: no tool library is configured for this run."
        if ctx.mid_step_loads >= run.budgets.max_mid_step_loads:
            return (
                f"refused: mid-step load cap reached ({run.budgets.max_mid_step_loads} "
                "for this run); this step already loaded its allowance."
            )
        try:
            record = deps.tool_library.get(name)
        except NotFound as exc:
            return f"could not load {name!r}: {exc}"

        agent_tool = deps.tool_library.as_agent_tool(record, run.run_id)
        agent = ctx._agent_ref
        if agent is not None:
            try:
                agent.tool_registry.register_dynamic_tool(agent_tool)
            except ValueError as exc:
                return f"could not register {name!r}: {exc}"
        ctx.mid_step_loads += 1
        ctx.mid_step_loaded_names.add(name)
        deps.run_store.log_event(
            run.run_id,
            "tool_loaded",
            step.step_id,
            {"name": name, "version": record.version, "reason": reason},
        )
        return f"loaded {name}@{record.version}: {reason}"

    @tool
    def create_tool(name: str, purpose: str, requirements: str) -> str:
        """Author a new library tool via the toolsmith, when no existing tool covers a capability.

        Limited to `budgets.max_tools_created` per run. On success the tool is made
        usable immediately, for this step, as if it had been selected at the start.

        Args:
            name: snake_case tool name.
            purpose: What the tool does and when to use it.
            requirements: The input/output shape and behavior the tool must have; the
                toolsmith decides the concrete schema, files and tests.
        """
        if deps.author_tool is None:
            return "unavailable: no toolsmith is configured for this run."
        if ctx.tools_created >= run.budgets.max_tools_created:
            return (
                f"refused: this run already created {ctx.tools_created} tools "
                f"(cap: {run.budgets.max_tools_created})."
            )

        result = deps.author_tool(
            run_id=run.run_id,
            step_id=step.step_id,
            name=name,
            purpose=purpose,
            requirements=requirements,
        )
        ctx.tools_created += 1
        if not result.get("ok"):
            return f"tool creation failed: {result.get('reason', 'unknown reason')}"

        version = result.get("version")
        created_name = result.get("name", name)
        if version is None:
            # Created but not yet an active/loadable version (e.g. still validating).
            return f"created {created_name} (not yet usable): {result.get('reason', '')}"

        record = deps.tool_store.get(created_name, version)
        agent_tool = (
            deps.tool_library.as_agent_tool(record, run.run_id) if deps.tool_library else None
        )
        agent = ctx._agent_ref
        if agent is not None and agent_tool is not None:
            try:
                agent.tool_registry.register_dynamic_tool(agent_tool)
            except ValueError:
                pass  # already registered under this name; still make it selected below
        ctx.mid_step_loaded_names.add(created_name)
        step.selected_tools.append(
            ToolPick(name=created_name, version=version, reason="created this step")
        )
        deps.run_store.update_step(step.step_id, selected_tools=step.selected_tools)
        return f"created and activated {created_name}@{version} for this step"

    @tool
    def check_environment() -> str:
        """Report the sandbox's OS, architecture, installed CLIs, and free disk/memory."""
        report = deps.installer.check_environment(run.run_id)
        deps.run_store.log_event(
            run.run_id,
            "cli_checked",
            step.step_id,
            {"installed": report.get("installed", {}), "arch": report.get("arch", "")},
        )
        return str(report)

    @tool
    def install_cli_tool(name: str) -> str:
        """Install a CLI tool from the reviewed allow-list into the sandbox.

        Args:
            name: The CLI's name, exactly as listed in config/cli_allowlist.yaml.
        """
        result = deps.installer.install(run.run_id, name)
        manifest = list(run.cli_manifest)
        if result.ok:
            manifest.append({"name": result.name, "version": result.version})
            deps.run_store.update_run(run.run_id, cli_manifest=manifest)
            deps.run_store.log_event(
                run.run_id,
                "cli_installed",
                step.step_id,
                {
                    "name": result.name,
                    "version": result.version,
                    "already_installed": result.already_installed,
                },
            )
            return f"installed {result.name}@{result.version}"
        deps.run_store.log_event(
            run.run_id,
            "cli_refused",
            step.step_id,
            {"name": name, "reason": result.reason or "refused"},
        )
        return f"refused: {result.reason or 'not on the allow-list'}"

    @tool
    def record_lesson(title: str, body: str, tags: list[str] | None = None) -> str:
        """Record a durable lesson learned during this step.

        Args:
            title: Short title.
            body: What was learned and why it matters.
            tags: Optional tags for search (e.g. language, framework).
        """
        item = KnowledgeItem(
            id=new_id("lesson"),
            kind="lesson",
            title=title,
            body=body,
            tags=tags or [],
            sources=[
                KnowledgeSource(run_id=run.run_id, step_id=step.step_id, repo_url=run.repo_url)
            ],
        )
        item_id = deps.knowledge.upsert(item)
        merged = item_id != item.id
        deps.run_store.log_event(
            run.run_id,
            "lesson_recorded",
            step.step_id,
            {"item_id": item_id, "title": title, "merged": merged},
        )
        return f"recorded lesson {item_id}" + (" (merged into existing)" if merged else "")

    @tool
    def record_gotcha(
        title: str, symptom: str, cause: str, fix: str, tags: list[str] | None = None
    ) -> str:
        """Record a specific failure mode and how to avoid or fix it.

        Args:
            title: Short title.
            symptom: What went wrong / how it showed up.
            cause: The root cause.
            fix: How to avoid or resolve it.
            tags: Optional tags for search.
        """
        body = f"Symptom: {symptom}\nCause: {cause}\nFix: {fix}"
        item = KnowledgeItem(
            id=new_id("gotcha"),
            kind="gotcha",
            title=title,
            body=body,
            tags=tags or [],
            sources=[
                KnowledgeSource(run_id=run.run_id, step_id=step.step_id, repo_url=run.repo_url)
            ],
        )
        item_id = deps.knowledge.upsert(item)
        merged = item_id != item.id
        deps.run_store.log_event(
            run.run_id,
            "gotcha_recorded",
            step.step_id,
            {"item_id": item_id, "title": title, "merged": merged},
        )
        return f"recorded gotcha {item_id}" + (" (merged into existing)" if merged else "")

    return [
        complete_step,
        search_knowledge,
        search_tools,
        load_tool,
        create_tool,
        check_environment,
        install_cli_tool,
        record_lesson,
        record_gotcha,
    ]


__all__ = ["CORE_TOOL_NAMES", "StepContext", "build_core_tools"]
