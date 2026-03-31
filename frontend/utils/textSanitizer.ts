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
 */
export function sanitizeRationale(rationale: string | undefined | null): string {
  if (!rationale) return '';

  return rationale
    .replace(/\\\[/g, '[')
    .replace(/\\\]/g, ']')
    .replace(/\\-/g, '-')
    .replace(/\\n/g, ' ')
    .replace(/\\"/g, '"')
    .replace(/\\t/g, ' ')
    .replace(/^[{\s"']+|[}\s"']+$/g, '')
    .trim();
}
