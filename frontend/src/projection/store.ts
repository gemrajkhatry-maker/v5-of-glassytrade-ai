import { useSyncExternalStore } from "react";
import type { ProjectionEnvelope } from "../generated/ws_v1";
import {
  initialProjectionState,
  projectionReducer,
  type ProjectionAction,
  type ProjectionState,
} from "./reducer";

export type ProjectionListener = (state: ProjectionState) => void;

export class ProjectionStore {
  private state: ProjectionState = initialProjectionState;
  private readonly listeners = new Set<ProjectionListener>();

  getState = (): ProjectionState => this.state;

  dispatch = (action: ProjectionAction): void => {
    this.state = projectionReducer(this.state, action);
    for (const listener of this.listeners) listener(this.state);
  };

  apply = (message: ProjectionEnvelope): void => this.dispatch({ type: "message", message });

  subscribe = (listener: ProjectionListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}

export function useProjection(store: ProjectionStore): ProjectionState {
  return useSyncExternalStore(store.subscribe, store.getState, store.getState);
}
