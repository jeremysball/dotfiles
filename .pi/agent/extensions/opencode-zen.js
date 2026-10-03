/**
 * Registers the opencode-go (paid subscription) and opencode (Zen free tier)
 * providers for pi, mirroring their opencode.jsonc / models.dev definitions
 * so `--executor pi --model opencode-go/<id>` and `opencode/<id>-free` work.
 * Both endpoints are OpenAI-compatible. The current environment exposes
 * separate provider-key aliases: OPENCODE_JNM_API_KEY for OpenCode Go and
 * OPENCODE_ZEN_LX_API_KEY for Zen. The bare Zen endpoint
 * (https://opencode.ai/zen/v1) rejects requests with no/invalid key even for
 * the nominally "free" models.
 *
 * 2026-08-30: the opencode-go block below was commented out (subscription
 * lapsed). Current liveness is recorded only in
 * .config/opencode/provider-status.yml in the dotfiles repo.
 */
export default function (pi) {
// DEAD 2026-08-30: opencode-go subscription lapsed. Block commented
// out, not deleted, so the provider shape survives for a future
// re-enable. Current liveness: .config/opencode/provider-status.yml.
// See providers/pre-retirement-2026-08-30 tag in ~/.pi and ~/.dotfiles.
//   pi.registerProvider("opencode-go", {
//     name: "OpenCode Go",
//     baseUrl: "https://opencode.ai/zen/go/v1",
//     apiKey: "$OPENCODE_JNM_API_KEY",
//     api: "openai-completions",
//     models: [
//       { id: "deepseek-v4-flash", name: "DeepSeek V4 Flash", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 384000 },
//       { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 384000 },
//       { id: "glm-5.1", name: "GLM-5.1", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 202752, maxTokens: 32768 },
//       { id: "glm-5.2", name: "GLM-5.2", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 131072 },
//       { id: "grok-4.5", name: "Grok 4.5", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 500000, maxTokens: 500000 },
//       { id: "hy3", name: "Hy3", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 256000, maxTokens: 64000 },
//       { id: "kimi-k2.6", name: "Kimi K2.6", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 262144, maxTokens: 65536 },
//       { id: "kimi-k2.7-code", name: "Kimi K2.7 Code", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 262144, maxTokens: 262144 },
//       { id: "kimi-k3", name: "Kimi K3 (2x usage)", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1048576, maxTokens: 131072 },
//       { id: "mimo-v2.5", name: "MiMo V2.5", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 128000 },
//       { id: "mimo-v2.5-pro", name: "MiMo V2.5 Pro", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1048576, maxTokens: 128000 },
//       { id: "minimax-m2.7", name: "MiniMax-M2.7", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 204800, maxTokens: 131072 },
//       { id: "minimax-m3", name: "MiniMax-M3", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 131072 },
//       { id: "qwen3.6-plus", name: "Qwen3.6 Plus", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 65536 },
//       { id: "qwen3.7-max", name: "Qwen3.7 Max", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 65536 },
//       { id: "qwen3.7-plus", name: "Qwen3.7 Plus", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 65536 },
//     ],
//   });

  pi.registerProvider("opencode", {
    name: "OpenCode Zen",
    baseUrl: "https://opencode.ai/zen/v1",
    apiKey: "$OPENCODE_ZEN_LX_API_KEY",
    api: "openai-completions",
    models: [
      { id: "big-pickle", name: "Big Pickle", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 32000 },
      { id: "deepseek-v4-flash-free", name: "DeepSeek V4 Flash Free", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 128000 },
      { id: "laguna-s-2.1-free", name: "Laguna S 2.1 Free", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 256000, maxTokens: 32000 },
      { id: "ling-3.0-flash-free", name: "Ling-3.0-flash Free", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 262144, maxTokens: 32768 },
      { id: "mimo-v2.5-free", name: "MiMo V2.5 Free", reasoning: true, input: ["text", "image"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 32000 },
      { id: "nemotron-3-ultra-free", name: "Nemotron 3 Ultra Free", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 128000 },
      { id: "north-mini-code-free", name: "North Mini Code Free", reasoning: true, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 256000, maxTokens: 64000 },
    ],
  });
}


