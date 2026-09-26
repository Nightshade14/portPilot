/**
 * The proxy allow-list: which /api/pp/* paths + methods are forwarded.
 * Extracted from app/api/pp/[...path]/route.ts so it's unit-testable without
 * spinning up the Next.js route handler.
 */

export const GET_PATTERNS: RegExp[] = [
  /^health$/,
  /^runs$/,
  /^runs\/[^/]+$/,
  /^runs\/[^/]+\/steps\/[^/]+$/,
  /^runs\/[^/]+\/events$/,
  /^runs\/[^/]+\/artifacts$/,
  /^runs\/[^/]+\/artifacts\/[^/]+$/,
  /^runs\/[^/]+\/download$/,
  /^tools$/,
  /^tools\/[^/]+$/,
  /^knowledge\/search$/,
  /^knowledge$/,
];

export const POST_PATTERNS: RegExp[] = [
  /^runs$/,
  /^runs\/[^/]+\/pause$/,
  /^runs\/[^/]+\/resume$/,
  /^runs\/[^/]+\/cancel$/,
];

export function isAllowed(method: string, joinedPath: string): boolean {
  const patterns = method === "GET" ? GET_PATTERNS : method === "POST" ? POST_PATTERNS : [];
  return patterns.some((p) => p.test(joinedPath));
}
