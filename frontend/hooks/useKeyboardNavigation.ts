import { useEffect, useRef } from 'react';

export interface HotkeyConfig {
    /** Key combination (e.g., '1', 'Ctrl+S', 'Alt+Tab') */
    key: string;
    
    /** Description for documentation */
    description: string;
    
    /** Handler function */
    handler: () => void;
    
    /** Prevent default browser behavior (default: true) */
    preventDefault?: boolean;
    
    /** Only trigger when not in input/textarea (default: true) */
    ignoreInputs?: boolean;
}

/**
 * Professional keyboard navigation hook for trading terminal.
 * Implements hotkey system with conflict prevention and documentation.
 */
export function useKeyboardNavigation(hotkeys: HotkeyConfig[]) {
    const hotkeysRef = useRef(hotkeys);
    
    // Always use latest hotkeys
    useEffect(() => {
        hotkeysRef.current = hotkeys;
    }, [hotkeys]);
    
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Build key combination string
            const modifiers: string[] = [];
            if (e.ctrlKey || e.metaKey) modifiers.push('Ctrl');
            if (e.altKey) modifiers.push('Alt');
            if (e.shiftKey) modifiers.push('Shift');
            
            // Get base key
            let baseKey = e.key;
            if (baseKey === ' ') baseKey = 'Space';
            if (baseKey === 'Escape') baseKey = 'Esc';
            if (baseKey === 'ArrowUp') baseKey = 'ArrowUp';
            if (baseKey === 'ArrowDown') baseKey = 'ArrowDown';
            if (baseKey === 'ArrowLeft') baseKey = 'ArrowLeft';
            if (baseKey === 'ArrowRight') baseKey = 'ArrowRight';
            
            // Ignore modifier-only presses
            if (['Control', 'Alt', 'Shift', 'Meta'].includes(baseKey)) return;
            
            const keyCombo = modifiers.length > 0 
                ? `${modifiers.join('+')}+${baseKey}` 
                : baseKey;
            
            // Find matching hotkey
            const matchingHotkey = hotkeysRef.current.find(h => {
                // Check if key matches
                if (h.key !== keyCombo) return false;
                
                // Check input ignoring
                if (h.ignoreInputs !== false) {
                    const target = e.target as HTMLElement;
                    if (target.tagName === 'INPUT' || 
                        target.tagName === 'TEXTAREA' || 
                        target.contentEditable === 'true') {
                        return false;
                    }
                }
                
                return true;
            });
            
            if (matchingHotkey) {
                // Prevent default if configured
                if (matchingHotkey.preventDefault !== false) {
                    e.preventDefault();
                }
                
                // Execute handler
                matchingHotkey.handler();
            }
        };
        
        window.addEventListener('keydown', handleKeyDown);
        
        return () => {
            window.removeEventListener('keydown', handleKeyDown);
        };
    }, []);
}

/**
 * Generate hotkey hints for UI display
 */
export function getHotkeyHints(hotkeys: HotkeyConfig[]): Record<string, string> {
    const hints: Record<string, string> = {};
    hotkeys.forEach(h => {
        hints[h.key] = h.description;
    });
    return hints;
}

/**
 * Default trading terminal hotkeys
 */
export function getDefaultTradingHotkeys(options: {
    onChartModeChange?: (mode: 'STANDARD' | 'FOOTPRINT' | 'RANGE') => void;
    onVpModeChange?: (mode: 'session' | 'leg' | 'combined' | 'off') => void;
    onToggleSidebar?: () => void;
    onToggleRightSidebar?: () => void;
    onToggleControls?: () => void;
    onNextSymbol?: () => void;
    onPrevSymbol?: () => void;
    onSaveWorkspace?: () => void;
    onOpenJournal?: () => void;
    onClosePanels?: () => void;
}): HotkeyConfig[] {
    return [
        // Chart Modes (1-3)
        {
            key: '1',
            description: 'Candles mode',
            handler: () => options.onChartModeChange?.('STANDARD'),
        },
        {
            key: '2',
            description: 'Footprint mode',
            handler: () => options.onChartModeChange?.('FOOTPRINT'),
        },
        {
            key: '3',
            description: 'Range bars mode',
            handler: () => options.onChartModeChange?.('RANGE'),
        },
        
        // Volume Profile Overlays (4-7)
        {
            key: '4',
            description: 'Session profile',
            handler: () => options.onVpModeChange?.('session'),
        },
        {
            key: '5',
            description: 'Leg profile',
            handler: () => options.onVpModeChange?.('leg'),
        },
        {
            key: '6',
            description: 'Combined profile',
            handler: () => options.onVpModeChange?.('combined'),
        },
        {
            key: '7',
            description: 'Profile off',
            handler: () => options.onVpModeChange?.('off'),
        },
        
        // Navigation
        {
            key: 'Space',
            description: 'Toggle sidebar',
            handler: () => options.onToggleSidebar?.(),
        },
        {
            key: 'Tab',
            description: 'Next symbol',
            handler: () => options.onNextSymbol?.(),
        },
        {
            key: 'Shift+Tab',
            description: 'Previous symbol',
            handler: () => options.onPrevSymbol?.(),
        },
        
        // Panels
        {
            key: 'Alt+S',
            description: 'Toggle right panel',
            handler: () => options.onToggleRightSidebar?.(),
        },
        {
            key: 'Alt+C',
            description: 'Toggle controls',
            handler: () => options.onToggleControls?.(),
        },
        {
            key: 'Esc',
            description: 'Close panels',
            handler: () => options.onClosePanels?.(),
        },
        
        // Workspace
        {
            key: 'Ctrl+S',
            description: 'Save workspace',
            handler: () => options.onSaveWorkspace?.(),
        },
        {
            key: 'Ctrl+J',
            description: 'Open journal',
            handler: () => options.onOpenJournal?.(),
        },
    ];
}
