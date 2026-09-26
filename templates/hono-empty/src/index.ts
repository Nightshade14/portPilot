// Empty PortPilot target. generate_target replaces everything under src/.
import { serve } from "@hono/node-server";
import { Hono } from "hono";

const app = new Hono();

app.get("/health", (c) => c.json({ ok: true }));

serve({ fetch: app.fetch, port: Number(process.env.PORT ?? 8787), hostname: "127.0.0.1" });
