/**
 * Shared symbol utilities.
 * Dhan symbols look like: "NIFTY 27 FEB 25500 CALL" or "CRUDEOIL 17 MAR 5900 PUT"
 */

/** Extract a short display name and option type from a Dhan symbol. */
export function shortSymbol(sym: string): { name: string; tag: string } {
    const parts = sym.split(' ');
    if (parts.length >= 4) {
        const underlying = parts[0];
        const strike = parts[parts.length - 2];
        const optType = parts[parts.length - 1];
        const tag = optType === 'CALL' ? 'CE' : optType === 'PUT' ? 'PE' : optType;
        return { name: `${underlying} ${strike}`, tag };
    }
    return { name: sym.replace('USDT', ''), tag: '' };
}

/** Extract just the short symbol name (for tables/lists). */
export function shortSymbolName(sym: string): string {
    const { name } = shortSymbol(sym);
    return name;
}
