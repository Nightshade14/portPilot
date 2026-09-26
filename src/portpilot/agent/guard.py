"""Guardrails for the executor agent (lane-a.md build step 6).

`StepPolicy` is an `InterventionHandler` (verified shape: `Agent(interventions=[...])`,
`before_tool_call(self, event) -> Deny | Proceed`, `event.tool_use` a `ToolUse` dict --
docs/spikes/S2_STRANDS.md goal 6). It also owns the STP's turn/token/time budget and the
run-control / lease-heartbeat check, since both are naturally per-tool-call hooks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from strands.interventions import Deny, InterventionHandler, Proceed

from portpilot.core.models import Run, ShortTermPlan

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.core_tools import StepContext
    from portpilot.agent.deps import AgentDeps


class LeaseLost(Exception):
    """Raised to abort the run cleanly when the run's lease was lost mid-step."""


class BudgetExceeded(Exception):
    """Raised to stop the step when a turn/token/time budget is exhausted.

    Carries the same fields as the `budget_exceeded` event payload so callers (the loop,
    tests) can inspect what tripped without re-parsing a message.
    """

    def __init__(self, budget: str, used: int, limit: int) -> None:
        super().__init__(f"budget '{budget}' exceeded: used={used} limit={limit}")
        self.budget = budget
        self.used = used
        self.limit = limit


INSTALL_LIKE_GUIDANCE = "use install_cli_tool"


@dataclass
class StepPolicy(InterventionHandler):
    """Enforces the per-step allowed-tool set, denies install-like shell commands,
    stops the step on budget exhaustion, and checks pause/cancel + the lease heartbeat.

    `heartbeat_every_n_calls` bounds how often `run_store.heartbeat` and `run.control`
    are re-checked -- every tool call by default (n=1), which is cheap for the in-memory
    store and safe for a real one at STP call volumes.
    """

    name = "step-policy"

    deps: AgentDeps
    run: Run
    step: ShortTermPlan
    ctx: StepContext
    heartbeat_every_n_calls: int = 1
    _call_count: int = field(default=0, init=False)
    _start_time: float = field(default_factory=time.monotonic, init=False)
    _core_tool_names: frozenset[str] = field(default_factory=frozenset, init=False)

    def __post_init__(self) -> None:
        from portpilot.agent.core_tools import CORE_TOOL_NAMES

        selected = {p.name for p in self.step.selected_tools}
        # The sandbox shell/file_editor tools (real DockerSandbox tools or the
        # exec/write_file/read_file fallback in executor.py) are present in every STP
        # alongside the core tools, per MVP_PLAN §3.5 ("Core tools, present in every
        # STP") and core_tools.py's own docstring -- selection only governs *library*
        # tools, never these.
        self._core_tool_names = (
            frozenset(CORE_TOOL_NAMES)
            | selected
            | {
                "shell",
                "file_editor",
                "sandbox_shell",
                "sandbox_file_editor",
            }
        )

    def allowed_tool_names(self) -> frozenset[str]:
        # Mid-step loads join the allowed set the moment `load_tool` registers them.
        return self._core_tool_names | frozenset(self.ctx.mid_step_loaded_names)

    def before_tool_call(self, event: Any) -> Deny | Proceed:
        tool_name = event.tool_use.get("name", "")

        self._call_count += 1
        if self._call_count % self.heartbeat_every_n_calls == 0:
            self._check_control_and_lease()

        self._check_budgets()

        if tool_name not in self.allowed_tool_names():
            return Deny(
                reason=(
                    f"'{tool_name}' is not in this step's allowed tool set "
                    f"(core tools, the {len(self.step.selected_tools)} selected tools, "
                    "and any mid-step loads). Call search_tools/load_tool if you need "
                    "another capability."
                )
            )

        if tool_name in {"shell", "sandbox_shell"} and self.deps.shell_guard is not None:
            command = event.tool_use.get("input", {}).get("command", "")
            guidance = self.deps.shell_guard(command)
            if guidance:
                return Deny(reason=f"{guidance} ({INSTALL_LIKE_GUIDANCE})")

        return Proceed()

    def _check_control_and_lease(self) -> None:
        current = self.deps.run_store.get_run(self.run.run_id)
        if current.control == "cancel":
            raise LeaseLost(f"run {self.run.run_id} was cancelled")
        if current.lease is None:
            # No lease held (e.g. an offline/in-process run that never called
            # claim_run): nothing to lose, so there is nothing to check here.
            return
        alive = self.deps.run_store.heartbeat(self.run.run_id, current.lease.owner)
        if not alive:
            raise LeaseLost(f"lease lost for run {self.run.run_id}")

    def _check_budgets(self) -> None:
        budget = self.step.budget
        if self._call_count > budget.max_turns:
            self._emit_budget_exceeded("max_turns", self._call_count, budget.max_turns)
            raise BudgetExceeded("max_turns", self._call_count, budget.max_turns)

        elapsed_minutes = (time.monotonic() - self._start_time) / 60.0
        if elapsed_minutes > budget.max_minutes:
            self._emit_budget_exceeded("max_minutes", int(elapsed_minutes), budget.max_minutes)
            raise BudgetExceeded("max_minutes", int(elapsed_minutes), budget.max_minutes)

        agent = self.ctx._agent_ref
        if agent is not None:
            used_tokens = agent.event_loop_metrics.accumulated_usage.get("totalTokens", 0)
            if used_tokens > budget.max_tokens:
                self._emit_budget_exceeded("max_tokens", used_tokens, budget.max_tokens)
                raise BudgetExceeded("max_tokens", used_tokens, budget.max_tokens)

    def _emit_budget_exceeded(self, budget: str, used: int, limit: int) -> None:
        self.deps.run_store.log_event(
            self.run.run_id,
            "budget_exceeded",
            self.step.step_id,
            {"budget": budget, "used": used, "limit": limit},
        )


__all__ = ["INSTALL_LIKE_GUIDANCE", "BudgetExceeded", "LeaseLost", "StepPolicy"]
