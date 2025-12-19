from typing import Annotated
from datetime import datetime, timedelta
import akshare as ak


def get_stock(
    symbol: Annotated[str, "ticker symbol (6-digit A-share code, e.g., 600519)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    try:
        # Normalize symbol (remove any prefix like 'sh' or 'sz')
        symbol = symbol.replace("sh", "").replace("sz", "").replace(".", "").strip()

        # Convert date format for akshare (YYYYMMDD)
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")

        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_fmt,
            end_date=end_fmt,
            adjust="qfq"  # Forward adjusted
        )

        if df.empty:
            return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

        # Rename columns to match expected format
        df = df.rename(columns={
            "日期": "Date",
            "开盘": "Open",
            "最高": "High",
            "最低": "Low",
            "收盘": "Close",
            "成交量": "Volume"
        })

        # Select and order columns
        cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in cols if c in df.columns]]

        csv_string = df.to_csv(index=False)
        header = f"# Stock data for {symbol} from {start_date} to {end_date}\n"
        header += f"# Total records: {len(df)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving stock data for {symbol}: {str(e)}"


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol (6-digit A-share code)"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date (optional)"] = None
) -> str:
    try:
        ticker = ticker.replace("sh", "").replace("sz", "").replace(".", "").strip()

        # Add market prefix for the API
        prefix = "SH" if ticker.startswith("6") else "SZ"
        full_symbol = f"{prefix}{ticker}"

        df = ak.stock_balance_sheet_by_report_em(symbol=full_symbol)

        if df is None or df.empty:
            return f"No balance sheet data found for symbol '{ticker}'"

        csv_string = df.to_csv(index=False)
        header = f"# Balance Sheet for {ticker} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving balance sheet for {ticker}: {str(e)}"


def get_cashflow(
    ticker: Annotated[str, "ticker symbol (6-digit A-share code)"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date (optional)"] = None
) -> str:
    try:
        ticker = ticker.replace("sh", "").replace("sz", "").replace(".", "").strip()

        prefix = "SH" if ticker.startswith("6") else "SZ"
        full_symbol = f"{prefix}{ticker}"

        df = ak.stock_cash_flow_sheet_by_report_em(symbol=full_symbol)

        if df is None or df.empty:
            return f"No cash flow data found for symbol '{ticker}'"

        csv_string = df.to_csv(index=False)
        header = f"# Cash Flow for {ticker} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving cash flow for {ticker}: {str(e)}"


def get_income_statement(
    ticker: Annotated[str, "ticker symbol (6-digit A-share code)"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date (optional)"] = None
) -> str:
    try:
        ticker = ticker.replace("sh", "").replace("sz", "").replace(".", "").strip()

        prefix = "SH" if ticker.startswith("6") else "SZ"
        full_symbol = f"{prefix}{ticker}"

        df = ak.stock_profit_sheet_by_report_em(symbol=full_symbol)

        if df is None or df.empty:
            return f"No income statement data found for symbol '{ticker}'"

        csv_string = df.to_csv(index=False)
        header = f"# Income Statement for {ticker} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + csv_string

    except Exception as e:
        return f"Error retrieving income statement for {ticker}: {str(e)}"


def get_news(
    ticker: Annotated[str, "ticker symbol (6-digit A-share code)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    try:
        ticker = ticker.replace("sh", "").replace("sz", "").replace(".", "").strip()

        # Use stock individual info which is more reliable
        df = ak.stock_individual_info_em(symbol=ticker)

        if df is None or df.empty:
            return f"No info found for symbol '{ticker}'"

        # Format as news-like output with company info
        info_items = []
        for _, row in df.iterrows():
            item = row.get("item", "")
            value = row.get("value", "")
            info_items.append(f"{item}: {value}")

        header = f"# Company Info for {ticker}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(info_items)

    except Exception as e:
        return f"Error retrieving news for {ticker}: {str(e)}"


def get_global_news(*args, **kwargs) -> str:
    return "Global news is not available via akshare in this project configuration."
