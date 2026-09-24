"""Generate the frontend projection types from the versioned WS schema."""

from __future__ import annotations

import argparse
from pathlib import Path

TYPESCRIPT = """// Generated from contracts/ws_v1.schema.json. Do not edit by hand.
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
"""


def generate_typescript(output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(TYPESCRIPT, encoding="utf-8")
    return TYPESCRIPT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate_typescript(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
