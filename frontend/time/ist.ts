export const IST_OFFSET_SECONDS = 19800; // UTC+5:30, sole frontend owner
export function toISTSeconds(epochSeconds: number): number {
  return epochSeconds + IST_OFFSET_SECONDS;
}
