/**
 * hono-v1-miss: idiomatic-errors reference target (hackathon-authored stand-in).
 *
 * Business logic (coercion, truncation, defaults, trim/lowercase, seed) matches
 * the Flask source, so all success cases pass. But error handling is idiomatic
 * Hono/zod: validation failures return a default-style 400 with zod's flat body,
 * and unknown ids return a flat `{"error":"Not found"}` 404. This is exactly the
 * legacy error behavior that policy v1 is designed to miss, so this target fails:
 *   - normalize_rejects_invalid_payload_with_422   (400, not 422)
 *   - validate_missing_required_field_returns_422   (400, not 422)
 *   - validate_uncoercible_age_returns_422          (400, not 422)
 *   - get_profile_not_found_returns_nested_404      (flat 404 body)
 * and passes the other 6.
 */
import { serve } from "@hono/node-server";
import { zValidator } from "@hono/zod-validator";
import { Hono } from "hono";
import { z } from "zod";

const app = new Hono();

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

// Age coercion identical to the source: int as-is, float truncated, string
// trimmed then parsed and truncated; booleans not coercible; range 0..150.
const ageSchema = z
  .union([z.number(), z.string()])
  .transform((value, ctx) => {
    let age: number;
    if (typeof value === "number") {
      if (!Number.isFinite(value)) {
        ctx.addIssue({ code: "custom", message: "not_coercible" });
        return z.NEVER;
      }
      age = Math.trunc(value);
    } else {
      const text = value.trim();
      if (/^[+-]?\d+$/.test(text)) {
        age = parseInt(text, 10);
      } else {
        const f = Number(text);
        if (text === "" || Number.isNaN(f)) {
          ctx.addIssue({ code: "custom", message: "not_coercible" });
          return z.NEVER;
        }
        age = Math.trunc(f);
      }
    }
    if (age < 0 || age > 150) {
      ctx.addIssue({ code: "custom", message: "out_of_range" });
      return z.NEVER;
    }
    return age;
  });

const profileSchema = z
  .object({
    name: z.string().trim().min(1),
    email: z
      .string()
      .trim()
      .toLowerCase()
      .refine((e) => e.includes("@"), { message: "invalid_format" }),
    age: ageSchema,
    country: z.string().default("US"),
    newsletter: z.boolean().default(false),
    tags: z.array(z.string()).default([]),
  })
  .strict()
  .transform((p) => ({
    name: p.name,
    email: p.email,
    age: p.age,
    country: p.country,
    newsletter: p.newsletter,
    tags: p.tags,
  }));

app.get("/health", (c) => c.json({ ok: true }));

// zValidator with no custom hook => the default behavior: a 400 with zod's
// flat error body. This is the idiomatic miss.
app.post("/profiles/normalize", zValidator("json", profileSchema), (c) => {
  return c.json(c.req.valid("json"));
});

app.post("/profiles/validate", zValidator("json", profileSchema), (c) => {
  return c.json({ valid: true, errors: [] });
});

app.get("/profiles/:id", (c) => {
  const id = c.req.param("id");
  const profile = SEED[id];
  if (profile === undefined) return c.json({ error: "Not found" }, 404);
  return c.json(profile);
});

const port = Number(process.env.PORT ?? 8787);
serve({ fetch: app.fetch, port, hostname: "127.0.0.1" });
