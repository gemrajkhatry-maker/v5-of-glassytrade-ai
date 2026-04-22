#!/bin/bash
# Start backend in MCX mode

cd /Users/apple/Downloads/v5-of-glassytrade-ai/backend

# Activate virtual environment
source venv/bin/activate

# Set MCX mode environment variables
export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options

echo "Starting backend in MCX mode..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 9090 --log-level info
