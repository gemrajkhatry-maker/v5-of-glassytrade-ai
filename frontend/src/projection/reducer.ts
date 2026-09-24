import type { ProjectionEnvelope } from "../generated/ws_v1";

export interface ProjectionState {
  envelope: ProjectionEnvelope | null;
  data: Record<string, unknown>;
  lastSequence: number | null;
  needsResnapshot: boolean;
  error: string | null;
}

export type ProjectionAction =
  | { type: "message"; message: ProjectionEnvelope }
  | { type: "reset" }
  | { type: "error"; error: string };

export const initialProjectionState: ProjectionState = {
  envelope: null,
  data: {},
  lastSequence: null,
  needsResnapshot: false,
  error: null,
};

export function projectionReducer(
  state: ProjectionState,
  action: ProjectionAction,
): ProjectionState {
  if (action.type === "reset") return initialProjectionState;
  if (action.type === "error") {
    return { ...state, error: action.error, needsResnapshot: true };
  }
  const message = action.message;
  if (message.schemaVersion !== "1.0") {
    return {
      ...state,
      error: `unsupported schema version: ${message.schemaVersion}`,
      needsResnapshot: true,
    };
  }
  if (message.type === "snapshot") {
    return {
      envelope: message,
      data: { ...message.payload },
      lastSequence: message.sequence,
      needsResnapshot: false,
      error: null,
    };
  }
  if (state.lastSequence === null || message.baseSequence !== state.lastSequence) {
    return { ...state, needsResnapshot: true, error: "projection sequence gap" };
  }
  return {
    ...state,
    envelope: message,
    data: { ...state.data, ...message.payload },
    lastSequence: message.sequence,
    needsResnapshot: false,
    error: null,
  };
}
