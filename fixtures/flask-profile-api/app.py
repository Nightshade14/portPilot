"""Legacy Profile Normalization API (the migration source of truth).

Plain, readable Flask so the harness can read it as the "legacy" service.
Behavior is specified by contracts/profile-api/v1/SPEC.md; this app is the
oracle the contract runner compares generated targets against.

Run: python app.py --port 5001   (binds 127.0.0.1 only)
"""

from __future__ import annotations

import argparse

from flask import Flask, jsonify, request

app = Flask(__name__)
# Preserve insertion order of keys in JSON responses (legacy behavior).
app.json.sort_keys = False

# In-memory seed. The only stored profile is p_001.
PROFILES: dict[str, dict] = {
    "p_001": {
        "id": "p_001",
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "age": 36,
        "country": "GB",
        "newsletter": True,
        "tags": ["math", "computing"],
    }
}

# Field order used for error `details`. At most one issue per field.
FIELD_ORDER = ["name", "email", "age", "country", "newsletter", "tags"]


def _validation_error(details: list[dict]):
    body = {
        "error": {
            "code": "VALIDATION_FAILED",
            "message": "Invalid profile payload",
            "details": details,
        }
    }
    return jsonify(body), 422


def _not_found_error():
    body = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Profile not found",
            "details": [{"field": "id", "issue": "not_found"}],
        }
    }
    return jsonify(body), 404


def _coerce_age(value):
    """Return (age_int, issue). issue is None on success.

    Rules: int as-is; float truncated toward zero; string trimmed then parsed
    as int or float and truncated; booleans are not coercible; must be 0..150.
    """
    # bool is a subclass of int, so reject it before the int branch.
    if isinstance(value, bool):
        return None, "not_coercible"
    if isinstance(value, int):
        age = value
    elif isinstance(value, float):
        age = int(value)  # truncate toward zero
    elif isinstance(value, str):
        text = value.strip()
        try:
            age = int(text)
        except ValueError:
            try:
                age = int(float(text))  # "4.5" -> 4
            except ValueError:
                return None, "not_coercible"
    else:
        return None, "not_coercible"
    if age < 0 or age > 150:
        return None, "out_of_range"
    return age, None


def _normalize(payload: dict):
    """Return (profile, details). details is [] on success."""
    details: list[dict] = []
    profile: dict = {}

    # name: required string, trimmed; empty after trim counts as missing.
    if "name" not in payload:
        details.append({"field": "name", "issue": "required"})
    elif not isinstance(payload["name"], str):
        details.append({"field": "name", "issue": "invalid_type"})
    else:
        name = payload["name"].strip()
        if name == "":
            details.append({"field": "name", "issue": "required"})
        else:
            profile["name"] = name

    # email: required string, trimmed and lowercased; must contain '@'.
    if "email" not in payload:
        details.append({"field": "email", "issue": "required"})
    elif not isinstance(payload["email"], str):
        details.append({"field": "email", "issue": "invalid_type"})
    else:
        email = payload["email"].strip().lower()
        if email == "":
            details.append({"field": "email", "issue": "required"})
        elif "@" not in email:
            details.append({"field": "email", "issue": "invalid_format"})
        else:
            profile["email"] = email

    # age: required; coerce per rules above.
    if "age" not in payload:
        details.append({"field": "age", "issue": "required"})
    else:
        age, issue = _coerce_age(payload["age"])
        if issue is not None:
            details.append({"field": "age", "issue": issue})
        else:
            profile["age"] = age

    # country: optional string, as given; default "US".
    if "country" not in payload:
        profile["country"] = "US"
    elif not isinstance(payload["country"], str):
        details.append({"field": "country", "issue": "invalid_type"})
    else:
        profile["country"] = payload["country"]

    # newsletter: optional boolean; default false.
    if "newsletter" not in payload:
        profile["newsletter"] = False
    elif not isinstance(payload["newsletter"], bool):
        details.append({"field": "newsletter", "issue": "invalid_type"})
    else:
        profile["newsletter"] = payload["newsletter"]

    # tags: optional list of strings; default [].
    if "tags" not in payload:
        profile["tags"] = []
    elif not isinstance(payload["tags"], list) or not all(
        isinstance(t, str) for t in payload["tags"]
    ):
        details.append({"field": "tags", "issue": "invalid_type"})
    else:
        profile["tags"] = payload["tags"]

    if details:
        # Sort details into canonical field order (one issue per field already).
        details.sort(key=lambda d: FIELD_ORDER.index(d["field"]))
        return None, details

    # Emit keys in the fixed output order.
    ordered = {
        "name": profile["name"],
        "email": profile["email"],
        "age": profile["age"],
        "country": profile["country"],
        "newsletter": profile["newsletter"],
        "tags": profile["tags"],
    }
    return ordered, []


def _read_json_object():
    """Return (payload, error_response). error_response set if body invalid."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _validation_error([{"field": "body", "issue": "invalid_type"}])
    return payload, None


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/profiles/normalize")
def normalize():
    payload, err = _read_json_object()
    if err is not None:
        return err
    profile, details = _normalize(payload)
    if details:
        return _validation_error(details)
    return jsonify(profile)


@app.post("/profiles/validate")
def validate():
    payload, err = _read_json_object()
    if err is not None:
        return err
    _, details = _normalize(payload)
    if details:
        return _validation_error(details)
    return jsonify({"valid": True, "errors": []})


@app.get("/profiles/<profile_id>")
def get_profile(profile_id: str):
    profile = PROFILES.get(profile_id)
    if profile is None:
        return _not_found_error()
    return jsonify(profile)


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile Normalization API (legacy source)")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    app.run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
