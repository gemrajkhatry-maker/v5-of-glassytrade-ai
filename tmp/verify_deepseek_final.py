
import asyncio
import os
import sys
import json
from pathlib import Path

# Setup path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.append(str(backend_path))

from dotenv import load_dotenv
load_dotenv()

from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
from app.config import settings

async def main():
    print(f"Current Model: {settings.REASONING_MODEL_ID}")
    
    adapter = MLXInferenceAdapter()
    
    # Test prompt
    instruction = "You are a trading assistant. Respond in JSON."
    input_text = "{\"market\": \"MCX\", \"action\": \"analyze\"}"
    
    print("\n--- Starting Inference Test ---")
    try:
        # Note: MLXInferenceAdapter.predict is NOT async based on recent inspection
        # But wait, I saw 'async def predict' in the file earlier. 
        # Line 175 was 'def predict('. Let me double check if I missed 'async'.
        
        response = adapter.predict(instruction=instruction, input_text=input_text)
        if asyncio.iscoroutine(response):
             response = await response
             
        print("\nFull Response:")
        print(response)
        
        # Check if valid JSON
        if "{" in response:
            try:
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                json_data = json.loads(response[json_start:json_end])
                print("\n✅ Success: Valid JSON extracted.")
            except json.JSONDecodeError:
                print("\n❌ Error: Found brackets but failed to parse JSON.")
        else:
            print("\n❌ Error: No JSON found in response.")
            
    except Exception as e:
        print(f"\n❌ Error during inference: {e}")

if __name__ == "__main__":
    asyncio.run(main())
