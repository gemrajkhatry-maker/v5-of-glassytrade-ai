import { describe, expect, it } from 'vitest';
import { IST_OFFSET_SECONDS, toISTSeconds } from '../../time/ist';
describe('ist', () => {
  it('offset is 19800', () => { expect(IST_OFFSET_SECONDS).toBe(19800); });
  it('shifts epoch', () => { expect(toISTSeconds(0)).toBe(19800); });
});
