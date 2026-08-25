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
 * Default trading terminal hotkeys
 */
export function getDefaultTradingHotkeys(options: {
    onChartModeChange?: (mode: 'STANDARD') => void;
    onVpModeChange?: (mode: 'session' | 'leg' | 'combined' | 'off') => void;
    onToggleSidebar?: () => void;
    onToggleRightSidebar?: () => void;
    onNextSymbol?: () => void;
    onPrevSymbol?: () => void;
    onSaveWorkspace?: () => void;
    onOpenJournal?: () => void;
}): HotkeyConfig[] {
    return [
        // Chart Modes (1)
        {
            key: '1',
            description: 'Candles mode',
            handler: () => options.onChartModeChange?.('STANDARD'),
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
