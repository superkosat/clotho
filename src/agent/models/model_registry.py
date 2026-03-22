"""Known model context window and output token limits.

Each entry maps a model name to its context limits. Used to auto-populate
ModelProfile fields for known models at profile creation time.

context_window    : total input tokens the model accepts in one call
max_output_tokens : maximum tokens the model can produce in one call
"""

MODEL_REGISTRY: dict[str, dict[str, int]] = {
    # Anthropic — Claude 4.x
    "claude-opus-4-6":              {"context_window": 200_000, "max_output_tokens": 32_000},
    "claude-sonnet-4-6":            {"context_window": 200_000, "max_output_tokens": 16_000},
    "claude-haiku-4-5-20251001":    {"context_window": 200_000, "max_output_tokens": 8_192},
    # Anthropic — Claude 3.5 / 3
    "claude-3-5-sonnet-20241022":   {"context_window": 200_000, "max_output_tokens": 8_192},
    "claude-3-5-haiku-20241022":    {"context_window": 200_000, "max_output_tokens": 8_192},
    "claude-3-opus-20240229":       {"context_window": 200_000, "max_output_tokens": 4_096},
    "claude-3-haiku-20240307":      {"context_window": 200_000, "max_output_tokens": 4_096},
    "claude-3-sonnet-20240229":     {"context_window": 200_000, "max_output_tokens": 4_096},
    # OpenAI
    "gpt-4o":                       {"context_window": 128_000, "max_output_tokens": 16_384},
    "gpt-4o-mini":                  {"context_window": 128_000, "max_output_tokens": 16_384},
    "gpt-4-turbo":                  {"context_window": 128_000, "max_output_tokens": 4_096},
    "gpt-4-turbo-preview":          {"context_window": 128_000, "max_output_tokens": 4_096},
    "gpt-4":                        {"context_window":   8_192, "max_output_tokens": 4_096},
    "gpt-3.5-turbo":                {"context_window":  16_385, "max_output_tokens": 4_096},
    # Ollama / Llama
    "llama3.2":                     {"context_window": 131_072, "max_output_tokens": 4_096},
    "llama3.2:1b":                  {"context_window": 131_072, "max_output_tokens": 4_096},
    "llama3.2:3b":                  {"context_window": 131_072, "max_output_tokens": 4_096},
    "llama3.1":                     {"context_window": 131_072, "max_output_tokens": 4_096},
    "llama3.1:8b":                  {"context_window": 131_072, "max_output_tokens": 4_096},
    "llama3.1:70b":                 {"context_window": 131_072, "max_output_tokens": 4_096},
    "llama3":                       {"context_window":   8_192, "max_output_tokens": 2_048},
    "llama3:8b":                    {"context_window":   8_192, "max_output_tokens": 2_048},
    "llama3:70b":                   {"context_window":   8_192, "max_output_tokens": 2_048},
    "llama2":                       {"context_window":   4_096, "max_output_tokens": 2_048},
    # Ollama / Mistral
    "mistral":                      {"context_window":  32_768, "max_output_tokens": 4_096},
    "mistral:7b":                   {"context_window":  32_768, "max_output_tokens": 4_096},
    "mistral-nemo":                 {"context_window": 128_000, "max_output_tokens": 4_096},
    "mixtral":                      {"context_window":  32_768, "max_output_tokens": 4_096},
    # Ollama / Deepseek
    "deepseek-coder-v2":            {"context_window": 163_840, "max_output_tokens": 4_096},
    "deepseek-r1":                  {"context_window": 131_072, "max_output_tokens": 8_000},
    # Ollama / Phi
    "phi3":                         {"context_window":   4_096, "max_output_tokens": 2_048},
    "phi3:mini":                    {"context_window":   4_096, "max_output_tokens": 2_048},
    "phi3:medium":                  {"context_window":   4_096, "max_output_tokens": 2_048},
    # Ollama / Qwen
    "qwen2.5-coder":                {"context_window":  32_768, "max_output_tokens": 4_096},
    "qwen2.5":                      {"context_window":  32_768, "max_output_tokens": 4_096},
}


def lookup_model(model_name: str) -> dict[str, int] | None:
    """Return registry entry for model_name, or None if not found.

    Tries exact match first, then prefix match for versioned model names
    (e.g. "gpt-4o" matches "gpt-4o-2024-05-13").
    """
    if model_name in MODEL_REGISTRY:
        return MODEL_REGISTRY[model_name]
    for key, entry in MODEL_REGISTRY.items():
        if model_name.startswith(key) or key.startswith(model_name):
            return entry
    return None
