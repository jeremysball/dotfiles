/**
 * Meta parity: ensures every fleet-tier model is listed.
 * Pi's built-in meta catalog hides contributor models despite
 * settings.json modelOverrides; this extension registers them
 * explicitly so pi --list-models matches the opencode/kilo fleet.
 * muse-spark-1.3 reached the fleet 2026-10-07 via models.dev's meta
 * catalog merge on opencode/kilo (which add to the built-in provider
 * instead of replacing it); pi replaces it here, so the model must be
 * explicit. Keep in sync with opencode.jsonc provider.meta and
 * verify-provider-parity.sh.
 */
export default function (pi) {
  // Register meta with full fleet: pi's built-in catalog plus both
  // contributor models. Using registerProvider here REPLACES the built-in
  // provider definition, so include all 4 models explicitly.
  try {
    pi.registerProvider("meta", {
      name: "Meta",
      baseUrl: "https://api.meta.ai/v1",
      apiKey: "$META_MODEL_API_KEY",
      api: "openai-completions",
      models: [
        {
          id: "muse-spark-1.1",
          name: "Muse Spark 1.1",
          reasoning: true,
          input: ["text", "image", "pdf", "video"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 200000,
          maxTokens: 131072,
        },
        {
          id: "muse-spark-1.2",
          name: "Muse Spark 1.2",
          reasoning: true,
          input: ["text", "image", "pdf", "video"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 200000,
          maxTokens: 131072,
        },
        {
          id: "muse-spark-1.2-contributor",
          name: "Muse Spark 1.2 Contributor",
          reasoning: true,
          input: ["text", "image", "pdf", "video"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 200000,
          maxTokens: 131072,
        },
        {
          id: "muse-spark-1.3",
          name: "Muse Spark 1.3",
          reasoning: true,
          input: ["text", "image", "pdf", "video"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 200000,
          maxTokens: 131072,
        },
        {
          id: "muse-spark-1.3-contributor",
          name: "Muse Spark 1.3 Contributor",
          reasoning: true,
          input: ["text", "image", "pdf", "video"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 200000,
          maxTokens: 131072,
        },
      ],
    });
  } catch (e) {
    // fallback
  }
}
