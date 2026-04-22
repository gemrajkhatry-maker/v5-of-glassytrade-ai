
import re

def check_div_balance(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    depth = 0
    for i, line in enumerate(lines, 1):
        # Count strictly opening divs (not ending in />)
        opens = len(re.findall(r'<div(?![^>]*/>)[^>]*>', line))
        closes = line.count('</div>')
        
        depth += opens
        depth -= closes
        
        if '/* 0' in line:
            print(f"DEPTH at {line.strip()}: {depth}")
        
        if depth < 0:
            print(f"ERROR: Depth < 0 at line {i}: {line.strip()}")
            depth = 0 # Reset to continue
            
    print(f"Final depth: {depth}")

check_div_balance('frontend/components/AIAnalysisPanel.tsx')
