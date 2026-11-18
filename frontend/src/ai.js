// Who answered an AI request, in words. `provider` comes from the API: "anthropic", "local" or "offline".

/** Short badge text: "Claude", "Local AI" or "Offline". */
export function aiBadge(provider) {
  return provider === "anthropic" ? "Claude" : provider === "local" ? "Local AI" : "Offline";
}

/** For sentences like "planned by …": "Claude", "the local AI model (qwen2.5:3b)" or "offline rules". */
export function aiBy(provider, model) {
  if (provider === "anthropic") return model ? `Claude (${model})` : "Claude";
  if (provider === "local") return model ? `the local AI model (${model})` : "the local AI model";
  return "offline rules";
}

// "Make an offer" rules from the server (minimum price, how long a deal is held), fetched once.
const OFFER_DEFAULTS = { min_price: 500, deal_minutes: 30 };
let offerRules = null;
export function getOfferRules() {
  offerRules ||= fetch("/api/ai/status/")
    .then((r) => r.json())
    .then((s) => s.offers || OFFER_DEFAULTS)
    .catch(() => {
      offerRules = null; // don't remember a failed load: try again next time
      return OFFER_DEFAULTS;
    });
  return offerRules;
}

/** Friendly names for the AI features the local model can answer. */
export const FEATURE_NAMES = {
  rag_answer: "help center answers", product_qa: "Ask this product", offer_reply: "bargaining replies",
  review_summary: "review summaries", listing_check: "listing checks", fit_read: "fit advice", search_parse: "search", planner: "the planner",
};
export const featureList = (features = []) => features.map((f) => FEATURE_NAMES[f] || f.replaceAll("_", " ")).join(" and ");
