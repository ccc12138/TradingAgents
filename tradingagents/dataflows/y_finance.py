from typing import Annotated
from datetime import datetime
from dateutil.relativedelta import relativedelta
import yfinance as yf
import os
import time
import random
from pathlib import Path
from .stockstats_utils import StockstatsUtils

def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "too many requests" in message
        or "rate limited" in message
        or "rate-limit" in message
        or "http error 429" in message
        or "status code 429" in message
        or "429" in message
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _cache_is_fresh(path: Path, ttl_seconds: int | None) -> bool:
    if not path.exists():
        return False
    if ttl_seconds is None:
        return True
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age_seconds <= ttl_seconds


def _get_yfinance_cache_dir() -> Path:
    from .config import get_config

    config = get_config()
    return Path(config.get("data_cache_dir", "dataflows/data_cache"))


def _get_yfinance_retry_config() -> tuple[int, float, float]:
    """
    Returns (max_attempts, backoff_base_seconds, backoff_jitter_seconds).
    """
    from .config import get_config

    config = get_config()
    max_attempts = int(config.get("yfinance_retry_max_attempts", 5))
    backoff_base_seconds = float(config.get("yfinance_retry_backoff_base_seconds", 1.0))
    backoff_jitter_seconds = float(
        config.get("yfinance_retry_backoff_jitter_seconds", 0.25)
    )
    return max_attempts, backoff_base_seconds, backoff_jitter_seconds


def _get_yfinance_cache_ttl_seconds() -> int:
    from .config import get_config

    config = get_config()
    return int(config.get("yfinance_cache_ttl_seconds", 60 * 60 * 24))


def _yfinance_download_with_retries(**download_kwargs):
    max_attempts, backoff_base_seconds, backoff_jitter_seconds = _get_yfinance_retry_config()

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return yf.download(**download_kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_rate_limit_error(exc) or attempt == max_attempts:
                raise
            # Exponential backoff with jitter
            delay = (backoff_base_seconds * (2 ** (attempt - 1))) + random.uniform(
                0.0, backoff_jitter_seconds
            )
            time.sleep(delay)

    # Defensive: should never reach here
    raise last_exc if last_exc else RuntimeError("yfinance download failed unexpectedly")


def get_YFin_data_online(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    cache_dir = _get_yfinance_cache_dir() / "yfinance" / "history"
    cache_path = cache_dir / f"{symbol.upper()}-history-{start_date}-{end_date}.csv"

    ttl_seconds = _get_yfinance_cache_ttl_seconds()
    if _cache_is_fresh(cache_path, ttl_seconds):
        csv_string = cache_path.read_text(encoding="utf-8")
        non_empty_lines = [line for line in csv_string.splitlines() if line.strip()]
        total_records = max(0, len(non_empty_lines) - 1)
        header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        header += f"# Total records: {total_records} (cached)\n"
        header += f"# Cache file: {cache_path}\n\n"
        return header + csv_string

    # Fetch historical data for the specified date range
    # Prefer yf.download over Ticker().history() to reduce request fan-out.
    try:
        data = _yfinance_download_with_retries(
            tickers=symbol.upper(),
            start=start_date,
            end=end_date,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="column",
            multi_level_index=False,
        )
    except Exception as exc:
        # If we're rate-limited, try to fall back to whatever cache exists (even if stale).
        if _is_rate_limit_error(exc) and cache_path.exists():
            csv_string = cache_path.read_text(encoding="utf-8")
            non_empty_lines = [line for line in csv_string.splitlines() if line.strip()]
            total_records = max(0, len(non_empty_lines) - 1)
            header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            header += f"# Total records: {total_records} (cached)\n"
            header += f"# NOTE: Using stale cache due to yfinance rate limit: {exc}\n"
            header += f"# Cache file: {cache_path}\n\n"
            return header + csv_string
        raise

    # Check if data is empty
    if data.empty:
        return (
            f"No data found for symbol '{symbol}' between {start_date} and {end_date}"
        )

    # Remove timezone info from index for cleaner output
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    # Round numerical values to 2 decimal places for cleaner display
    numeric_columns = ["Open", "High", "Low", "Close", "Adj Close"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(2)

    # Convert DataFrame to CSV string
    csv_string = data.to_csv()
    _atomic_write_text(cache_path, csv_string)

    # Add header information
    header = f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string

def get_stock_stats_indicators_window(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[
        str, "The current trading date you are trading on, YYYY-mm-dd"
    ],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:

    best_ind_params = {
        # Moving Averages
        "close_50_sma": (
            "50 SMA: A medium-term trend indicator. "
            "Usage: Identify trend direction and serve as dynamic support/resistance. "
            "Tips: It lags price; combine with faster indicators for timely signals."
        ),
        "close_200_sma": (
            "200 SMA: A long-term trend benchmark. "
            "Usage: Confirm overall market trend and identify golden/death cross setups. "
            "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
        ),
        "close_10_ema": (
            "10 EMA: A responsive short-term average. "
            "Usage: Capture quick shifts in momentum and potential entry points. "
            "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
        ),
        # MACD Related
        "macd": (
            "MACD: Computes momentum via differences of EMAs. "
            "Usage: Look for crossovers and divergence as signals of trend changes. "
            "Tips: Confirm with other indicators in low-volatility or sideways markets."
        ),
        "macds": (
            "MACD Signal: An EMA smoothing of the MACD line. "
            "Usage: Use crossovers with the MACD line to trigger trades. "
            "Tips: Should be part of a broader strategy to avoid false positives."
        ),
        "macdh": (
            "MACD Histogram: Shows the gap between the MACD line and its signal. "
            "Usage: Visualize momentum strength and spot divergence early. "
            "Tips: Can be volatile; complement with additional filters in fast-moving markets."
        ),
        # Momentum Indicators
        "rsi": (
            "RSI: Measures momentum to flag overbought/oversold conditions. "
            "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
            "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
        ),
        # Volatility Indicators
        "boll": (
            "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. "
            "Usage: Acts as a dynamic benchmark for price movement. "
            "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
        ),
        "boll_ub": (
            "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
            "Usage: Signals potential overbought conditions and breakout zones. "
            "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
        ),
        "boll_lb": (
            "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
            "Usage: Indicates potential oversold conditions. "
            "Tips: Use additional analysis to avoid false reversal signals."
        ),
        "atr": (
            "ATR: Averages true range to measure volatility. "
            "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
            "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
        ),
        # Volume-Based Indicators
        "vwma": (
            "VWMA: A moving average weighted by volume. "
            "Usage: Confirm trends by integrating price action with volume data. "
            "Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses."
        ),
        "mfi": (
            "MFI: The Money Flow Index is a momentum indicator that uses both price and volume to measure buying and selling pressure. "
            "Usage: Identify overbought (>80) or oversold (<20) conditions and confirm the strength of trends or reversals. "
            "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
        ),
    }

    if indicator not in best_ind_params:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    # Optimized: Get stock data once and calculate indicators for all dates
    try:
        indicator_data = _get_stock_stats_bulk(symbol, indicator, curr_date)
        
        # Generate the date range we need
        current_dt = curr_date_dt
        date_values = []
        
        while current_dt >= before:
            date_str = current_dt.strftime('%Y-%m-%d')
            
            # Look up the indicator value for this date
            if date_str in indicator_data:
                indicator_value = indicator_data[date_str]
            else:
                indicator_value = "N/A: Not a trading day (weekend or holiday)"
            
            date_values.append((date_str, indicator_value))
            current_dt = current_dt - relativedelta(days=1)
        
        # Build the result string
        ind_string = ""
        for date_str, value in date_values:
            ind_string += f"{date_str}: {value}\n"
        
    except Exception as e:
        print(f"Error getting bulk stockstats data: {e}")
        # Fallback to original implementation if bulk method fails
        ind_string = ""
        curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        while curr_date_dt >= before:
            indicator_value = get_stockstats_indicator(
                symbol, indicator, curr_date_dt.strftime("%Y-%m-%d")
            )
            ind_string += f"{curr_date_dt.strftime('%Y-%m-%d')}: {indicator_value}\n"
            curr_date_dt = curr_date_dt - relativedelta(days=1)

    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "No description available.")
    )

    return result_str


def _get_stock_stats_bulk(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to calculate"],
    curr_date: Annotated[str, "current date for reference"]
) -> dict:
    """
    Optimized bulk calculation of stock stats indicators.
    Fetches data once and calculates indicator for all available dates.
    Returns dict mapping date strings to indicator values.
    """
    from .config import get_config
    import pandas as pd
    from stockstats import wrap
    import os
    
    config = get_config()
    online = config["data_vendors"]["technical_indicators"] != "local"
    
    if not online:
        # Local data path
        try:
            data = pd.read_csv(
                os.path.join(
                    config.get("data_cache_dir", "data"),
                    f"{symbol}-YFin-data-2015-01-01-2025-03-25.csv",
                )
            )
            df = wrap(data)
        except FileNotFoundError:
            raise Exception("Stockstats fail: Yahoo Finance data not fetched yet!")
    else:
        # Online data fetching with caching
        cache_dir = _get_yfinance_cache_dir() / "yfinance" / "download"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Stable cache key so we don't generate a new file every day.
        data_file = cache_dir / f"{symbol.upper()}-download-period-15y-1d-auto_adjust.csv"
        ttl_seconds = _get_yfinance_cache_ttl_seconds()

        if _cache_is_fresh(data_file, ttl_seconds):
            data = pd.read_csv(data_file)
            data["Date"] = pd.to_datetime(data["Date"])
        else:
            try:
                data = _yfinance_download_with_retries(
                    tickers=symbol.upper(),
                    period="15y",
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    group_by="column",
                    multi_level_index=False,
                )
                data = data.reset_index()
                data.to_csv(data_file, index=False)
            except Exception as exc:
                # If we're rate-limited, fall back to whatever cache exists (even if stale).
                if _is_rate_limit_error(exc) and data_file.exists():
                    data = pd.read_csv(data_file)
                    data["Date"] = pd.to_datetime(data["Date"])
                else:
                    raise
        
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    
    # Calculate the indicator for all rows at once
    df[indicator]  # This triggers stockstats to calculate the indicator
    
    # Create a dictionary mapping date strings to indicator values
    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]
        
        # Handle NaN/None values
        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)
    
    return result_dict


def get_stockstats_indicator(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[
        str, "The current trading date you are trading on, YYYY-mm-dd"
    ],
) -> str:

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    curr_date = curr_date_dt.strftime("%Y-%m-%d")

    try:
        indicator_value = StockstatsUtils.get_stock_stats(
            symbol,
            indicator,
            curr_date,
        )
    except Exception as e:
        print(
            f"Error getting stockstats indicator data for indicator {indicator} on {curr_date}: {e}"
        )
        return ""

    return str(indicator_value)


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date (not used for yfinance)"] = None,
) -> str:
    """
    Retrieve company fundamentals using yfinance.

    Notes:
        - This uses `yfinance.Ticker(...).info`, which may be rate-limited by Yahoo.
        - Results are cached to reduce request volume.
    """
    import json

    symbol = ticker.upper()
    cache_dir = _get_yfinance_cache_dir() / "yfinance" / "fundamentals"
    cache_path = cache_dir / f"{symbol}-fundamentals.json"

    ttl_seconds = _get_yfinance_cache_ttl_seconds()
    if _cache_is_fresh(cache_path, ttl_seconds):
        return (
            f"# Fundamentals for {symbol} (cached)\n"
            f"# Cache file: {cache_path}\n\n"
            + cache_path.read_text(encoding="utf-8")
        )

    max_attempts, backoff_base_seconds, backoff_jitter_seconds = _get_yfinance_retry_config()
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            info = yf.Ticker(symbol).info
            if not isinstance(info, dict) or not info:
                raise ValueError("yfinance returned empty fundamentals info")

            selected_keys = [
                "symbol",
                "shortName",
                "longName",
                "sector",
                "industry",
                "country",
                "website",
                "currency",
                "quoteType",
                "marketCap",
                "enterpriseValue",
                "trailingPE",
                "forwardPE",
                "pegRatio",
                "priceToSalesTrailing12Months",
                "priceToBook",
                "enterpriseToRevenue",
                "enterpriseToEbitda",
                "beta",
                "dividendRate",
                "dividendYield",
                "payoutRatio",
                "profitMargins",
                "grossMargins",
                "operatingMargins",
                "ebitdaMargins",
                "returnOnAssets",
                "returnOnEquity",
                "totalRevenue",
                "revenueGrowth",
                "earningsGrowth",
                "freeCashflow",
                "totalCash",
                "totalDebt",
                "debtToEquity",
                "currentRatio",
                "quickRatio",
                "52WeekChange",
                "lastFiscalYearEnd",
                "nextFiscalYearEnd",
            ]

            payload = {
                "ticker": symbol,
                "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "yfinance",
                "data": {k: info.get(k) for k in selected_keys if k in info},
            }

            cache_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(
                cache_path,
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            )

            return (
                f"# Fundamentals for {symbol}\n"
                f"# Data retrieved on: {payload['retrieved_at']}\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            )

        except Exception as exc:
            last_exc = exc
            if not _is_rate_limit_error(exc) or attempt == max_attempts:
                # If we're rate-limited, try to fall back to stale cache if present.
                if _is_rate_limit_error(exc) and cache_path.exists():
                    return (
                        f"# Fundamentals for {symbol} (cached)\n"
                        f"# NOTE: Using stale cache due to rate limit error: {exc}\n"
                        f"# Cache file: {cache_path}\n\n"
                        + cache_path.read_text(encoding="utf-8")
                    )
                raise

            delay = (backoff_base_seconds * (2 ** (attempt - 1))) + random.uniform(
                0.0, backoff_jitter_seconds
            )
            time.sleep(delay)

    raise last_exc if last_exc else RuntimeError("yfinance fundamentals failed unexpectedly")


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date (not used for yfinance)"] = None
):
    """Get balance sheet data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        
        if freq.lower() == "quarterly":
            data = ticker_obj.quarterly_balance_sheet
        else:
            data = ticker_obj.balance_sheet
            
        if data.empty:
            return f"No balance sheet data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Balance Sheet data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving balance sheet for {ticker}: {str(e)}"


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date (not used for yfinance)"] = None
):
    """Get cash flow data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        
        if freq.lower() == "quarterly":
            data = ticker_obj.quarterly_cashflow
        else:
            data = ticker_obj.cashflow
            
        if data.empty:
            return f"No cash flow data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Cash Flow data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving cash flow for {ticker}: {str(e)}"


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date (not used for yfinance)"] = None
):
    """Get income statement data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        
        if freq.lower() == "quarterly":
            data = ticker_obj.quarterly_income_stmt
        else:
            data = ticker_obj.income_stmt
            
        if data.empty:
            return f"No income statement data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Income Statement data for {ticker.upper()} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving income statement for {ticker}: {str(e)}"


def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"]
):
    """Get insider transactions data from yfinance."""
    try:
        ticker_obj = yf.Ticker(ticker.upper())
        data = ticker_obj.insider_transactions
        
        if data is None or data.empty:
            return f"No insider transactions data found for symbol '{ticker}'"
            
        # Convert to CSV string for consistency with other functions
        csv_string = data.to_csv()
        
        # Add header information
        header = f"# Insider Transactions data for {ticker.upper()}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        return header + csv_string
        
    except Exception as e:
        return f"Error retrieving insider transactions for {ticker}: {str(e)}"
