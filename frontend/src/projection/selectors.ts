import type { ProjectionState } from "./reducer";

export function selectEnvelope(state: ProjectionState) {
  return state.envelope;
}

export function selectPayload(state: ProjectionState) {
  return state.data;
}

export function selectSequence(state: ProjectionState) {
  return state.lastSequence;
}

export function selectNeedsResnapshot(state: ProjectionState) {
  return state.needsResnapshot;
}

export function selectRuntimeStatus(state: ProjectionState) {
  const value = state.data.status;
  return typeof value === "string" ? value : "UNKNOWN";
}
