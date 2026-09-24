import { describe, expect, it } from "vitest";
import { initialProjectionState } from "../../src/projection/reducer";
import { selectNeedsResnapshot, selectRuntimeStatus, selectSequence } from "../../src/projection/selectors";

describe("projection selectors", () => {
  it("does not invent runtime values", () => {
    const state = { ...initialProjectionState, lastSequence: 4, data: {} };
    expect(selectSequence(state)).toBe(4);
    expect(selectRuntimeStatus(state)).toBe("UNKNOWN");
    expect(selectNeedsResnapshot(state)).toBe(false);
  });
});
