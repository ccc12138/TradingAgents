import questionary
from typing import List, Optional, Tuple, Dict
import ollama as ollama_client
from rich.console import Console

from cli.models import AnalystType
from tradingagents.i18n import get_text

console = Console()


def get_ollama_models() -> list[tuple[str, str]]:
    """Fetch available models from local Ollama instance."""
    try:
        response = ollama_client.list()
        # Handle both dict and object response formats
        models = getattr(response, 'models', None) or response.get('models', [])
        if models:
            return [(getattr(m, 'model', None) or m.get('name', str(m)),
                     getattr(m, 'model', None) or m.get('name', str(m))) for m in models]
    except Exception:
        pass
    return [("llama3.1", "llama3.1"), ("llama3.2", "llama3.2")]


def check_ollama_connection() -> bool:
    """Check if Ollama is running."""
    try:
        ollama_client.list()
        return True
    except Exception:
        return False

ANALYST_ORDER = [
    ("Market Analyst", AnalystType.MARKET),
    ("Social Media Analyst", AnalystType.SOCIAL),
    ("News Analyst", AnalystType.NEWS),
    ("Fundamentals Analyst", AnalystType.FUNDAMENTALS),
]


def get_ticker(lang: str = "en") -> str:
    """Prompt the user to enter a ticker symbol."""
    ticker = questionary.text(
        get_text("prompt_ticker", lang),
        validate=lambda x: len(x.strip()) > 0 or get_text("validate_ticker", lang),
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if not ticker:
        console.print(f"\n[red]{get_text('error_no_ticker', lang)}[/red]")
        exit(1)

    return ticker.strip().upper()


def get_analysis_date(lang: str = "en") -> str:
    """Prompt the user to enter a date in YYYY-MM-DD format."""
    import re
    from datetime import datetime

    def validate_date(date_str: str) -> bool:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    date = questionary.text(
        get_text("prompt_date", lang),
        validate=lambda x: validate_date(x.strip())
        or get_text("validate_date", lang),
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if not date:
        console.print(f"\n[red]{get_text('error_no_date', lang)}[/red]")
        exit(1)

    return date.strip()


def select_analysts(lang: str = "en") -> List[AnalystType]:
    """Select analysts using an interactive checkbox."""
    choices = questionary.checkbox(
        get_text("prompt_analysts", lang),
        choices=[
            questionary.Choice(display, value=value) for display, value in ANALYST_ORDER
        ],
        instruction=get_text("instruction_analysts", lang),
        validate=lambda x: len(x) > 0 or get_text("validate_analyst", lang),
        style=questionary.Style(
            [
                ("checkbox-selected", "fg:green"),
                ("selected", "fg:green noinherit"),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]
        ),
    ).ask()

    if not choices:
        console.print(f"\n[red]{get_text('error_no_analysts', lang)}[/red]")
        exit(1)

    return choices


def select_research_depth(lang: str = "en") -> int:
    """Select research depth using an interactive selection."""

    # Define research depth options with their corresponding values
    DEPTH_OPTIONS = [
        (get_text("depth_shallow", lang), 1),
        (get_text("depth_medium", lang), 3),
        (get_text("depth_deep", lang), 5),
    ]

    choice = questionary.select(
        get_text("prompt_depth", lang),
        choices=[
            questionary.Choice(display, value=value) for display, value in DEPTH_OPTIONS
        ],
        instruction=get_text("instruction_select", lang),
        style=questionary.Style(
            [
                ("selected", "fg:yellow noinherit"),
                ("highlighted", "fg:yellow noinherit"),
                ("pointer", "fg:yellow noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print(f"\n[red]{get_text('error_no_depth', lang)}[/red]")
        exit(1)

    return choice


def select_shallow_thinking_agent(provider, lang: str = "en") -> str:
    """Select shallow thinking llm engine using an interactive selection."""

    # Define shallow thinking llm engine options with their corresponding model names
    SHALLOW_AGENT_OPTIONS = {
        "openai": [
            ("GPT-4o-mini - Fast and efficient for quick tasks", "gpt-4o-mini"),
            ("GPT-4.1-nano - Ultra-lightweight model for basic operations", "gpt-4.1-nano"),
            ("GPT-4.1-mini - Compact model with good performance", "gpt-4.1-mini"),
            ("GPT-4o - Standard model with solid capabilities", "gpt-4o"),
        ],
        "anthropic": [
            ("Claude Haiku 3.5 - Fast inference and standard capabilities", "claude-3-5-haiku-latest"),
            ("Claude Sonnet 3.5 - Highly capable standard model", "claude-3-5-sonnet-latest"),
            ("Claude Sonnet 3.7 - Exceptional hybrid reasoning and agentic capabilities", "claude-3-7-sonnet-latest"),
            ("Claude Sonnet 4 - High performance and excellent reasoning", "claude-sonnet-4-0"),
        ],
        "google": [
            ("Gemini 2.0 Flash-Lite - Cost efficiency and low latency", "gemini-2.0-flash-lite"),
            ("Gemini 2.0 Flash - Next generation features, speed, and thinking", "gemini-2.0-flash"),
            ("Gemini 2.5 Flash - Adaptive thinking, cost efficiency", "gemini-2.5-flash-preview-05-20"),
        ],
        "openrouter": [
            ("Meta: Llama 4 Scout", "meta-llama/llama-4-scout:free"),
            ("Meta: Llama 3.3 8B Instruct - A lightweight and ultra-fast variant of Llama 3.3 70B", "meta-llama/llama-3.3-8b-instruct:free"),
            ("google/gemini-2.0-flash-exp:free - Gemini Flash 2.0 offers a significantly faster time to first token", "google/gemini-2.0-flash-exp:free"),
        ],
        "ollama": [
            ("llama3.1 local", "llama3.1"),
            ("llama3.2 local", "llama3.2"),
        ]
    }

    options = SHALLOW_AGENT_OPTIONS.get(provider.lower(), [])
    if provider.lower() == "ollama":
        options = get_ollama_models()

    choice = questionary.select(
        get_text("prompt_quick_llm", lang),
        choices=[
            questionary.Choice(display, value=value)
            for display, value in options
        ],
        instruction=get_text("instruction_select", lang),
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print(
            f"\n[red]{get_text('error_no_quick_llm', lang)}[/red]"
        )
        exit(1)

    return choice


def select_deep_thinking_agent(provider, lang: str = "en") -> str:
    """Select deep thinking llm engine using an interactive selection."""

    # Define deep thinking llm engine options with their corresponding model names
    DEEP_AGENT_OPTIONS = {
        "openai": [
            ("GPT-4.1-nano - Ultra-lightweight model for basic operations", "gpt-4.1-nano"),
            ("GPT-4.1-mini - Compact model with good performance", "gpt-4.1-mini"),
            ("GPT-4o - Standard model with solid capabilities", "gpt-4o"),
            ("o4-mini - Specialized reasoning model (compact)", "o4-mini"),
            ("o3-mini - Advanced reasoning model (lightweight)", "o3-mini"),
            ("o3 - Full advanced reasoning model", "o3"),
            ("o1 - Premier reasoning and problem-solving model", "o1"),
        ],
        "anthropic": [
            ("Claude Haiku 3.5 - Fast inference and standard capabilities", "claude-3-5-haiku-latest"),
            ("Claude Sonnet 3.5 - Highly capable standard model", "claude-3-5-sonnet-latest"),
            ("Claude Sonnet 3.7 - Exceptional hybrid reasoning and agentic capabilities", "claude-3-7-sonnet-latest"),
            ("Claude Sonnet 4 - High performance and excellent reasoning", "claude-sonnet-4-0"),
            ("Claude Opus 4 - Most powerful Anthropic model", "	claude-opus-4-0"),
        ],
        "google": [
            ("Gemini 2.0 Flash-Lite - Cost efficiency and low latency", "gemini-2.0-flash-lite"),
            ("Gemini 2.0 Flash - Next generation features, speed, and thinking", "gemini-2.0-flash"),
            ("Gemini 2.5 Flash - Adaptive thinking, cost efficiency", "gemini-2.5-flash-preview-05-20"),
            ("Gemini 2.5 Pro", "gemini-2.5-pro-preview-06-05"),
        ],
        "openrouter": [
            ("DeepSeek V3 - a 685B-parameter, mixture-of-experts model", "deepseek/deepseek-chat-v3-0324:free"),
            ("Deepseek - latest iteration of the flagship chat model family from the DeepSeek team.", "deepseek/deepseek-chat-v3-0324:free"),
        ],
        "ollama": [
            ("llama3.1 local", "llama3.1"),
            ("qwen3", "qwen3"),
        ]
    }
    
    options = DEEP_AGENT_OPTIONS.get(provider.lower(), [])
    if provider.lower() == "ollama":
        options = get_ollama_models()

    choice = questionary.select(
        get_text("prompt_deep_llm", lang),
        choices=[
            questionary.Choice(display, value=value)
            for display, value in options
        ],
        instruction=get_text("instruction_select", lang),
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print(f"\n[red]{get_text('error_no_deep_llm', lang)}[/red]")
        exit(1)

    return choice


def select_llm_provider(lang: str = "en") -> tuple[str, str]:
    """Select the OpenAI api url using interactive selection."""
    # Define OpenAI api options with their corresponding endpoints
    BASE_URLS = [
        ("OpenAI", "https://api.openai.com/v1"),
        ("Anthropic", "https://api.anthropic.com/"),
        ("Google", "https://generativelanguage.googleapis.com/v1"),
        ("Openrouter", "https://openrouter.ai/api/v1"),
        ("Ollama", "http://localhost:11434/v1"),        
    ]
    
    choice = questionary.select(
        get_text("prompt_provider", lang),
        choices=[
            questionary.Choice(display, value=(display, value))
            for display, value in BASE_URLS
        ],
        instruction=get_text("instruction_select", lang),
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print(f"\n[red]{get_text('error_no_provider', lang)}[/red]")
        exit(1)
    
    display_name, url = choice
    print(f"{get_text('you_selected', lang)} {display_name}\tURL: {url}")
    
    return display_name, url
