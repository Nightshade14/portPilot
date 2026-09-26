"""create_candidate_policy. Owner: Lane D.

Deterministic and template-driven: parent body + rule blocks keyed by
diagnosis category, rationale citing failed case ids.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from portpilot.config import POLICY_NAME
from portpilot.harness.context import ctx
from portpilot.models import Diagnosis, Policy

# The nested error body copied verbatim from contracts/profile-api/v1/SPEC.md.
_NESTED_SCHEMA = (
    '{"error": {"code": "VALIDATION_FAILED", "message": "Invalid profile payload",\n'
    '           "details": [{"field": "age", "issue": "not_coercible"}]}}'
)

# One human-readable rule bullet per category. Lane B parses `## Rules` bullets
# into Policy.rules; these are the extra rules a candidate adds.
_RULE_BULLETS: dict[str, str] = {
    "error_status_and_schema": (
        "Return 422 for every validation failure and 404 for unknown ids, never 400, "
        "with the nested error schema and exact messages from the spec; validate "
        "manually or with a custom zod-validator hook, do not rely on default error "
        "responses."
    ),
    "defaults": (
        'Apply the spec defaults exactly: country "US", newsletter false, tags [], '
        "and always emit all six keys."
    ),
    "coercion": (
        "Coerce age exactly as the spec quirk requires: trim numeric strings, parse "
        "int or float, then truncate toward zero; reject booleans."
    ),
    "behavior_mismatch": (
        "Match the source response byte-for-byte on the cited cases; the source is "
        "the oracle, not idiomatic framework defaults."
    ),
}


def _error_status_and_schema_block() -> str:
    return (
        "## Rule block: error_status_and_schema\n"
        "- Return HTTP 422 for every validation failure and 404 for an unknown "
        "profile id. Never return 400.\n"
        "- Every error response uses this nested body verbatim, with the exact "
        "messages shown:\n\n"
        "```json\n"
        f"{_NESTED_SCHEMA}\n"
        "```\n\n"
        "- `code` is `VALIDATION_FAILED` for 422 and `NOT_FOUND` for 404.\n"
        '- `message` is "Invalid profile payload" for 422 and "Profile not found" '
        "for 404.\n"
        "- `details` carries one entry per failing field, in field order name, "
        "email, age, country, newsletter, tags, at most one issue per field.\n"
        "- `issue` values are `required`, `invalid_format` (email without `@`), "
        "`not_coercible`, `out_of_range`, `invalid_type`.\n"
        '- A 404 uses `details: [{"field": "id", "issue": "not_found"}]`.\n'
        "- A non-JSON or non-object body returns 422 with "
        '`details: [{"field": "body", "issue": "invalid_type"}]`.\n'
        "- Validate manually or with a custom zod-validator hook; do not rely on "
        "default error responses.\n"
    )


def _short_block(category: str) -> str:
    text = {
        "defaults": (
            '- Apply the spec defaults exactly: country "US", newsletter false, '
            "tags []. Always emit all six keys.\n"
        ),
        "coercion": (
            "- Coerce age with the legacy quirk: trim a numeric string, parse it as "
            'int or float, then truncate toward zero (" 042 " -> 42, "4.5" -> 4); '
            "booleans are not coercible.\n"
        ),
        "behavior_mismatch": (
            "- Match the live source response exactly on the cited cases. The source "
            "is the oracle; do not substitute idiomatic framework behavior.\n"
        ),
        "target_unreachable": (
            "- The generated target failed to boot or respond. Ensure src/index.ts "
            "serves on process.env.PORT at 127.0.0.1 and that GET /health returns "
            '{"ok": true}.\n'
        ),
    }.get(category, f"- Address the {category} mismatch on the cited cases.\n")
    return f"## Rule block: {category}\n{text}"


def _block_for(category: str) -> str:
    if category == "error_status_and_schema":
        return _error_status_and_schema_block()
    return _short_block(category)


def build_candidate(parent: Policy, diagnosis: Diagnosis) -> Policy:
    """Return Policy(version=parent.version+1, status="candidate", parent_version=...).

    Body = parent body + one `## Rule block: <category>` per diagnosed category.
    rules = parent rules + one new bullet per category. rationale cites case ids.
    """
    categories = diagnosis.categories

    blocks = [_block_for(category) for category in categories]
    body_parts = [parent.body.rstrip()]
    body_parts.extend(blocks)
    body = "\n\n".join(body_parts) + "\n"

    new_rules = [
        _RULE_BULLETS.get(category, f"Address the {category} mismatch.") for category in categories
    ]
    rules = [*parent.rules, *new_rules]

    ids = ", ".join(diagnosis.failed_case_ids) if diagnosis.failed_case_ids else "none"
    rationale = (
        f"Candidate v{parent.version + 1} addresses categories "
        f"{categories} for failed cases: {ids}."
    )

    return Policy(
        name=parent.name,
        version=parent.version + 1,
        status="candidate",
        body=body,
        rules=rules,
        parent_version=parent.version,
        rationale=rationale,
    )


@tool
def create_candidate_policy(run_id: str, diagnosis_id: str) -> dict[str, Any]:
    """Create and save a candidate migration policy from a stored diagnosis, and store
    a candidate_policy artifact.

    Args:
        run_id: The migration run id.
        diagnosis_id: Artifact id of the diagnosis to address.

    Returns:
        The candidate Policy as a dict.
    """
    store = ctx().store
    diagnosis_doc = store.get_artifact(diagnosis_id)
    diagnosis = Diagnosis.from_doc(diagnosis_doc["content"])
    parent = store.get_policy(POLICY_NAME)  # the active policy

    candidate = build_candidate(parent, diagnosis)
    store.save_policy(candidate)

    attempt = diagnosis.attempt
    artifact_id = store.put_artifact(run_id, "candidate_policy", attempt, candidate.to_doc())
    store.log_event(
        run_id,
        "decision",
        "candidate_policy",
        {
            "parent_version": parent.version,
            "candidate_version": candidate.version,
            "categories": diagnosis.categories,
            "artifact_id": artifact_id,
        },
    )
    return {**candidate.to_doc(), "artifact_id": artifact_id}
