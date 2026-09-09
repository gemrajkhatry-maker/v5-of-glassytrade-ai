import React from 'react';

interface GlassPanelProps {
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
  variant?: 'default' | 'elevated' | 'active';
}

/**
 * GlassPanel — Institutional redesign
 * 
 * BEFORE: Glassmorphism (bg-white/8, backdrop-blur-xl, rounded-2xl)
 * AFTER: Solid backgrounds with professional borders
 * 
 * Usage:
 * - default: Standard panels (scanner, sidebar)
 * - elevated: Floating elements, modals
 * - active: Selected/active state panels
 */
const GlassPanel: React.FC<GlassPanelProps> = ({ 
  children, 
  className = '',
  contentClassName = '',
  variant = 'default' 
}) => {
  
  const variantClasses = {
    default: 'bg-glassy-bg-secondary border-glassy-border-default',
    elevated: 'bg-glassy-bg-tertiary border-glassy-border-prominent shadow-lg',
    active: 'bg-glassy-bg-active border-glassy-border-focus',
  };

  return (
    <div className={`
      relative overflow-hidden
      ${variantClasses[variant]}
      border
      shadow-[0_4px_16px_rgba(0,0,0,0.4)]
      rounded-md
      text-glassy-text-primary
      transition-transform duration-300
      ${className}
    `}>
      {/* Content */}
      <div className={`relative z-10 ${contentClassName}`}>
        {children}
      </div>
    </div>
  );
};

export default GlassPanel;
