import questionary
from typing import Any, List, Optional, Tuple, Dict
import ollama as ollama_client
from rich.console import Console
import os
from openai import OpenAI
import requests
import re

from cli.models import AnalystType
from tradingagents.i18n import get_text

console = Console()

_OPENAI_MODEL_LIST_CACHE: Dict[str, list[tuple[str, str]]] = {}
_ANTHROPIC_MODEL_LIST_CACHE: Dict[str, list[tuple[str, str]]] = {}
_GOOGLE_MODEL_LIST_CACHE: Dict[str, list[tuple[str, str]]] = {}

_NON_CHAT_MODEL_PATTERNS = [
    r"embedding",
    r"embed",
    r"tts",
    r"whisper",
    r"transcrib",
    r"speech",
    r"audio",
    r"moderation",
    r"rerank",
]


def _looks_like_non_chat_model(model_id: str) -> bool:
    lowered = (model_id or "").lower()
    return any(re.search(pattern, lowered) for pattern in _NON_CHAT_MODEL_PATTERNS)


def _filter_chat_models(provider: str, models: list[tuple[str, str]]) -> list[tuple[str, str]]:
    provider_key = (provider or "").lower()
    filtered: list[tuple[str, str]] = []
    for display, value in models:
        model_id = str(value)
        if not model_id or _looks_like_non_chat_model(model_id):
            continue

        lowered = model_id.lower()
        if provider_key == "openai":
            # Keep OpenAI chat/reasoning model families.
            if lowered.startswith("gpt-") or re.match(r"^o\\d", lowered) or lowered in {
                "o1",
                "o3",
                "o3-mini",
                "o4-mini",
            }:
                filtered.append((display, value))
            continue

        if provider_key == "google":
            # Keep Gemini chat models only.
            if lowered.startswith("gemini"):
                filtered.append((display, value))
            continue

        if provider_key == "anthropic":
            # Anthropic list endpoint should already be Claude-only, but keep it strict.
            if "claude" in lowered:
                filtered.append((display, value))
            continue

        # OpenRouter / Ollama: keep everything except obvious non-chat models.
        filtered.append((display, value))

    return filtered


def get_ollama_models() -> list[tuple[str, str]]:
    """Fetch available models from local Ollama instance."""
    try:
        response = ollama_client.list()
        # Handle both dict and object response formats
        models = getattr(response, 'models', None) or response.get('models', [])
        if models:
            result = [
                (
                    getattr(m, "model", None) or m.get("name", str(m)),
                    getattr(m, "model", None) or m.get("name", str(m)),
                )
                for m in models
            ]
            return _filter_chat_models("ollama", result)
    except Exception:
        pass
    return _filter_chat_models("ollama", [("llama3.1", "llama3.1"), ("llama3.2", "llama3.2")])


def check_ollama_connection() -> bool:
    """Check if Ollama is running."""
    try:
        ollama_client.list()
        return True
    except Exception:
        return False


def get_openai_compatible_models(base_url: str) -> list[tuple[str, str]]:
    """Fetch model ids from an OpenAI-compatible /v1/models endpoint.

    Returns [] on any failure.
    """
    if not base_url:
        return []

    cached = _OPENAI_MODEL_LIST_CACHE.get(base_url)
    if cached is not None:
        return cached

    max_items = int(os.getenv("TRADINGAGENTS_DYNAMIC_MODEL_LIST_MAX", "200"))
    try:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        client = OpenAI(base_url=base_url, api_key=api_key)
        models = client.models.list()

        ids: list[str] = []
        for model in getattr(models, "data", []) or models:
            model_id = getattr(model, "id", None)
            if model_id is None and isinstance(model, dict):
                model_id = model.get("id")
            if model_id:
                ids.append(str(model_id))

        ids = sorted(set(ids))
        if max_items > 0:
            ids = ids[:max_items]

        fetched = [(model_id, model_id) for model_id in ids]
        _OPENAI_MODEL_LIST_CACHE[base_url] = fetched
        return fetched
    except Exception:
        _OPENAI_MODEL_LIST_CACHE[base_url] = []
        return []


def get_anthropic_models(base_url: str) -> list[tuple[str, str]]:
    """Fetch model ids from Anthropic's /v1/models endpoint.

    Requires ANTHROPIC_API_KEY (or CLAUDE_API_KEY). Returns [] on any failure.
    """
    if not base_url:
        return []

    cached = _ANTHROPIC_MODEL_LIST_CACHE.get(base_url)
    if cached is not None:
        return cached

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        _ANTHROPIC_MODEL_LIST_CACHE[base_url] = []
        return []

    version = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
    url = f"{base_url.rstrip('/')}/v1/models"
    max_items = int(os.getenv("TRADINGAGENTS_DYNAMIC_MODEL_LIST_MAX", "200"))
    try:
        resp = requests.get(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": version,
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        ids = []
        for item in payload.get("data", []) or []:
            model_id = item.get("id")
            if model_id:
                ids.append(str(model_id))
        ids = sorted(set(ids))
        if max_items > 0:
            ids = ids[:max_items]
        fetched = [(model_id, model_id) for model_id in ids]
        _ANTHROPIC_MODEL_LIST_CACHE[base_url] = fetched
        return fetched
    except Exception:
        _ANTHROPIC_MODEL_LIST_CACHE[base_url] = []
        return []


def get_google_models(base_url: str) -> list[tuple[str, str]]:
    """Fetch model ids from Google GenAI `models.list`.

    Requires GEMINI_API_KEY or GOOGLE_API_KEY. Returns [] on any failure.
    """
    if not base_url:
        return []

    cached = _GOOGLE_MODEL_LIST_CACHE.get(base_url)
    if cached is not None:
        return cached

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        _GOOGLE_MODEL_LIST_CACHE[base_url] = []
        return []

    url = f"{base_url.rstrip('/')}/models"
    max_items = int(os.getenv("TRADINGAGENTS_DYNAMIC_MODEL_LIST_MAX", "200"))
    try:
        resp = requests.get(url, params={"key": api_key}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        ids = []
        for item in payload.get("models", []) or []:
            name = item.get("name")
            if not name:
                continue
            # API returns "models/<id>"
            model_id = str(name).split("/", 1)[-1]
            ids.append(model_id)
        ids = sorted(set(ids))
        if max_items > 0:
            ids = ids[:max_items]
        fetched = [(model_id, model_id) for model_id in ids]
        _GOOGLE_MODEL_LIST_CACHE[base_url] = fetched
        return fetched
    except Exception:
        _GOOGLE_MODEL_LIST_CACHE[base_url] = []
        return []


def get_provider_models(provider: str, base_url: Optional[str]) -> list[tuple[str, str]]:
    provider_key = (provider or "").lower()
    if provider_key == "ollama":
        return get_ollama_models()
    if provider_key in {"openai", "openrouter"}:
        return _filter_chat_models(provider_key, get_openai_compatible_models(base_url or ""))
    if provider_key == "anthropic":
        return _filter_chat_models(provider_key, get_anthropic_models(base_url or ""))
    if provider_key == "google":
        return _filter_chat_models(provider_key, get_google_models(base_url or ""))
    return []


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


def select_shallow_thinking_agent(provider, lang: str = "en", backend_url: Optional[str] = None) -> str:
    """Select shallow thinking llm engine using an interactive selection."""

    options = get_provider_models(provider, backend_url)
    if not options:
        console.print("\n[red]Failed to fetch model list for the selected provider.[/red]")
        exit(1)

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


def select_deep_thinking_agent(provider, lang: str = "en", backend_url: Optional[str] = None) -> str:
    """Select deep thinking llm engine using an interactive selection."""

    options = get_provider_models(provider, backend_url)
    if not options:
        console.print("\n[red]Failed to fetch model list for the selected provider.[/red]")
        exit(1)

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
