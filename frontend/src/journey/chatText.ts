/** Build a single citizen-facing chat line from journey message + prompt.

Root cause of duplicate bubbles: replies often set both `message` and `prompt`
to the same (or overlapping) citizen text. Joining them without dedupe showed
the same sentence twice in the conversation UI.
*/

const COMMANDISH_PROMPT =
  /\b(Reply|reply)\b.*(CONFIRM|CORRECT|PAY|FAIL|TIMEOUT|INCOME_CERTIFICATE|RETRY)\b/i;

function normalizeCitizenText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/**
 * Return one chat string. Prefer message; drop prompt when redundant.
 */
export function citizenVisibleText(message: string, prompt?: string | null): string {
  const msg = (message || "").trim();
  const pr = (prompt || "").trim();
  if (!msg) return pr;
  if (!pr) return msg;

  const msgNorm = normalizeCitizenText(msg);
  const prNorm = normalizeCitizenText(pr);

  if (msgNorm === prNorm) return msg;
  if (COMMANDISH_PROMPT.test(pr)) return msg;
  // Prompt fully contained in message (common fee/payment templates)
  if (msgNorm.includes(prNorm)) return msg;
  // Message fully contained in prompt
  if (prNorm.includes(msgNorm)) return pr;

  return `${msg}\n${pr}`;
}
