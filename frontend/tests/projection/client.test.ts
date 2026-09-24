import { describe, expect, it } from "vitest";
import { ProjectionClient, type ProjectionSocket } from "../../src/projection/client";
import type { ProjectionEnvelope } from "../../src/generated/ws_v1";

function message(sequence: number): ProjectionEnvelope {
  return {
    schemaVersion: "1.0",
    projectionVersion: 1,
    projectionId: "runtime-main",
    scope: { type: "runtime" },
    sequence,
    baseSequence: sequence - 1,
    asOf: "2026-09-24T10:00:00+05:30",
    releaseId: "release-test",
    configFingerprint: "fp-test",
    mode: "paper",
    type: "delta",
    payload: { sequence },
  };
}

describe("ProjectionClient", () => {
  it("forwards messages and exposes no trading method", () => {
    let socket: ProjectionSocket | null = null;
    const received: ProjectionEnvelope[] = [];
    const client = new ProjectionClient(
      "ws://localhost/api/v1/ws/projections",
      (value) => received.push(value),
      () => undefined,
      () => {
        socket = {
          close: () => undefined,
          onmessage: null,
          onerror: null,
          onclose: null,
        };
        return socket;
      },
    );
    client.connect();
    socket!.onmessage!({ data: JSON.stringify(message(2)) } as MessageEvent<string>);
    expect(received).toHaveLength(1);
    expect((client as unknown as Record<string, unknown>).placeOrder).toBeUndefined();
    client.close();
  });
});
