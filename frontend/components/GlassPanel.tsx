import React from 'react';

interface GlassPanelProps {
  children: React.ReactNode;
  className?: string;
}

const GlassPanel: React.FC<GlassPanelProps> = ({ children, className = '' }) => {
  return (
    <div className={`
      relative overflow-hidden
      bg-white/5 
      backdrop-blur-xl 
      border border-white/10 
      shadow-[0_8px_32px_0_rgba(0,0,0,0.37)] 
      rounded-2xl 
      text-white
      transition-all duration-300
      ${className}
    `}>
      {/* Glossy gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-br from-white/10 to-transparent pointer-events-none" />
      
      {/* Content */}
      <div className="relative z-10">
        {children}
      </div>
    </div>
  );
};

export default GlassPanel;
