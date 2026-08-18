import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ProfileOverlayInfo } from '../../components/ProfileOverlayInfo';
import { AMTAnalysis } from '../../types';

const baseAmt = (overrides: Partial<AMTAnalysis> = {}): AMTAnalysis => ({
  marketState: 'BALANCED',
  poc: 103.93,
  valueAreaHigh: 105.04,
  valueAreaLow: 94.61,
  lvns: [],
  hvns: [],
  aggression: 0,
  setup: null,
  profile: [],
  aggressivePrints: [],
  legProfile: [],
  legLvns: [],
  legPoc: 103.75,
  legVah: 105,
  legVal: 103.3,
  hasDisplacement: true,
  ...overrides,
});

describe('ProfileOverlayInfo', () => {
  it('shows MCX session hours and POC/VA inline', () => {
    const { container } = render(<ProfileOverlayInfo amt={baseAmt()} mode="session" symbol="CRUDEOIL 17 AUG 7950 CALL" />);
    expect(screen.getByText(/09:00-23:30 IST/i)).toBeTruthy();
    expect(container.textContent).toContain('POC');
    expect(container.textContent).toContain('103.93');
  });

  it('shows NSE 09:15 session hours', () => {
    render(<ProfileOverlayInfo amt={baseAmt()} mode="session" symbol="NIFTY 18 AUG 24550 CALL" />);
    expect(screen.getByText(/09:15-15:30 IST/i)).toBeTruthy();
  });

  it('labels the leg profile as orange displacement leg', () => {
    render(<ProfileOverlayInfo amt={baseAmt()} mode="leg" symbol="NIFTY 18 AUG 24550 CALL" />);
    expect(screen.getByText(/DISPLACEMENT LEG/i)).toBeTruthy();
  });

  it('shows a CONFLUENCE badge in combined mode', () => {
    render(<ProfileOverlayInfo amt={baseAmt({ poc: 100, legPoc: 100.05 })} mode="combined" symbol="NIFTY 18 AUG 24550 CALL" />);
    expect(screen.getByText(/CONFLUENCE/i)).toBeTruthy();
  });

  it('shows a DIVERGENCE badge for far-apart POCs', () => {
    render(<ProfileOverlayInfo amt={baseAmt({ poc: 100, legPoc: 102 })} mode="combined" symbol="NIFTY 18 AUG 24550 CALL" />);
    expect(screen.getByText(/DIVERGENCE/i)).toBeTruthy();
  });

  it('shows value migration drift once two 15-min windows have data', () => {
    const amt = baseAmt({
      valueMigration: {
        direction: 'MIGRATING_UP',
        pocDrift: 2.1,
        vahDrift: 3.0,
        valDrift: 1.2,
        windowLabel: '09:00→09:15',
        hasMigration: true,
      },
    });
    const { container } = render(<ProfileOverlayInfo amt={amt} mode="session" symbol="CRUDEOIL 17 AUG 7950 CALL" />);
    expect(screen.getByText(/MIGRATION/i)).toBeTruthy();
    expect(container.textContent).toContain('MIGRATING_UP');
    expect(container.textContent).toContain('+2.10');
    expect(container.textContent).toContain('09:00→09:15');
  });

  it('hides the migration line before two windows have closed', () => {
    const amt = baseAmt({
      valueMigration: {
        direction: 'INSUFFICIENT',
        pocDrift: 0,
        vahDrift: 0,
        valDrift: 0,
        windowLabel: '',
        hasMigration: false,
      },
    });
    const { container } = render(<ProfileOverlayInfo amt={amt} mode="session" symbol="CRUDEOIL 17 AUG 7950 CALL" />);
    expect(container.textContent).not.toContain('MIGRATION');
  });

  it('renders nothing for off mode or null AMT', () => {
    const { container } = render(<ProfileOverlayInfo amt={null} mode="session" symbol="NIFTY 18 AUG 24550 CALL" />);
    expect(container.firstChild).toBeNull();
    const { container: c2 } = render(<ProfileOverlayInfo amt={baseAmt()} mode="off" symbol="NIFTY 18 AUG 24550 CALL" />);
    expect(c2.firstChild).toBeNull();
  });
});
