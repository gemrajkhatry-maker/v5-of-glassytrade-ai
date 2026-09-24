import { describe, expect, it } from "vitest";
import { projectionReducer, initialProjectionState } from "../../src/projection/reducer";
import type { ProjectionEnvelope } from "../../src/generated/ws_v1";

function envelope(overrides: Partial<ProjectionEnvelope> = {}): ProjectionEnvelope {
  return {
    schemaVersion: "1.0",
    projectionVersion: 1,
    projectionId: "runtime-main",
    scope: { type: "runtime" },
    sequence: 2,
    baseSequence: 1,
    asOf: "2026-09-24T10:00:00+05:30",
    releaseId: "release-test",
    configFingerprint: "fp-test",
    mode: "paper",
    type: "delta",
    payload: { status: "ready" },
    ...overrides,
  };
}

describe("projectionReducer", () => {
  it("applies a full snapshot", () => {
    const next = projectionReducer(initialProjectionState, {
      type: "message",
      message: envelope({ type: "snapshot", baseSequence: null, sequence: 1 }),
    });
    expect(next.lastSequence).toBe(1);
    expect(next.data.status).toBe("ready");
  });

  it("requests resnapshot on a sequence gap", () => {
    const state = projectionReducer(initialProjectionState, {
      type: "message",
      message: envelope({ type: "snapshot", baseSequence: null, sequence: 1 }),
    });
    const next = projectionReducer(state, {
      type: "message",
      message: envelope({ baseSequence: 4, sequence: 6 }),
    });
    expect(next.needsResnapshot).toBe(true);
    expect(next.lastSequence).toBe(1);
  });

  it("rejects unsupported schema versions", () => {
    const next = projectionReducer(initialProjectionState, {
      type: "message",
      message: envelope({ schemaVersion: "2.0" as "1.0" }),
    });
    expect(next.error).toContain("unsupported schema");
  });
});
