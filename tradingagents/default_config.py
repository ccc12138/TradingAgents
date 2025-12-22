import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_dir": os.getenv(
        "TRADINGAGENTS_DATA_DIR",
        os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")), "data"),
    ),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # yfinance robustness (avoid Yahoo 429 rate limits)
    # Cache is used for yfinance price history + bulk downloads.
    "yfinance_cache_ttl_seconds": int(os.getenv("TRADINGAGENTS_YFINANCE_CACHE_TTL_SECONDS", str(60 * 60 * 24))),
    "yfinance_retry_max_attempts": int(os.getenv("TRADINGAGENTS_YFINANCE_RETRY_MAX_ATTEMPTS", "5")),
    "yfinance_retry_backoff_base_seconds": float(os.getenv("TRADINGAGENTS_YFINANCE_RETRY_BACKOFF_BASE_SECONDS", "1.0")),
    "yfinance_retry_backoff_jitter_seconds": float(os.getenv("TRADINGAGENTS_YFINANCE_RETRY_BACKOFF_JITTER_SECONDS", "0.25")),
    # Language settings
    "language": "zh",  # Options: "en", "zh"
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "o4-mini",
    "quick_think_llm": "gpt-4o-mini",
    "backend_url": "https://api.openai.com/v1",
    # Embedding + memory (Chroma) settings
    # When using local embedding models (e.g. Ollama `nomic-embed-text`), long situation strings can exceed
    # the embedding model input limit. Enable summarization-before-embedding to keep retrieval working.
    "embedding_model": os.getenv("TRADINGAGENTS_EMBEDDING_MODEL", "text-embedding-3-large"),
    "embedding_summarize_enabled": os.getenv("TRADINGAGENTS_EMBEDDING_SUMMARIZE_ENABLED", "1") == "1",
    "embedding_context_length_tokens": int(os.getenv("TRADINGAGENTS_EMBEDDING_CONTEXT_LENGTH_TOKENS", "8000")),
    "embedding_summarize_margin_tokens": int(os.getenv("TRADINGAGENTS_EMBEDDING_SUMMARIZE_MARGIN_TOKENS", "256")),
    "embedding_summary_max_tokens": int(os.getenv("TRADINGAGENTS_EMBEDDING_SUMMARY_MAX_TOKENS", "1024")),
    "embedding_summarize_input_max_tokens": int(os.getenv("TRADINGAGENTS_EMBEDDING_SUMMARIZE_INPUT_MAX_TOKENS", "32000")),
    "embedding_summary_cache_max_items": int(os.getenv("TRADINGAGENTS_EMBEDDING_SUMMARY_CACHE_MAX_ITEMS", "256")),
    "embedding_log_summarization": os.getenv("TRADINGAGENTS_EMBEDDING_LOG_SUMMARIZATION", "0") == "1",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # If true, do not attempt fallback vendors when a primary vendor fails.
    # This makes runs "fail-fast" on the configured vendor(s) for each tool/category.
    "disable_vendor_fallback": False,
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: yfinance, alpha_vantage, local
        "technical_indicators": "yfinance",  # Options: yfinance, alpha_vantage, local
        "fundamental_data": "alpha_vantage", # Options: yfinance, openai, alpha_vantage, local
        "news_data": "alpha_vantage",        # Options: openai, alpha_vantage, google, local
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
        # Example: "get_news": "openai",               # Override category default
    },
}
