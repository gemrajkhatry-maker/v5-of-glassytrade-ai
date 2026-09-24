// Generated from contracts/ws_v1.schema.json. Do not edit by hand.
export type ProjectionMode = "shadow" | "paper" | "live";
export type ProjectionType = "snapshot" | "delta";
export type ProjectionScope =
  | { type: "runtime" }
  | { type: "portfolio"; accountId: string }
  | { type: "contract"; contractId: string }
  | { type: "journal" };

export interface ProjectionEnvelope<TPayload = Record<string, unknown>> {
  schemaVersion: "1.0";
  projectionVersion: number;
  projectionId: string;
  scope: ProjectionScope;
  sequence: number;
  baseSequence: number | null;
  asOf: string;
  releaseId: string;
  configFingerprint: string;
  mode: ProjectionMode;
  type: ProjectionType;
  payload: TPayload;
}
