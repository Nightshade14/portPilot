import "server-only";

/**
 * Access-gate helpers: constant-time passcode check + HMAC session cookie.
 * The cookie is HMAC(passcode, PORTPILOT_UI_SECRET), never the raw passcode.
 *
 * Uses Web Crypto (globalThis.crypto.subtle) rather than node:crypto so this
 * module works in both the Node.js runtime (Server Actions, route handlers)
 * and the Edge runtime (middleware).
 */

export const AUTH_COOKIE_NAME = "pp_auth";

export function isGateConfigured(): boolean {
  return Boolean(process.env.PORTPILOT_UI_PASSCODE);
}

function getSecret(): string {
  const secret = process.env.PORTPILOT_UI_SECRET;
  if (!secret) {
    throw new Error("PORTPILOT_UI_SECRET must be set when PORTPILOT_UI_PASSCODE is configured.");
  }
  return secret;
}

async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function signPasscode(passcode: string): Promise<string> {
  return hmacHex(getSecret(), passcode);
}

function timingSafeEqualStrings(a: string, b: string): boolean {
  const bufA = new TextEncoder().encode(a);
  const bufB = new TextEncoder().encode(b);
  // Constant-time regardless of length: compare against a fixed-size buffer
  // so early return on length doesn't leak timing beyond what's unavoidable.
  const maxLen = Math.max(bufA.length, bufB.length, 32);
  let diff = bufA.length ^ bufB.length;
  for (let i = 0; i < maxLen; i++) {
    const byteA = i < bufA.length ? bufA[i]! : 0;
    const byteB = i < bufB.length ? bufB[i]! : 0;
    diff |= byteA ^ byteB;
  }
  return diff === 0;
}

/** Constant-time compare of the submitted passcode against the configured one. */
export function checkPasscode(submitted: string): boolean {
  const expected = process.env.PORTPILOT_UI_PASSCODE ?? "";
  return timingSafeEqualStrings(submitted, expected);
}

/** Verifies a cookie value against the expected HMAC for the configured passcode. */
export async function verifyCookie(cookieValue: string): Promise<boolean> {
  const expected = await hmacHex(getSecret(), process.env.PORTPILOT_UI_PASSCODE ?? "");
  return timingSafeEqualStrings(cookieValue, expected);
}
