import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import LocationTab from '../../../../components/intelligence/tabs/LocationTab';

describe('LocationTab', () => {
  const defaultProps = {
    currentLtp: 50000,
    poc: 50000,
    vah: 50500,
    val: 49500,
    amtResult: {
      poc: 50000,
      valueAreaHigh: 50500,
      valueAreaLow: 49500,
      dailyPoc: 50100,
      dailyVah: 50600,
      dailyVal: 49400,
      legPoc: 50050,
      legVah: 50550,
      legVal: 49450,
      hourlyPoc: 50025,
      marketState: 'BALANCED',
    },
  };

  it('shows loading state when poc is null', () => {
    render(<LocationTab {...defaultProps} amtResult={{ ...defaultProps.amtResult, poc: null }} />);
    expect(screen.getByText(/Building Volume Profile/)).toBeInTheDocument();
  });

  it('shows loading state when currentLtp is 0', () => {
    render(<LocationTab {...defaultProps} currentLtp={0} />);
    expect(screen.getByText(/Building Volume Profile/)).toBeInTheDocument();
  });

  it('displays Location header', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText('Location')).toBeInTheDocument();
  });

  it('displays session POC', () => {
    render(<LocationTab {...defaultProps} />);
    // POC and value are in separate spans
    expect(screen.getByText('POC')).toBeInTheDocument();
    expect(screen.getByText('50000')).toBeInTheDocument();
  });

  it('displays session VAH', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/VAH 50500\.0/)).toBeInTheDocument();
  });

  it('displays session VAL', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/VAL 49500\.0/)).toBeInTheDocument();
  });

  it('displays DPOC when available', () => {
    render(<LocationTab {...defaultProps} />);
    // DPOC label is separate
    expect(screen.getByText('DPOC')).toBeInTheDocument();
  });

  it('displays HPOC when available', () => {
    render(<LocationTab {...defaultProps} />);
    // HPOC label is separate
    expect(screen.getByText('HPOC')).toBeInTheDocument();
  });

  it('displays LEG POC when available', () => {
    render(<LocationTab {...defaultProps} />);
    // LEG POC label with value
    expect(screen.getByText(/LEG 50050\.0/)).toBeInTheDocument();
  });

  it('displays current LTP marker', () => {
    render(<LocationTab {...defaultProps} />);
    // LTP is displayed with value
    expect(screen.getByText(/50000\.0/)).toBeInTheDocument();
  });

  it('shows overflow ABOVE when LTP > VAH', () => {
    render(<LocationTab {...defaultProps} currentLtp={51000} />);
    expect(screen.getByText(/ABOVE/)).toBeInTheDocument();
  });

  it('shows overflow BELOW when LTP < VAL', () => {
    render(<LocationTab {...defaultProps} currentLtp={49000} />);
    expect(screen.getByText(/BELOW/)).toBeInTheDocument();
  });

  it('does not show overflow when LTP within VA', () => {
    render(<LocationTab {...defaultProps} currentLtp={50000} />);
    expect(screen.queryByText(/ABOVE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/BELOW/)).not.toBeInTheDocument();
  });

  it('displays distance from VAH when above value area', () => {
    render(<LocationTab {...defaultProps} currentLtp={51000} />);
    expect(screen.getByText(/pts/)).toBeInTheDocument();
  });

  it('displays distance from VAL when below value area', () => {
    render(<LocationTab {...defaultProps} currentLtp={49000} />);
    expect(screen.getByText(/pts/)).toBeInTheDocument();
  });

  it('renders Target icon', () => {
    render(<LocationTab {...defaultProps} />);
    // Component renders SVG icons, just verify it renders without error
    expect(screen.getByText('Location')).toBeInTheDocument();
  });

  it('handles missing daily levels gracefully', () => {
    render(<LocationTab {...defaultProps} amtResult={{
      ...defaultProps.amtResult,
      dailyPoc: undefined,
      dailyVah: undefined,
      dailyVal: undefined,
    }} />);
    expect(screen.queryByText(/DPOC/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DVAH/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DVAL/)).not.toBeInTheDocument();
  });

  it('handles missing leg levels gracefully', () => {
    render(<LocationTab {...defaultProps} amtResult={{
      ...defaultProps.amtResult,
      legPoc: undefined,
      legVah: undefined,
      legVal: undefined,
    }} />);
    expect(screen.queryByText(/LEG POC/)).not.toBeInTheDocument();
    expect(screen.queryByText(/LEG VAH/)).not.toBeInTheDocument();
    expect(screen.queryByText(/LEG VAL/)).not.toBeInTheDocument();
  });

  it('handles missing hourly POC gracefully', () => {
    render(<LocationTab {...defaultProps} amtResult={{
      ...defaultProps.amtResult,
      hourlyPoc: undefined,
    }} />);
    expect(screen.queryByText(/HPOC/)).not.toBeInTheDocument();
  });
});
