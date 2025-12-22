from typing import Annotated
from datetime import datetime
from .googlenews_utils import getNewsData


def get_google_news(
    query: Annotated[str, "Query to search with"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    query = query.replace(" ", "+")

    # Validate date formats
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    news_results = getNewsData(query, start_date, end_date)

    news_str = ""

    for news in news_results:
        news_str += (
            f"### {news['title']} (source: {news['source']}) \n\n{news['snippet']}\n\n"
        )

    if len(news_results) == 0:
        return ""

    return f"## {query} Google News, from {start_date} to {end_date}:\n\n{news_str}"
