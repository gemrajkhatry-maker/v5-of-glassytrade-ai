
import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, Loader2, User, Bot, AlertTriangle, Minus } from 'lucide-react';
import GlassPanel from './GlassPanel';
import { ChatMessage, MessageRole } from '../types';

interface AIControlsProps {
  onSendMessage: (text: string) => Promise<void>;
  isProcessing: boolean;
  history: ChatMessage[];
  hasApiKey: boolean;
  onSetApiKey: () => void;
  onClose: () => void;
}

const AIControls: React.FC<AIControlsProps> = ({ 
  onSendMessage, 
  isProcessing, 
  history, 
  hasApiKey,
  onSetApiKey,
  onClose
}) => {
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isProcessing) return;
    
    const msg = input;
    setInput('');
    await onSendMessage(msg);
  };

  return (
    <GlassPanel className="flex flex-col h-[500px] w-full max-w-md pointer-events-auto">
      {/* Header */}
      <div className="p-4 border-b border-white/10 flex items-center justify-between bg-white/5">
        <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-400" />
            <h2 className="font-semibold text-lg tracking-tight">AI Commander</h2>
        </div>
        <button 
            onClick={onClose}
            className="p-1 rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors"
            title="Minimize"
        >
            <Minus size={20} />
        </button>
      </div>

      {/* API Key Warning Overlay (Modified logic: OpenRouter key is hardcoded in service for this demo, but keeping prop logic in case App passes false) */}
      {/* We assume hasApiKey is true if using the internal hardcoded key, or App handles it. */}
      {/* For now, we render the warning if the parent says we don't have one, but we updated the service to use a constant. */}
      {/* If the App checks process.env.API_KEY, this might show up. Let's assume the user's prompt implies we use the key they gave us. */}
      
      {!hasApiKey && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-slate-900/90 backdrop-blur-sm p-6 text-center">
            <AlertTriangle className="w-12 h-12 text-yellow-500 mb-4" />
            <h3 className="text-xl font-bold mb-2">API Key Required</h3>
            <p className="text-sm text-gray-300 mb-6">
               Please ensure the API configuration is correct.
            </p>
        </div>
      )}

      {/* Chat History */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
      >
        {history.length === 0 && (
          <div className="text-center text-white/40 mt-10">
            <p className="text-sm">Try saying:</p>
            <ul className="mt-2 space-y-2 text-xs">
              <li>"Show me a bullish setup for BTC"</li>
              <li>"Make it look like red neon glass"</li>
              <li>"Simulate high volatility"</li>
            </ul>
          </div>
        )}

        {history.map((msg) => (
          <div 
            key={msg.id} 
            className={`flex gap-3 ${msg.role === MessageRole.USER ? 'flex-row-reverse' : ''}`}
          >
            <div className={`
              w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0
              ${msg.role === MessageRole.USER ? 'bg-blue-500/20 text-blue-300' : 'bg-purple-500/20 text-purple-300'}
            `}>
              {msg.role === MessageRole.USER ? <User size={14} /> : <Bot size={14} />}
            </div>
            
            <div className={`
              p-3 rounded-2xl max-w-[80%] text-sm
              ${msg.role === MessageRole.USER 
                ? 'bg-blue-600/30 text-white rounded-tr-none' 
                : 'bg-white/10 text-gray-100 rounded-tl-none'}
            `}>
              {msg.text}
            </div>
          </div>
        ))}
        
        {isProcessing && (
           <div className="flex gap-3">
             <div className="w-8 h-8 rounded-full bg-purple-500/20 text-purple-300 flex items-center justify-center">
                <Bot size={14} />
             </div>
             <div className="bg-white/10 p-3 rounded-2xl rounded-tl-none flex items-center">
                <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
             </div>
           </div>
        )}
      </div>

      {/* Input Area */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-white/10 bg-white/5">
        <div className="relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Grok to analyze or change config..."
            disabled={isProcessing}
            className="w-full bg-black/20 border border-white/10 rounded-xl py-3 px-4 pr-12 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/50 transition-all"
          />
          <button
            type="submit"
            disabled={isProcessing || !input.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-white/50 hover:text-white hover:bg-white/10 disabled:opacity-30 transition-colors"
          >
            <Send size={16} />
          </button>
        </div>
      </form>
    </GlassPanel>
  );
};

export default AIControls;
