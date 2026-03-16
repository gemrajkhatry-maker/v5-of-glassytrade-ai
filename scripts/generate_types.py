"""
Script to automatically generate TypeScript interfaces from Pydantic DTOs.
Ensures frontend and backend types are always in sync.
"""

import subprocess
import os
from pathlib import Path

def generate_types():
    import sys
    print(f"Python executable: {sys.executable}")
    print(f"Python path: {sys.path}")
    
    root = Path(__file__).resolve().parent.parent
    schema_file = root / "backend" / "app" / "infrastructure" / "serialization" / "schemas.py"
    output_file = root / "frontend" / "types_generated.ts"
    
    print(f"Generating TypeScript types from {schema_file}...")
    
    # Using pydantic2ts (provided by pydantic-to-typescript package)
    try:
        import traceback
        import pydantic2ts
        print(f"Module pydantic2ts found at {pydantic2ts.__file__}")
        from pydantic2ts import generate_typescript_defs
        generate_typescript_defs(
            "backend.app.infrastructure.serialization.schemas",
            str(output_file)
        )
        print(f"Successfully generated types at {output_file}")
    except ImportError as e:
        print(f"Import Error: {e}")
        print("pydantic2ts lib not found. Please run 'pip install pydantic-to-typescript'")
    except Exception as e:
        print(f"Error generating types: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    generate_types()
