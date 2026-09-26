"""Strands @tool wrappers (plan 4.5). Lane C wires them; owners implement logic.

Every tool reads the store from portpilot.harness.context.ctx().
"""

from portpilot.harness.tools.create_candidate_policy import create_candidate_policy
from portpilot.harness.tools.diagnose_failure import diagnose_failure
from portpilot.harness.tools.evaluate_policy import evaluate_policy
from portpilot.harness.tools.generate_target import generate_target
from portpilot.harness.tools.inspect_source import inspect_source
from portpilot.harness.tools.persist_checkpoint import persist_checkpoint
from portpilot.harness.tools.run_contract_tests import run_contract_tests

ALL_TOOLS = [
    inspect_source,
    generate_target,
    run_contract_tests,
    diagnose_failure,
    create_candidate_policy,
    evaluate_policy,
    persist_checkpoint,
]

__all__ = [
    "ALL_TOOLS",
    "create_candidate_policy",
    "diagnose_failure",
    "evaluate_policy",
    "generate_target",
    "inspect_source",
    "persist_checkpoint",
    "run_contract_tests",
]
