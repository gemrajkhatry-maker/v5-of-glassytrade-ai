import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import React from 'react';
import { useServerTradingSystem } from '../../hooks/useServerTradingSystem';
import { AIAnalysisPanel } from '../../components/AIAnalysisPanel';
import type { AuctionAnalysis, ChartConfig } from '../../types';

// Mock WebSocket class (reused from tests/hooks/useServerTradingSystem.test.tsx)
class MockWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    readyState = MockWebSocket.OPEN;
    onopen: (() => void) | null = null;
    onclose: ((event: { code: number }) => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onerror: ((error: Event) => void) | null = null;

    constructor(public url: string) {}

    send(data: string) {}
    close(code = 1000) {
        this.readyState = MockWebSocket.CLOSED;
        this.onclose?.({ code });
    }
}

const CONFIG: ChartConfig = {
    symbol: 'SYM',
    bullColor: '#22c55e',
    bearColor: '#ef4444',
    showVolumeProfile: false,
    vpMode: 'session',
};

/**
 * Mirrors the shape produced by the backend's auction_state_to_dto
 * (backend/app/application/services/quant_bridge.py) → frontend AuctionAnalysis.
 */
const auctionFixture = (overrides: Partial<AuctionAnalysis> = {}): AuctionAnalysis => ({
    time: '2026-08-06T09:15:00Z',
    close: 25123.5,
    volumeProfile: { poc: 25100, vah: 25250, val: 25000, step: 5, totalVolume: 12345.5 },
    vwap: {
        value: 25120,
        upper1: 25180,
        lower1: 25060,
        upper2: 25240,
        lower2: 25000,
        std: 40,
        deviationSigmas: 0.8,
    },
    orderFlow: { delta: 1234.5, cvd: 5678.25, cvdSlope: 0.0123, cvdDivergence: 'bullish' },
    absorption: { side: 'BUY', price: 25100, volume: 4500.5, strength: 0.72, barAge: 2 },
    location: {
        ibHigh: 25200,
        ibLow: 25000,
        ibComplete: true,
        zone: 'near_ib_high',
        nearestLevel: 25200,
        distanceToLevel: 23.5,
    },
    tripleAPhase: 'AGGRESSION',
    tripleASignal: 'LONG',
    ...overrides,
});

// Mirrors App.tsx wiring: hook → AIAnalysisPanel + a probe exposing the
// auction triple-A state (the ModelStateBanner that rendered it was removed
// with the LLM layer; the auction data itself still flows through the hook).
const Harness = () => {
    const { activeInstrument } = useServerTradingSystem(CONFIG);
    if (!activeInstrument) return <div>connecting…</div>;
    return (
        <div>
            <AIAnalysisPanel
                amtResult={activeInstrument.amtAnalysis}
                portfolio={activeInstrument.portfolio}
                riskState={activeInstrument.riskState}
                agentDecision={activeInstrument.agentDecision}
                orderBook={activeInstrument.orderBook}
                quantDecision={activeInstrument.quantDecisionAnalysis}
                symbol={activeInstrument.symbol}
                data={activeInstrument.data}
            />
            <span data-testid="tripleA-phase">{activeInstrument.auctionAnalysis?.tripleAPhase || ''}</span>
            <span data-testid="tripleA-signal">{activeInstrument.auctionAnalysis?.tripleASignal || ''}</span>
        </div>
    );
};

describe('auction WS → analysis pipeline', () => {
    const connect = async () => {
        const instances: MockWebSocket[] = [];
        class TrackingWS extends MockWebSocket {
            constructor(url: string) {
                super(url);
                instances.push(this);
            }
        }
        const realFetch = global.fetch;
        global.fetch = vi.fn(async () => ({
            ok: true,
            json: async () => ({ activeSymbols: ['SYM'] }),
        })) as any;
        global.WebSocket = TrackingWS as any;

        const rendered = render(<Harness />);

        // Let the config fetch resolve and the WS connect effect run.
        for (let i = 0; i < 3; i++) {
            await act(async () => {
                await new Promise(r => setTimeout(r, 20));
            });
        }

        global.fetch = realFetch;
        return { ...rendered, ws: instances[0] };
    };

    const pushMessage = async (ws: MockWebSocket, msg: Record<string, unknown>) => {
        await act(async () => {
            ws.onmessage?.({ data: JSON.stringify(msg) } as any);
            // Flush the RAF-batched state update inside act.
            await new Promise(r => setTimeout(r, 30));
        });
    };

    it('merges the auction through a full message and renders market state', async () => {
        const { ws } = await connect();
        expect(ws).toBeDefined();

        await pushMessage(ws, {
            _type: 'full',
            _symbol: 'SYM',
            auction: auctionFixture({
                tripleASignal: null,
                tripleAPhase: 'ABSORBING',
            }),
            amt: {
                marketState: 'IMBALANCED',
                setup: 'MEAN_REVERSION',
                poc: 100,
                valueAreaHigh: 102,
                valueAreaLow: 98,
                lvns: [],
                hvns: [],
                aggression: 0.5,
                profile: [],
                aggressivePrints: [],
                legProfile: [],
                legLvns: [],
                legPoc: 0,
                legVah: 0,
                legVal: 0,
                hasDisplacement: false,
            },
        });

        // Auction data flows through the hook.
        expect(screen.getByTestId('tripleA-phase').textContent).toBe('ABSORBING');
        // Market state renders through AIAnalysisPanel's MarketStateCard (may
        // appear in more than one card, e.g. the order-flow summary too).
        expect(screen.getAllByText(/IMBALANCED/i).length).toBeGreaterThan(0);
    });

    it('keeps the TRIPLE-A LONG signal from a full WS message carrying auction', async () => {
        const { ws } = await connect();
        expect(ws).toBeDefined();

        await pushMessage(ws, {
            _type: 'full',
            _symbol: 'SYM',
            auction: auctionFixture(),
        });

        expect(screen.getByTestId('tripleA-signal').textContent).toBe('LONG');
    });

    it('merges auction through the delta path and updates the signal', async () => {
        const { ws } = await connect();
        expect(ws).toBeDefined();

        await pushMessage(ws, {
            _type: 'full',
            _symbol: 'SYM',
            auction: auctionFixture(),
        });
        expect(screen.getByTestId('tripleA-signal').textContent).toBe('LONG');

        // Delta: only auction changed → auctionAnalysis merged (LONG→SHORT, absorption cleared).
        await pushMessage(ws, {
            _type: 'delta',
            _symbol: 'SYM',
            auction: auctionFixture({
                tripleASignal: 'SHORT',
                tripleAPhase: 'ACCUMULATING',
                absorption: null,
            }),
        });

        expect(screen.getByTestId('tripleA-signal').textContent).toBe('SHORT');
        expect(screen.getByTestId('tripleA-phase').textContent).toBe('ACCUMULATING');
    });

    it('renders an approved quant decision from a full WS message carrying quantDecision', async () => {
        const { ws } = await connect();
        expect(ws).toBeDefined();

        await pushMessage(ws, {
            _type: 'full',
            _symbol: 'SYM',
            auction: auctionFixture(),
            quantDecision: {
                approved: true,
                reason: 'Triple-A',
                phase: 'AGGRESSION',
                signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, confidence: 1.0 },
            },
        });

        expect(screen.getByText(/LONG @ 104\.00/i)).toBeInTheDocument();
        expect(screen.getByText(/RR 2\.0/i)).toBeInTheDocument();
    });

    it('clears the decision card when quantDecision is not approved', async () => {
        const { ws } = await connect();
        expect(ws).toBeDefined();

        await pushMessage(ws, {
            _type: 'full',
            _symbol: 'SYM',
            auction: auctionFixture(),
            quantDecision: { approved: true, reason: 'Triple-A', phase: 'AGGRESSION',
                signal: { type: 'LONG', entry: 104.0, sl: 99.54, tp: 112.92, rr: 2.0, confidence: 1.0 } },
        });
        expect(screen.getByText(/LONG @ 104\.00/i)).toBeInTheDocument();

        await pushMessage(ws, {
            _type: 'delta',
            _symbol: 'SYM',
            quantDecision: { approved: false, reason: 'NO_EDGE', phase: 'WAITING', signal: null },
        });
        expect(screen.queryByText(/LONG @ 104\.00/i)).not.toBeInTheDocument();
    });
});
