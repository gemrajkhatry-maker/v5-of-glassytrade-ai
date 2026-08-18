import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ThreeAIndicator } from '../../components/ai/ThreeAIndicator';
import { AMTAnalysis } from '../../types';

const baseAmt = (overrides: Partial<AMTAnalysis> = {}): AMTAnalysis => ({
  marketState: 'BALANCED',
  poc: 100,
  valueAreaHigh: 105,
  valueAreaLow: 95,
  lvns: [99],
  hvns: [],
  aggression: 1.0,
  setup: null,
  profile: [],
  aggressivePrints: [],
  legProfile: [],
  legLvns: [],
  legPoc: 0,
  legVah: 0,
  legVal: 0,
  hasDisplacement: false,
  ...overrides,
});

describe('ThreeAIndicator', () => {
  it('renders three lights reflecting the 3A score', () => {
    const { container } = render(<ThreeAIndicator amt={baseAmt()} />);
    // 3 dots + a score chip
    const dots = container.querySelectorAll('[data-3a-light]');
    expect(dots.length).toBe(3);
    expect(container.querySelector('[data-3a-score]')?.textContent).toContain('2');
  });

  it('shows ENTER for a full 3A pass', () => {
    render(<ThreeAIndicator amt={baseAmt({ aggression: 2.5 })} />);
    expect(screen.getByText(/ENTER/i)).toBeTruthy();
  });

  it('shows SKIP for a dead market with no evidence', () => {
    render(<ThreeAIndicator amt={baseAmt({ marketState: 'DEAD', poc: 0, lvns: [], aggression: 0 })} />);
    expect(screen.getByText(/SKIP/i)).toBeTruthy();
  });

  it('renders a placeholder for null AMT', () => {
    const { container } = render(<ThreeAIndicator amt={null} />);
    expect(container.querySelectorAll('[data-3a-light]').length).toBe(3);
    expect(screen.getByText(/SKIP/i)).toBeTruthy();
  });
});
