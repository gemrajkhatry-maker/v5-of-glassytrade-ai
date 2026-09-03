import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore, selectShowHalfTrend } from '../../stores/ui';

// The zustand persist middleware writes to localStorage; reset it between
// tests so a previous suite run can't leak persisted state.
beforeEach(() => {
    localStorage.clear();
});

describe('UI store HalfTrend toggle', () => {
    it('defaults to visible', () => {
        const state = useUIStore.getState();
        expect(state.showHalfTrend).toBe(true);
        expect(selectShowHalfTrend(state)).toBe(true);
    });

    it('toggles visibility', () => {
        useUIStore.getState().toggleHalfTrend();
        expect(useUIStore.getState().showHalfTrend).toBe(false);

        useUIStore.getState().toggleHalfTrend();
        expect(useUIStore.getState().showHalfTrend).toBe(true);
    });

    it('sets visibility explicitly', () => {
        useUIStore.getState().setHalfTrendVisible(false);
        expect(useUIStore.getState().showHalfTrend).toBe(false);
        useUIStore.getState().setHalfTrendVisible(true);
        expect(useUIStore.getState().showHalfTrend).toBe(true);
    });

    it('persists the toggle to localStorage (workspace save)', () => {
        useUIStore.getState().setHalfTrendVisible(false);
        const raw = localStorage.getItem('glassytrade-ui-state');
        expect(raw).toBeTruthy();
        const persisted = JSON.parse(raw as string);
        expect(persisted.state.showHalfTrend).toBe(false);
    });

    it('resetUI restores the toggle to visible', () => {
        useUIStore.getState().setHalfTrendVisible(false);
        useUIStore.getState().resetUI();
        expect(useUIStore.getState().showHalfTrend).toBe(true);
    });
});