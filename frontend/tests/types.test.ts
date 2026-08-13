import fs from 'fs';
import path from 'path';

describe('AMTAnalysis type pruning', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../types.ts'), 'utf8');
  const amtStart = source.indexOf('export interface AMTAnalysis');
  const nextInterface = source.indexOf('\nexport interface ', amtStart + 1);
  const amtBlock = source.slice(amtStart, nextInterface > amtStart ? nextInterface : source.length);

  const phantomMembers = [
    'direction', 'pLong', 'pShort', 'agentRegime', 'agentTiming',
    'agentKelly', 'agentRationale', 'tickSize', 'sessionId', 'computedAt',
    'amtTimeWindow', 'amtStructureLabel', 'kellyBreakdown', 'cvdDivPlaybook',
    'optionType', 'underlyingPrice', 'llmThinking',
  ];

  it('does not declare backend-never-sent members', () => {
    for (const k of phantomMembers) {
      const re = new RegExp(`^  ${k}\\??:`, 'm');
      expect(re.test(amtBlock)).toBe(false);
    }
  });
});
