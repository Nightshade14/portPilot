/**
 * hono-good: full-parity reference target (hackathon-authored stand-in).
 *
 * Reproduces the Flask source behavior exactly, including the nested legacy
 * error schema (422 VALIDATION_FAILED / 404 NOT_FOUND), field-ordered details,
 * issue codes, and JSON key order. Passes 10/10 against the contract suite.
 */
import { serve } from "@hono/node-server";
import { Hono } from "hono";

const app = new Hono();

const FIELD_ORDER = ["name", "email", "age", "country", "newsletter", "tags"];

type Detail = { field: string; issue: string };

const SEED: Record<string, unknown> = {
  p_001: {
    id: "p_001",
    name: "Ada Lovelace",
    email: "ada@example.com",
    age: 36,
    country: "GB",
    newsletter: true,
    tags: ["math", "computing"],
  },
};

function coerceAge(value: unknown): { age?: number; issue?: string } {
  // booleans are not coercible (checked before number, since typeof true === "boolean")
  if (typeof value === "boolean") return { issue: "not_coercible" };
  let age: number;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return { issue: "not_coercible" };
    age = Math.trunc(value);
  } else if (typeof value === "string") {
    const text = value.trim();
    // int-like first, then float-like, else not coercible
    if (/^[+-]?\d+$/.test(text)) {
      age = parseInt(text, 10);
    } else {
      const f = Number(text);
      if (text === "" || Number.isNaN(f)) return { issue: "not_coercible" };
      age = Math.trunc(f);
    }
  } else {
    return { issue: "not_coercible" };
  }
  if (age < 0 || age > 150) return { issue: "out_of_range" };
  return { age };
}

function normalize(payload: Record<string, unknown>): {
  profile?: Record<string, unknown>;
  details: Detail[];
} {
  const details: Detail[] = [];
  const profile: Record<string, unknown> = {};

  // name
  if (!("name" in payload)) {
    details.push({ field: "name", issue: "required" });
  } else if (typeof payload.name !== "string") {
    details.push({ field: "name", issue: "invalid_type" });
  } else {
    const name = payload.name.trim();
    if (name === "") details.push({ field: "name", issue: "required" });
    else profile.name = name;
  }

  // email
  if (!("email" in payload)) {
    details.push({ field: "email", issue: "required" });
  } else if (typeof payload.email !== "string") {
    details.push({ field: "email", issue: "invalid_type" });
  } else {
    const email = payload.email.trim().toLowerCase();
    if (email === "") details.push({ field: "email", issue: "required" });
    else if (!email.includes("@")) details.push({ field: "email", issue: "invalid_format" });
    else profile.email = email;
  }

  // age
  if (!("age" in payload)) {
    details.push({ field: "age", issue: "required" });
  } else {
    const { age, issue } = coerceAge(payload.age);
    if (issue) details.push({ field: "age", issue });
    else profile.age = age;
  }

  // country (optional, default "US")
  if (!("country" in payload)) {
    profile.country = "US";
  } else if (typeof payload.country !== "string") {
    details.push({ field: "country", issue: "invalid_type" });
  } else {
    profile.country = payload.country;
  }

  // newsletter (optional, default false)
  if (!("newsletter" in payload)) {
    profile.newsletter = false;
  } else if (typeof payload.newsletter !== "boolean") {
    details.push({ field: "newsletter", issue: "invalid_type" });
  } else {
    profile.newsletter = payload.newsletter;
  }

  // tags (optional, default [])
  if (!("tags" in payload)) {
    profile.tags = [];
  } else if (
    !Array.isArray(payload.tags) ||
    !payload.tags.every((t) => typeof t === "string")
  ) {
    details.push({ field: "tags", issue: "invalid_type" });
  } else {
    profile.tags = payload.tags;
  }

  if (details.length > 0) {
    details.sort((a, b) => FIELD_ORDER.indexOf(a.field) - FIELD_ORDER.indexOf(b.field));
    return { details };
  }

  // Fixed output key order.
  const ordered = {
    name: profile.name,
    email: profile.email,
    age: profile.age,
    country: profile.country,
    newsletter: profile.newsletter,
    tags: profile.tags,
  };
  return { profile: ordered, details: [] };
}

function validationError(details: Detail[]) {
  return {
    error: {
      code: "VALIDATION_FAILED",
      message: "Invalid profile payload",
      details,
    },
  };
}

function notFoundError() {
  return {
    error: {
      code: "NOT_FOUND",
      message: "Profile not found",
      details: [{ field: "id", issue: "not_found" }],
    },
  };
}

async function readObject(c: {
  req: { json: () => Promise<unknown> };
}): Promise<Record<string, unknown> | null> {
  try {
    const body = await c.req.json();
    if (body === null || typeof body !== "object" || Array.isArray(body)) return null;
    return body as Record<string, unknown>;
  } catch {
    return null;
  }
}

app.get("/health", (c) => c.json({ ok: true }));

app.post("/profiles/normalize", async (c) => {
  const payload = await readObject(c);
  if (payload === null) {
    return c.json(validationError([{ field: "body", issue: "invalid_type" }]), 422);
  }
  const { profile, details } = normalize(payload);
  if (details.length > 0) return c.json(validationError(details), 422);
  return c.json(profile);
});

app.post("/profiles/validate", async (c) => {
  const payload = await readObject(c);
  if (payload === null) {
    return c.json(validationError([{ field: "body", issue: "invalid_type" }]), 422);
  }
  const { details } = normalize(payload);
  if (details.length > 0) return c.json(validationError(details), 422);
  return c.json({ valid: true, errors: [] });
});

app.get("/profiles/:id", (c) => {
  const id = c.req.param("id");
  const profile = SEED[id];
  if (profile === undefined) return c.json(notFoundError(), 404);
  return c.json(profile);
});

const port = Number(process.env.PORT ?? 8787);
serve({ fetch: app.fetch, port, hostname: "127.0.0.1" });
