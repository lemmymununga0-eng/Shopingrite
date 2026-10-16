import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom has no ResizeObserver (Recharts needs one).
globalThis.ResizeObserver = globalThis.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };

beforeEach(() => { try { localStorage.clear(); } catch { /* storage unavailable */ } });
afterEach(() => cleanup());
