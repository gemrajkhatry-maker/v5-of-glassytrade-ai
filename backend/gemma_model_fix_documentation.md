# Gemma 4 26B Model Loading Fix Documentation

## Issue Description
The backend was failing to load the Gemma 4 26B model properly, resulting in the error "unknown url type: ''" when the system attempted to fall back to cloud services. The root cause was that the MLX inference adapter couldn't locate the environment variables for model and adapter paths.

## Root Cause Analysis
1. The MLX inference adapter was looking for the `.env` file 4 levels up from its location (project root)
2. However, the `.env` file was located in the `backend` directory (3 levels up from the adapter)
3. As a result, environment variables like `MLX_MODEL_PATH` and `MLX_ADAPTER_PATH` weren't being loaded
4. This caused the model path to remain empty, triggering a fallback to cloud services with empty configuration

## Solution Implemented
Modified the `_ensure_runtime_env_loaded` method in `backend/app/infrastructure/adapters/mlx_inference_adapter.py` to:

1. Check both potential locations for the `.env` file:
   - Backend directory (3 levels up from adapter): `Path(__file__).resolve().parents[3] / ".env"`
   - Project root (4 levels up from adapter): `Path(__file__).resolve().parents[4] / ".env"`

2. Prioritize the backend directory first, then fall back to project root

## Changes Made
File: `backend/app/infrastructure/adapters/mlx_inference_adapter.py`
Method: `_ensure_runtime_env_loaded` (lines 149-157)

```python
# Look for .env in backend directory (3 levels up from adapter)
backend_env_path = Path(__file__).resolve().parents[3] / ".env"
# Also look in project root (4 levels up from adapter)
root_env_path = Path(__file__).resolve().parents[4] / ".env"

# Check backend directory first, then project root
if backend_env_path.exists():
    env_path = backend_env_path
elif root_env_path.exists():
    env_path = root_env_path
else:
    # Fallback to project root
    env_path = root_env_path
```

## Verification
- The Gemma 4 26B model (mlx-community/gemma-4-26b-a4b-it-4bit) loads successfully
- The adapter (../gemma4_26b_clean_adapter) is properly applied
- Local model inference is working without falling back to cloud services
- The "unknown url type: ''" error is resolved
- Backend operates in NSE mode with proper AI decision making

## Impact
- Improved reliability: No more failed cloud fallback attempts
- Better performance: Direct local model inference instead of API calls
- Cost reduction: Eliminated cloud API usage for model inference
- Enhanced stability: Proper environment variable loading prevents configuration issues

## Files Affected
- `backend/app/infrastructure/adapters/mlx_inference_adapter.py` - Fixed environment variable loading
- `backend/.env` - Contains the model and adapter path configurations
- `backend/scripts/start_nse.sh` - Sets environment variables for NSE mode

## Configuration Used
- Model: `mlx-community/gemma-4-26b-a4b-it-4bit`
- Adapter: `../gemma4_26b_clean_adapter` (Iteration 1950 - verified stable weights)
- Backend runs in NSE mode for options trading