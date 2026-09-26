"""Acceptance-check verification (lane-a.md build step 9).

The harness runs each `Check` through the sandbox and decides pass/fail -- the agent's
own `complete_step` claim is never trusted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from portpilot.core.models import Run, ShortTermPlan

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps


def verify_step(deps: AgentDeps, run: Run, step: ShortTermPlan) -> bool:
    """Run every acceptance check; emit `step_verified`; return overall pass/fail."""

    checks_report = []
    all_ok = True
    for check in step.acceptance:
        result = deps.sandbox.exec(run.run_id, check.command, timeout_s=check.timeout_s)
        ok = result.exit_code == check.expect_exit
        all_ok = all_ok and ok
        checks_report.append({"name": check.name, "ok": ok, "exit_code": result.exit_code})

    deps.run_store.log_event(
        run.run_id, "step_verified", step.step_id, {"ok": all_ok, "checks": checks_report}
    )
    return all_ok


__all__ = ["verify_step"]
