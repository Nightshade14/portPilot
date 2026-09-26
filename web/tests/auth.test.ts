import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { checkPasscode, isGateConfigured, signPasscode, verifyCookie } from "@/lib/auth";

const ORIGINAL_ENV = { ...process.env };

describe("auth", () => {
  beforeEach(() => {
    process.env.PORTPILOT_UI_PASSCODE = "correct-passcode";
    process.env.PORTPILOT_UI_SECRET = "test-secret-key";
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("reports the gate as configured when a passcode is set", () => {
    expect(isGateConfigured()).toBe(true);
  });

  it("reports the gate as open when no passcode is set", () => {
    delete process.env.PORTPILOT_UI_PASSCODE;
    expect(isGateConfigured()).toBe(false);
  });

  it("accepts the correct passcode", () => {
    expect(checkPasscode("correct-passcode")).toBe(true);
  });

  it("rejects an incorrect passcode", () => {
    expect(checkPasscode("wrong-passcode")).toBe(false);
  });

  it("rejects a passcode of a different length without throwing", () => {
    expect(checkPasscode("x")).toBe(false);
    expect(checkPasscode("a-very-long-incorrect-passcode-value")).toBe(false);
  });

  it("produces a verifiable HMAC cookie value for the correct passcode", async () => {
    const cookie = await signPasscode("correct-passcode");
    expect(await verifyCookie(cookie)).toBe(true);
  });

  it("rejects a tampered cookie value", async () => {
    const cookie = await signPasscode("correct-passcode");
    const tampered = cookie.slice(0, -1) + (cookie.endsWith("0") ? "1" : "0");
    expect(await verifyCookie(tampered)).toBe(false);
  });

  it("produces a deterministic signature for the same passcode", async () => {
    expect(await signPasscode("correct-passcode")).toBe(await signPasscode("correct-passcode"));
  });

  it("produces different signatures for different passcodes", async () => {
    expect(await signPasscode("a")).not.toBe(await signPasscode("b"));
  });
});
