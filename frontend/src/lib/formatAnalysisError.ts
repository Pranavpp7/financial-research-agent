/** Map raw analysis/task errors to short UI copy; log the original. */
export function formatAnalysisError(raw: string | null | undefined): string {
  const text = (raw ?? "").trim();
  if (!text) return "Analysis failed. Try again.";

  // Always keep the full payload in the browser console for debugging.
  console.error("[analysis]", text);

  const lower = text.toLowerCase();

  if (
    lower.includes("invalid_api_key") ||
    lower.includes("invalid api key") ||
    (lower.includes("401") && lower.includes("api"))
  ) {
    return "Analysis failed: invalid Groq API key. Check GROQ_API_KEY.";
  }

  if (
    lower.includes("model_decommissioned") ||
    lower.includes("decommissioned") ||
    lower.includes("model not found") ||
    lower.includes("model_not_found")
  ) {
    return "Groq model unavailable. Set GROQ_MODEL in .env.";
  }

  if (
    lower.includes("rate_limit") ||
    lower.includes("rate limit") ||
    lower.includes("429") ||
    lower.includes("too many requests")
  ) {
    return "Rate limited, try again shortly.";
  }

  return "Analysis failed. Check the browser console for details.";
}
