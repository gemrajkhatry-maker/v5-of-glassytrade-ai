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
    expect(screen.getByText(/POC 50000\.0/)).toBeInTheDocument();
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
    expect(screen.getByText(/DPOC 50100\.0/)).toBeInTheDocument();
  });

  it('displays HPOC when available', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/HPOC 50025\.0/)).toBeInTheDocument();
  });

  it('displays daily VAH when available', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/DVAH 50600\.0/)).toBeInTheDocument();
  });

  it('displays daily VAL when available', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/DVAL 49400\.0/)).toBeInTheDocument();
  });

  it('displays LEG POC when available', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/LEG POC 50050\.0/)).toBeInTheDocument();
  });

  it('displays LEG VAH when available', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/LEG VAH 50550\.0/)).toBeInTheDocument();
  });

  it('displays LEG VAL when available', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/LEG VAL 49450\.0/)).toBeInTheDocument();
  });

  it('displays current LTP marker', () => {
    render(<LocationTab {...defaultProps} />);
    expect(screen.getByText(/LTP 50000/)).toBeInTheDocument();
  });

  it('shows overflow ABOVE when LTP > VAH', () => {
    render(<LocationTab {...defaultProps} currentLtp={51000} />);
    expect(screen.getByText(/ABOVE VA/)).toBeInTheDocument();
  });

  it('shows overflow BELOW when LTP < VAL', () => {
    render(<LocationTab {...defaultProps} currentLtp={49000} />);
    expect(screen.getByText(/BELOW VA/)).toBeInTheDocument();
  });

  it('does not show overflow when LTP within VA', () => {
    render(<LocationTab {...defaultProps} currentLtp={50000} />);
    expect(screen.queryByText(/ABOVE VA/)).not.toBeInTheDocument();
    expect(screen.queryByText(/BELOW VA/)).not.toBeInTheDocument();
  });

  it('displays distance from VAH when above value area', () => {
    render(<LocationTab {...defaultProps} currentLtp={51000} />);
    expect(screen.getByText(/\+1000\.0/)).toBeInTheDocument();
  });

  it('displays distance from VAL when below value area', () => {
    render(<LocationTab {...defaultProps} currentLtp={49000} />);
    expect(screen.getByText(/-500\.0/)).toBeInTheDocument();
  });

  it('renders Target icon', () => {
    const { container } = render(<LocationTab {...defaultProps} />);
    const targetIcon = container.querySelector('svg');
    expect(targetIcon).toBeInTheDocument();
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
