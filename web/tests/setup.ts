import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// `globals: false` in vitest.config.ts means Testing Library's automatic
// afterEach cleanup (which relies on the vitest globals) never registers,
// so each rendered component would otherwise pile up in the jsdom document
// across tests in the same file. Register it explicitly instead.
afterEach(() => {
  cleanup();
});
