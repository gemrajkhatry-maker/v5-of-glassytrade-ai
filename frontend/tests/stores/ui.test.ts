import { describe, it, expect, beforeEach } from 'vitest';
import { useUIStore, selectShowHalfTrend, selectShowHARSI, selectHarsiHeight } from '../../stores/ui';

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

describe('UI store HARSI toggle', () => {
    it('defaults to visible', () => {
        const state = useUIStore.getState();
        expect(state.showHARSI).toBe(true);
        expect(selectShowHARSI(state)).toBe(true);
    });

    it('toggles visibility', () => {
        useUIStore.getState().toggleHARSI();
        expect(useUIStore.getState().showHARSI).toBe(false);

        useUIStore.getState().toggleHARSI();
        expect(useUIStore.getState().showHARSI).toBe(true);
    });

    it('sets visibility explicitly', () => {
        useUIStore.getState().setHARSIVisible(false);
        expect(useUIStore.getState().showHARSI).toBe(false);
        useUIStore.getState().setHARSIVisible(true);
        expect(useUIStore.getState().showHARSI).toBe(true);
    });

    it('persists the HARSI toggle to localStorage', () => {
        useUIStore.getState().setHARSIVisible(false);
        const raw = localStorage.getItem('glassytrade-ui-state');
        expect(raw).toBeTruthy();
        const persisted = JSON.parse(raw as string);
        expect(persisted.state.showHARSI).toBe(false);
    });

    it('resetUI restores HARSI to visible', () => {
        useUIStore.getState().setHARSIVisible(false);
        useUIStore.getState().resetUI();
        expect(useUIStore.getState().showHARSI).toBe(true);
    });

    it('defaults harsiHeight to 180 and allows resizing', () => {
        const state = useUIStore.getState();
        expect(state.harsiHeight).toBe(180);
        expect(selectHarsiHeight(state)).toBe(180);

        useUIStore.getState().setHarsiHeight(240);
        expect(useUIStore.getState().harsiHeight).toBe(240);
        expect(selectHarsiHeight(useUIStore.getState())).toBe(240);
    });

    it('persists harsiHeight to localStorage', () => {
        useUIStore.getState().setHarsiHeight(220);
        const raw = localStorage.getItem('glassytrade-ui-state');
        expect(raw).toBeTruthy();
        const persisted = JSON.parse(raw as string);
        expect(persisted.state.harsiHeight).toBe(220);
    });
});