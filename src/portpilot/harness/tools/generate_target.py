"""generate_target. Owner: Lane C (critical path)."""

from __future__ import annotations

from strands import tool

from portpilot.config import POLICY_NAME, target_dir
from portpilot.harness.context import ctx
from portpilot.harness.generation import GenerationRequest, LLMGenerator, generate_into


@tool
def generate_target(run_id: str, attempt: int, policy_version: int) -> str:
    """Copy templates/hono-empty into a fresh runs/<run_id>/attempt-<n>-policy-v<k>/target/,
    generate src/** from the source analysis under the given policy, type-check it
    (one repair retry), and store a target_version artifact (manifest + hashes + path).

    Args:
        run_id: The migration run id.
        attempt: Attempt number (1 = v1 generation, 2 = regeneration, ...).
        policy_version: Policy version to generate under.

    Returns:
        The target_version artifact id.
    """
    c = ctx()
    store = c.store
    analysis_doc = store.latest_artifact(run_id, "source_analysis")
    if analysis_doc is None:
        raise RuntimeError(f"run {run_id} has no source_analysis artifact")
    policy = store.get_policy(POLICY_NAME, policy_version)
    milestone = "generation" if attempt == 1 else "regeneration"
    generator = c.generator or LLMGenerator(c.settings)

    request = GenerationRequest(
        milestone=milestone,
        policy=policy,
        analysis=analysis_doc["content"],
        attempt=attempt,
    )
    content = generate_into(target_dir(run_id, attempt, policy_version), request, generator)
    content.update(
        {
            "attempt": attempt,
            "policy_version": policy_version,
            "source_analysis_id": analysis_doc["artifact_id"],
            "generator": type(generator).__name__,
            "model_id": c.settings.model_id if c.generator is None else None,
        }
    )
    artifact_id = store.put_artifact(run_id, "target_version", attempt, content)
    store.log_event(
        run_id,
        "tool_result",
        milestone,
        {
            "tool": "generate_target",
            "artifact_id": artifact_id,
            "policy_version": policy_version,
            "files": [f["path"] for f in content["files"]],
            "typecheck_ok": content["typecheck"]["ok"],
            "repairs": content["typecheck"]["repairs"],
        },
    )
    if not content["typecheck"]["ok"]:
        raise RuntimeError(
            f"generated target does not type-check after repairs:\n{content['typecheck']['output']}"
        )
    return artifact_id
