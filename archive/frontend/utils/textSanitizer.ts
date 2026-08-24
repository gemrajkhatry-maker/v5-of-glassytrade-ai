/**
 * Text sanitization utility for LLM output display.
 * 
 * LLMs often return escape sequences that need to be cleaned
 * before displaying in the UI:
 * - \[ and \] → [ and ]
 * - \- → -
 * - \n → newline
 * - \" → "
 * - JSON wrapping artifacts → removed
 */

/**
 * Try to extract a value from potentially malformed JSON using regex.
 * Looks for common keys like quant_reason, rationale, reason, direction, etc.
 */
function extractFromMalformedJson(text: string): string | null {
  // List of keys to try extracting, in priority order
  const keys = [
    'quant_reason',
    'rationale',
    'reason',
    'direction',
    'analysis',
    'verdict',
    'decision',
    'signal',
    'message'
  ];
  
  for (const key of keys) {
    // Match patterns like "key":"value" or "key": "value"
    // Handles both single and double quotes, and escaped quotes in values
    const patterns = [
      new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"`),
      new RegExp(`'${key}'\\s*:\\s*'((?:[^'\\\\]|\\\\.)*)'`),
      new RegExp(`"${key}"\\s*:\\s*([^,}\\n]+)`),
    ];
    
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match && match[1]) {
        // Clean up the extracted value
        let value = match[1]
          .replace(/\\"/g, '"')
          .replace(/\\'/g, "'")
          .replace(/\\n/g, ' ')
          .replace(/\\t/g, ' ')
          .trim();
        // Remove surrounding quotes if present
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        if (value && value !== 'null' && value !== 'undefined') {
          return value;
        }
      }
    }
  }
  
  return null;
}

/**
 * Try to parse and extract meaningful text from JSON or JSON-like content.
 * Returns null if no meaningful extraction was possible.
 */
function tryParseJsonContent(text: string): string | null {
  const trimmed = text.trim();
  
  // Only attempt JSON parsing if it looks like JSON
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) {
    return null;
  }
  
  // Try to parse as valid JSON first
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed === 'string') {
      return parsed;
    }
    if (typeof parsed === 'object' && parsed !== null) {
      // Extract in priority order
      const value = parsed.quant_reason ||
                    parsed.rationale ||
                    parsed.reason ||
                    parsed.analysis ||
                    parsed.verdict ||
                    parsed.decision ||
                    parsed.signal ||
                    parsed.message ||
                    parsed.direction;
      if (typeof value === 'string' && value.trim()) {
        return value.trim();
      }
      // If we have a direction but no text, return a readable form
      if (parsed.direction) {
        return `Signal: ${parsed.direction}`;
      }
    }
  } catch {
    // JSON parse failed - try regex extraction for malformed JSON
    const extracted = extractFromMalformedJson(trimmed);
    if (extracted) {
      return extracted;
    }
  }
  
  return null;
}

/**
 * Remove any remaining JSON-like artifacts from text.
 * Strips curly braces, brackets, and key-value patterns.
 */
function stripJsonArtifacts(text: string): string {
  return text
    // Remove standalone JSON objects that might be embedded
    .replace(/\{[^{}]*"[^"]+"\s*:\s*"[^"]*"[^{}]*\}/g, '')
    .replace(/\{[^{}]*"[^"]+"\s*:\s*[^,}]+[^{}]*\}/g, '')
    // Remove orphaned braces
    .replace(/^\s*\{\s*/, '')
    .replace(/\s*\}\s*$/, '')
    // Remove patterns like "key":"value" that might remain
    .replace(/"[a-z_]+"\s*:\s*"[^"]*"\s*,?\s*/gi, '')
    .replace(/"[a-z_]+"\s*:\s*[^,}\n]+\s*,?\s*/gi, '')
    // Clean up multiple spaces
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * Clean LLM output text for display.
 * Removes escape sequences, JSON artifacts, and formats properly.
 */
export function sanitizeLlmText(text: string | undefined | null): string {
  if (!text) return '';

  return text
    // Remove escape sequences
    .replace(/\\\[/g, '[')
    .replace(/\\\]/g, ']')
    .replace(/\\-/g, '-')
    .replace(/\\n/g, '\n')
    .replace(/\\"/g, '"')
    .replace(/\\t/g, '  ')
    // Remove JSON wrapping
    .replace(/^[{\s"']+|[}\s"']+$/g, '')
    // Remove leading/trailing whitespace
    .trim();
}

/**
 * Clean LLM rationale for display.
 * More aggressive cleaning for the rationale field.
 * Handles embedded JSON objects and extracts meaningful text.
 */
export function sanitizeRationale(rationale: string | undefined | null): string {
  if (!rationale) return '';

  // First, unescape common escape sequences
  let text = rationale
    .replace(/\\\[/g, '[')
    .replace(/\\\]/g, ']')
    .replace(/\\-/g, '-')
    .replace(/\\n/g, ' ')
    .replace(/\\"/g, '"')
    .replace(/\\t/g, ' ');

  // Try to extract from JSON content
  const jsonExtraction = tryParseJsonContent(text);
  if (jsonExtraction) {
    return jsonExtraction;
  }

  // Strip any JSON artifacts that might remain
  text = stripJsonArtifacts(text);

  // Remove repetitive phrases (LLM stuck in loop)
  // Detect 3+ consecutive repeats of the same phrase
  text = text.replace(/(\b[\w.]+(?:\s[\w.]+){0,3})\s*(?:\1\s*){2,}/gi, '$1');

  // Remove orphaned JSON fragments (partial objects)
  // Truncated JSON at end — extended range and multiline
  text = text.replace(/\{[^}]{0,200}$/gm, '');
  // Orphaned closing brace at start
  text = text.replace(/^[^{]{0,20}\}/gm, '');
  // Orphaned brackets, braces, or quotes at very end of text
  text = text.replace(/[\[{}\]"]\s*$/g, '');
  // Partial JSON objects like {"key": or {"key":"value  (no closing brace)
  text = text.replace(/\{"[^"]*"?\s*:?\s*"?[^"}]*"?\s*$/g, '');

  // Remove hallucinated ratio references (e.g., "1:553", "1:1234")
  text = text.replace(/\b\d+:\d{3,}\b/g, '');

  // Remove "First d..." style truncations
  text = text.replace(/\bFirst\s+[a-z]\.\.\./gi, '');

  // Final cleanup
  text = text.trim();
  
  // Return the cleaned text, or a fallback if empty
  return text || 'Analysis pending...';
}

/**
 * Helper function specifically for AIAnalysisPanel decision text.
 * Returns a clean human-readable text or a fallback message.
 */
export function extractDecisionText(
  rationale: string | undefined | null,
  fallback: string = 'QUANT_MONITORING'
): string {
  const sanitized = sanitizeRationale(rationale);
  
  // If we got a meaningful extraction, return it
  if (sanitized && sanitized !== 'Analysis pending...') {
    return sanitized;
  }
  
  // Return the provided fallback
  return fallback;
}
