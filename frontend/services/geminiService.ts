
// Use official Google GenAI SDK
import { GoogleGenAI, Type } from "@google/genai";
import { AICommandResponse } from "../types";

/**
 * Initialize the Google GenAI client using the environment's API key.
 * Named parameters must be used for initialization.
 */
const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });

/**
 * Processes natural language commands to control the 3D candlestick chart.
 * Uses gemini-3-pro-preview for complex reasoning and structured JSON output.
 */
export const processUserCommand = async (
  prompt: string,
  currentConfig: any
): Promise<AICommandResponse> => {
  try {
    const systemInstruction = `
      You are an expert financial visualizer and 3D graphics controller.
      Your goal is to interpret natural language commands to control a 3D candlestick chart application.
      
      Current Chart Configuration:
      ${JSON.stringify(currentConfig)}

      The user can ask to:
      1. Switch to live data for a crypto symbol (e.g., "Show me BTC", "ETH live"). 
         - Set 'dataSource' to 'BINANCE'.
         - Infer the symbol (e.g., "BTC" -> "BTCUSDT").
      2. Change the timeframe/interval (e.g., "use 15m", "daily chart", "5 minute candles").
         - Set 'interval' (valid values: '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M').
      3. Simulate market trends (e.g., "Simulate a crash", "Show me a bullish pattern").
         - Set 'dataSource' to 'SIMULATION'.
         - Set 'trend' accordingly.
      4. Change the visual theme (colors, glassiness, roughness, transmission).
      5. Control features like Predictions or Grid.
         - "Show predictions", "Hide forecast", "Turn off projected candles" -> Toggle 'showPredictions'.
      6. Control Volume Profile visibility.
         - "Hide volume profile", "remove volume bars", "show profile" -> Toggle 'showVolumeProfile'.

      Available Parameters to Update:
      - symbol: string (e.g., 'BTCUSDT', 'ETHUSDT' for Binance; anything for Simulation)
      - interval: string (Binance kline intervals)
      - dataSource: 'BINANCE' | 'SIMULATION'
      - bullColor: hex color string
      - bearColor: hex color string
      - roughness: number (0.0 to 1.0, 0 is smooth glass, 1 is matte)
      - transmission: number (0.0 to 1.0, 1 is clear glass)
      - autoRotate: boolean
      - showPredictions: boolean
      - showVolumeProfile: boolean
      - trend: 'bullish' | 'bearish' | 'sideways' | 'volatile'
    `;

    // Query Gemini model with system instructions and JSON schema enforcement
    const response = await ai.models.generateContent({
      model: 'gemini-3-pro-preview',
      contents: prompt,
      config: {
        systemInstruction,
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            message: {
              type: Type.STRING,
              description: "A short, friendly confirmation message to the user."
            },
            action: {
              type: Type.STRING,
              enum: ["UPDATE_CONFIG", "GENERATE_DATA", "RESET"]
            },
            configUpdates: {
              type: Type.OBJECT,
              properties: {
                symbol: { type: Type.STRING },
                interval: { type: Type.STRING },
                dataSource: { type: Type.STRING, enum: ["BINANCE", "SIMULATION"] },
                bullColor: { type: Type.STRING },
                bearColor: { type: Type.STRING },
                roughness: { type: Type.NUMBER },
                transmission: { type: Type.NUMBER },
                autoRotate: { type: Type.BOOLEAN },
                showPredictions: { type: Type.BOOLEAN },
                showVolumeProfile: { type: Type.BOOLEAN },
                trend: { type: Type.STRING, enum: ['bullish', 'bearish', 'sideways', 'volatile'] }
              }
            }
          },
          required: ["message", "action"]
        }
      }
    });

    // Access text property directly as per guidelines
    const text = response.text;
    if (!text) throw new Error("No response content from Gemini");

    return JSON.parse(text) as AICommandResponse;

  } catch (error) {
    console.error("Gemini API Error:", error);
    return {
      message: "Sorry, I had trouble processing that command via Gemini. Please try again.",
      action: "RESET" 
    };
  }
};
