from typing import Annotated

# Import from vendor-specific modules
from .local import get_YFin_data, get_finnhub_news, get_finnhub_company_insider_sentiment, get_finnhub_company_insider_transactions, get_simfin_balance_sheet, get_simfin_cashflow, get_simfin_income_statements, get_reddit_global_news, get_reddit_company_news
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .google import get_google_news
from .openai import get_stock_news_openai, get_global_news_openai, get_fundamentals_openai
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .akshare_data import (
    get_stock as get_akshare_stock,
    get_balance_sheet as get_akshare_balance_sheet,
    get_cashflow as get_akshare_cashflow,
    get_income_statement as get_akshare_income_statement,
    get_news as get_akshare_news
)

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News (public/insiders, original/processed)",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_sentiment",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "local",
    "yfinance",
    "openai",
    "google",
    "akshare"
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "local": get_YFin_data,
        "akshare": get_akshare_stock,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "local": get_stock_stats_indicators_window
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "openai": get_fundamentals_openai,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "local": get_simfin_balance_sheet,
        "akshare": get_akshare_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "local": get_simfin_cashflow,
        "akshare": get_akshare_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "local": get_simfin_income_statements,
        "akshare": get_akshare_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "openai": get_stock_news_openai,
        "google": get_google_news,
        "local": [get_finnhub_news, get_reddit_company_news, get_google_news],
        "akshare": get_akshare_news,
    },
    "get_global_news": {
        "alpha_vantage": get_alpha_vantage_global_news,
        "openai": get_global_news_openai,
        "local": get_reddit_global_news,
    },
    "get_insider_sentiment": {
        "local": get_finnhub_company_insider_sentiment
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "local": get_finnhub_company_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")


_ALLOW_EMPTY_RESULTS_METHODS = {"get_news", "get_global_news"}


def _result_failure_reason(method: str, result) -> str | None:
    """
    Some vendor implementations return error strings instead of raising.
    Treat these as failures so routing/fail-fast behavior is consistent.
    """
    if result is None:
        return "returned None"

    if isinstance(result, str):
        stripped = result.strip()
        if stripped == "":
            if method in _ALLOW_EMPTY_RESULTS_METHODS:
                return None
            return "returned empty string"

        lowered = stripped.lower()
        if lowered.startswith(("error:", "error ")):
            return stripped.splitlines()[0]

        if lowered.startswith("no ") and " data found" in lowered:
            if method in _ALLOW_EMPTY_RESULTS_METHODS:
                return None
            return stripped.splitlines()[0]

    return None


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    config = get_config()

    # Handle comma-separated vendors
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Get all available vendors for this method for fallback
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    
    # Create fallback vendor list: primary vendors first, then remaining vendors as fallbacks.
    # Can be disabled via config for strict fail-fast behavior.
    fallback_vendors = primary_vendors.copy()
    if not config.get("disable_vendor_fallback", False):
        for vendor in all_available_vendors:
            if vendor not in fallback_vendors:
                fallback_vendors.append(vendor)

    # Debug: Print fallback ordering
    primary_str = " → ".join(primary_vendors)
    fallback_str = " → ".join(fallback_vendors)
    print(f"DEBUG: {method} - Primary: [{primary_str}] | Full fallback order: [{fallback_str}]")

    # Track results and execution state
    results = []
    vendor_attempt_count = 0
    any_primary_vendor_attempted = False
    successful_vendor = None
    vendor_errors: list[dict] = []

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            if vendor in primary_vendors:
                print(f"INFO: Vendor '{vendor}' not supported for method '{method}', falling back to next vendor")
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        is_primary_vendor = vendor in primary_vendors
        vendor_attempt_count += 1

        # Track if we attempted any primary vendor
        if is_primary_vendor:
            any_primary_vendor_attempted = True

        # Debug: Print current attempt
        vendor_type = "PRIMARY" if is_primary_vendor else "FALLBACK"
        print(f"DEBUG: Attempting {vendor_type} vendor '{vendor}' for {method} (attempt #{vendor_attempt_count})")

        # Handle list of methods for a vendor
        if isinstance(vendor_impl, list):
            vendor_methods = [(impl, vendor) for impl in vendor_impl]
            print(f"DEBUG: Vendor '{vendor}' has multiple implementations: {len(vendor_methods)} functions")
        else:
            vendor_methods = [(vendor_impl, vendor)]

        # Run methods for this vendor
        vendor_results = []
        for impl_func, vendor_name in vendor_methods:
            try:
                print(f"DEBUG: Calling {impl_func.__name__} from vendor '{vendor_name}'...")
                result = impl_func(*args, **kwargs)
                failure_reason = _result_failure_reason(method, result)
                if failure_reason:
                    print(
                        f"FAILED: {impl_func.__name__} from vendor '{vendor_name}' returned a failure result: {failure_reason}"
                    )
                    vendor_errors.append(
                        {
                            "vendor": vendor_name,
                            "impl": impl_func.__name__,
                            "exc_type": "BadResult",
                            "message": str(failure_reason),
                        }
                    )
                    continue

                vendor_results.append(result)
                print(f"SUCCESS: {impl_func.__name__} from vendor '{vendor_name}' completed successfully")
                    
            except AlphaVantageRateLimitError as e:
                if vendor == "alpha_vantage":
                    print(f"RATE_LIMIT: Alpha Vantage rate limit exceeded, falling back to next available vendor")
                    print(f"DEBUG: Rate limit details: {e}")
                vendor_errors.append(
                    {
                        "vendor": vendor_name,
                        "impl": impl_func.__name__,
                        "exc_type": type(e).__name__,
                        "message": str(e),
                    }
                )
                # Continue to next vendor for fallback
                continue
            except Exception as e:
                # Log error but continue with other implementations
                print(f"FAILED: {impl_func.__name__} from vendor '{vendor_name}' failed: {e}")
                vendor_errors.append(
                    {
                        "vendor": vendor_name,
                        "impl": impl_func.__name__,
                        "exc_type": type(e).__name__,
                        "message": str(e),
                    }
                )
                continue

        # Add this vendor's results
        if vendor_results:
            results.extend(vendor_results)
            successful_vendor = vendor
            result_summary = f"Got {len(vendor_results)} result(s)"
            print(f"SUCCESS: Vendor '{vendor}' succeeded - {result_summary}")
            
            # Stopping logic: Stop after first successful vendor for single-vendor configs
            # Multiple vendor configs (comma-separated) may want to collect from multiple sources
            if len(primary_vendors) == 1:
                print(f"DEBUG: Stopping after successful vendor '{vendor}' (single-vendor config)")
                break
        else:
            print(f"FAILED: Vendor '{vendor}' produced no results")

    # Final result summary
    if not results:
        print(f"FAILURE: All {vendor_attempt_count} vendor attempts failed for method '{method}'")
        attempted_vendors_str = " → ".join(
            [v for v in fallback_vendors if v in VENDOR_METHODS.get(method, {})]
        )
        error_lines = []
        for err in vendor_errors:
            msg = err.get("message", "")
            if len(msg) > 300:
                msg = msg[:300] + "…"
            error_lines.append(
                f"- {err.get('vendor')}:{err.get('impl')} -> {err.get('exc_type')}: {msg}"
            )

        hints = []
        combined_messages = "\n".join(e.get("message", "") for e in vendor_errors)
        vendors_with_errors = {e.get("vendor") for e in vendor_errors if e.get("vendor")}

        if "alpha_vantage" in vendors_with_errors:
            hints.append(
                "Set `ALPHA_VANTAGE_API_KEY` (Alpha Vantage) or switch `data_vendors['fundamental_data']` to `yfinance`."
            )
        if "openai" in vendors_with_errors:
            hints.append(
                "Set `OPENAI_API_KEY` (or configure your LLM provider credentials) if using the `openai` vendor."
            )
        if "yfinance" in vendors_with_errors and "no module named" in combined_messages.lower():
            hints.append("Install `yfinance` (dependency) or disable the `yfinance` vendor.")

        hint_block = "\n".join(f"- {h}" for h in hints) if hints else "- Check your vendor config and API/network access."
        error_block = "\n".join(error_lines) if error_lines else "- (no exception details captured)"

        raise RuntimeError(
            "\n".join(
                [
                    f"All vendor implementations failed for method '{method}'.",
                    f"Configured vendor(s): {vendor_config}",
                    f"Attempted vendor order: {attempted_vendors_str or '(none)'}",
                    "Errors:",
                    error_block,
                    "Fix hints:",
                    hint_block,
                ]
            )
        )
    else:
        print(f"FINAL: Method '{method}' completed with {len(results)} result(s) from {vendor_attempt_count} vendor attempt(s)")

    # Return single result if only one, otherwise concatenate as string
    if len(results) == 1:
        return results[0]
    else:
        # Convert all results to strings and concatenate
        return '\n'.join(str(result) for result in results)
