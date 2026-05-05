"""
Script to automatically generate TypeScript interfaces from Pydantic DTOs.
Ensures frontend and backend types are always in sync.

USAGE:
    python scripts/generate_types.py

This generates:
    - frontend/types_generated.ts (Backend DTOs for AMTAnalysis and related types)

The generated file contains pure backend DTOs with 'DTO' suffix.
The main types.ts file contains frontend-specific extensions.
"""

import re
from pathlib import Path
from datetime import datetime
from typing import get_origin, get_args, ForwardRef, Union


def python_type_to_ts(annotation) -> str:
    """Convert Python type annotation to TypeScript."""
    # Handle None/Optional
    if annotation is type(None):
        return 'null'
    
    # Handle basic types
    type_map = {
        str: 'string',
        int: 'number',
        float: 'number',
        bool: 'boolean',
    }
    
    if annotation in type_map:
        return type_map[annotation]
    
    # Handle bare list/dict (without type args)
    if annotation is list:
        return 'unknown[]'
    if annotation is dict:
        return 'Record<string, unknown>'
    
    # Handle typing constructs
    origin = get_origin(annotation)
    
    if origin is list:
        args = get_args(annotation)
        inner = python_type_to_ts(args[0]) if args else 'unknown'
        return f'{inner}[]'
    
    if origin is dict:
        args = get_args(annotation)
        key = python_type_to_ts(args[0]) if args else 'string'
        value = python_type_to_ts(args[1]) if len(args) > 1 else 'unknown'
        return f'Record<{key}, {value}>'
    
    # Handle Union (including Optional)
    if origin is Union:
        args = get_args(annotation)
        # Filter out None type for optional handling
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return python_type_to_ts(non_none[0])
        return ' | '.join(python_type_to_ts(a) for a in non_none if a is not type(None))
    
    # Forward references - extract string name
    if isinstance(annotation, ForwardRef):
        type_name = annotation.__forward_arg__
        return type_name
    
    # Class types - extract just the class name (remove module prefix)
    type_str = str(annotation)
    if '.' in type_str:
        # Extract just the class name
        type_name = type_str.rsplit('.', 1)[-1].replace("'>", '').replace("'", '')
        # Handle special types
        if type_name == 'Any':
            return 'unknown'
        if type_name in ('tuple', 'Tuple'):
            return 'unknown[]'
        if type_name in ('dict', 'Dict'):
            return 'Record<string, unknown>'
        return type_name
    # Handle bare tuple, dict, list, etc.
    if type_str in ('tuple', 'Tuple'):
        return 'unknown[]'
    if type_str in ('dict', 'Dict'):
        return 'Record<string, unknown>'
    return type_str


def to_camel(snake: str) -> str:
    """Convert snake_case to camelCase."""
    parts = snake.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])


def generate_from_schemas():
    """Generate TypeScript types from Pydantic DTOs in schemas.py."""
    root = Path(__file__).resolve().parent.parent
    output_file = root / "frontend" / "types_generated.ts"
    
    # Import the DTOs
    from app.infrastructure.serialization.schemas import (
        AMTAnalysisDTO, VolumeProfileLevelDTO, AggressivePrintDTO,
        OIWallDTO, SqueezeStateDTO, TradeSignalDTO
    )
    
    # Build output
    output = [
        "// Auto-generated from Python Pydantic DTOs",
        f"// Generated: {datetime.now().isoformat()}",
        "// Source: backend/app/infrastructure/serialization/schemas.py",
        "// DO NOT EDIT MANUALLY - regenerate via: python scripts/generate_types.py",
        "",
        "/**",
        " * Shared types generated from Python Pydantic DTOs.",
        " * Import these for data that comes directly from the backend.",
        " */",
        "",
        "export interface VolumeProfileLevel {",
        "  price: number;",
        "  volume?: number;",
        "  buyVolume?: number;",
        "  sellVolume?: number;",
        "}",
        "",
        "export interface AggressivePrint {",
        "  price: number;",
        "  time: string;",
        "  volume: number;",
        "  delta: number;",
        "  side: 'BUY' | 'SELL';",
        "}",
        "",
        "export interface OIWall {",
        "  price: number;",
        "  callOi?: number;",
        "  putOi?: number;",
        "  totalOi?: number;",
        "  optionType?: string;",
        "}",
        "",
        "export interface SqueezeState {",
        "  isSqueezeOn?: boolean;",
        "  squeezeDirection?: string;",
        "  bollingerBandWidth?: number;",
        "  keltnerBandWidth?: number;",
        "  breakoutProbability?: number;",
        "}",
        "",
        "export interface TradeSignal {",
        "  type: 'BUY' | 'SELL';",
        "  price: number;",
        "  reason: string;",
        "  stopLoss?: number;",
        "  takeProfit?: number;",
        "  timestamp?: string;",
        "  setup?: string;",
        "  source?: string;",
        "  metadata?: Record<string, unknown>;",
        "}",
        "",
        "/**",
        " * Backend DTO for AMT analysis.",
        " * This represents the pure backend data structure.",
        " * For frontend-specific extensions, use AMTAnalysis from types.ts.",
        " */",
        "export interface AMTAnalysisDTO {",
    ]
    
    # Get the DTO fields and generate the interface
    for field_name, field_info in AMTAnalysisDTO.model_fields.items():
        alias = field_info.alias if field_info.alias else to_camel(field_name)
        ts_type = python_type_to_ts(field_info.annotation)
        
        # Replace DTO suffixes with interface names (for nested types)
        ts_type = ts_type.replace('TradeSignalDTO', 'TradeSignal')
        ts_type = ts_type.replace('VolumeProfileLevelDTO[]', 'VolumeProfileLevel[]')
        ts_type = ts_type.replace('AggressivePrintDTO[]', 'AggressivePrint[]')
        ts_type = ts_type.replace('OIWallDTO[]', 'OIWall[]')
        ts_type = ts_type.replace('SqueezeStateDTO', 'SqueezeState')
        ts_type = ts_type.replace('Record<str, Any>', 'Record<string, unknown>')
        
        is_required = field_info.is_required()
        optional_marker = '' if is_required else '?'
        
        output.append(f"  {alias}{optional_marker}: {ts_type};")
    
    output.append("}");
    
    # Write output
    output_file.write_text('\n'.join(output))
    print(f"Generated TypeScript types to {output_file}")


def generate_types():
    """Main entry point for type generation."""
    try:
        generate_from_schemas()
    except ImportError as e:
        print(f"Import Error: {e}")
        print("Ensure you run this from the project root with proper PYTHONPATH")
        raise


if __name__ == "__main__":
    generate_types()
