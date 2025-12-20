import chromadb
from chromadb.config import Settings
from openai import OpenAI
import hashlib
import logging
from typing import Any, Dict, Tuple


class FinancialSituationMemory:
    def __init__(self, name, config):
        self._log = logging.getLogger(__name__)
        self._config = config
        if config["backend_url"] == "http://localhost:11434/v1":
            default_embedding_model = "nomic-embed-text"
        else:
            default_embedding_model = "text-embedding-3-large"
        self.embedding = config.get("embedding_model", default_embedding_model)
        self.client = OpenAI(base_url=config["backend_url"])
        self.quick_llm_model = config.get("quick_think_llm")

        default_embedding_ctx = 8000
        self.embedding_context_length_tokens = int(
            config.get("embedding_context_length_tokens", default_embedding_ctx)
        )
        self.embedding_summarize_margin_tokens = int(
            config.get("embedding_summarize_margin_tokens", 256)
        )
        self.embedding_summarize_enabled = self._coerce_bool(
            config.get("embedding_summarize_enabled", True), default=True
        )
        self.embedding_summary_max_tokens = int(
            config.get("embedding_summary_max_tokens", 1024)
        )
        self.embedding_summary_cache_max_items = int(
            config.get("embedding_summary_cache_max_items", 256)
        )
        self.embedding_log_summarization = self._coerce_bool(
            config.get("embedding_log_summarization", False), default=False
        )

        self._summary_cache: Dict[str, str] = {}
        self.chroma_client = chromadb.Client(Settings(allow_reset=True))
        self.situation_collection = self.chroma_client.create_collection(name=name)

    def _coerce_bool(self, value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False
        return default

    def _estimate_tokens(self, text: str) -> int:
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return int(non_ascii_chars + (ascii_chars / 4))

    def _truncate_middle(self, text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        if max_chars < 200:
            return text[:max_chars]
        head = max_chars // 2
        tail = max_chars - head
        return f"{text[:head]}\n...\n{text[-tail:]}"

    def _shrink_to_token_budget(self, text: str, token_budget: int) -> str:
        token_budget = max(64, int(token_budget))
        est = self._estimate_tokens(text)
        if est <= token_budget:
            return text

        scale = token_budget / max(est, 1)
        max_chars = int(len(text) * scale * 0.95)
        return self._truncate_middle(text, max_chars=max_chars)

    def _ollama_extra_body(self) -> Dict[str, Any] | None:
        if self._config.get("backend_url") != "http://localhost:11434/v1":
            return None
        return {"options": {"num_ctx": int(self._config.get("ollama_num_ctx", 32768))}}

    def prepare_text_for_embedding(self, text: str) -> Tuple[str, Dict[str, Any]]:
        cleaned = (text or "").strip()
        if not cleaned:
            return " ", {"mode": "empty", "source_tokens_est": 0, "final_tokens_est": 1}

        source_tokens_est = self._estimate_tokens(cleaned)
        token_budget = self.embedding_context_length_tokens - self.embedding_summarize_margin_tokens

        if (not self.embedding_summarize_enabled) or (source_tokens_est <= token_budget):
            return cleaned, {
                "mode": "raw",
                "source_tokens_est": source_tokens_est,
                "final_tokens_est": source_tokens_est,
            }

        cache_key = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        cached = self._summary_cache.get(cache_key)
        if cached is not None:
            return cached, {
                "mode": "summarized_cached",
                "source_tokens_est": source_tokens_est,
                "final_tokens_est": self._estimate_tokens(cached),
            }

        prepared = self._summarize_for_embedding(cleaned)
        prepared = self._shrink_to_token_budget(prepared, token_budget=token_budget)

        if (
            self.embedding_summary_cache_max_items > 0
            and len(self._summary_cache) >= self.embedding_summary_cache_max_items
        ):
            self._summary_cache.clear()
        self._summary_cache[cache_key] = prepared

        if self.embedding_log_summarization:
            self._log.info(
                "Summarized embedding text (%s -> %s tokens est, model=%s)",
                source_tokens_est,
                self._estimate_tokens(prepared),
                self.quick_llm_model,
            )

        return prepared, {
            "mode": "summarized",
            "source_tokens_est": source_tokens_est,
            "final_tokens_est": self._estimate_tokens(prepared),
        }

    def _summarize_for_embedding(self, text: str) -> str:
        if not self.quick_llm_model:
            return self._shrink_to_token_budget(
                text,
                token_budget=self.embedding_context_length_tokens
                - self.embedding_summarize_margin_tokens,
            )

        safe_input_budget = int(self._config.get("embedding_summarize_input_max_tokens", 32000))
        safe_text = self._shrink_to_token_budget(text, token_budget=safe_input_budget)

        system_prompt = (
            "You compress long market situation text into a high-density summary for semantic retrieval.\n"
            "Rules:\n"
            "- Keep tickers, company names, dates, numbers, units, and key events.\n"
            "- Keep technical indicators/signals, sentiment, news catalysts, fundamentals.\n"
            "- Remove repetition and boilerplate.\n"
            "- Use the same language as the input.\n"
            "- Output plain text with short headings/bullets; no markdown tables."
        )

        user_prompt = (
            "Summarize the following text for embedding-based retrieval. "
            "Be concise but information-dense.\n\n"
            f"{safe_text}"
        )

        try:
            kwargs: Dict[str, Any] = {}
            extra_body = self._ollama_extra_body()
            if extra_body:
                kwargs["extra_body"] = extra_body

            response = self.client.chat.completions.create(
                model=self.quick_llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=self.embedding_summary_max_tokens,
                **kwargs,
            )
            summary = (response.choices[0].message.content or "").strip()
            return summary or safe_text
        except Exception as e:
            if self.embedding_log_summarization:
                self._log.warning(
                    "Failed to summarize for embedding, falling back to truncated text (model=%s): %s",
                    self.quick_llm_model,
                    e,
                )
            return safe_text

    def _embed_prepared_text(self, prepared_text: str) -> list[float]:
        kwargs: Dict[str, Any] = {}
        extra_body = self._ollama_extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body

        response = self.client.embeddings.create(
            model=self.embedding,
            input=prepared_text,
            encoding_format="float",
            **kwargs,
        )
        return response.data[0].embedding

    def get_embedding(self, text):
        """Get embedding for a text (auto-summarizes when too long)."""
        prepared_text, _ = self.prepare_text_for_embedding(text)
        return self._embed_prepared_text(prepared_text)

    def add_situations(self, situations_and_advice):
        """Add financial situations and their corresponding advice. Parameter is a list of tuples (situation, rec)"""

        situations = []
        ids = []
        embeddings = []
        metadatas = []

        offset = self.situation_collection.count()

        for i, (situation, recommendation) in enumerate(situations_and_advice):
            situations.append(situation)
            ids.append(str(offset + i))
            prepared_text, info = self.prepare_text_for_embedding(situation)
            embeddings.append(self._embed_prepared_text(prepared_text))

            metadata: Dict[str, Any] = {"recommendation": recommendation}
            if info["mode"].startswith("summarized"):
                metadata["embedding_summary"] = prepared_text
                metadata["embedding_summary_source_tokens_est"] = info["source_tokens_est"]
            metadatas.append(metadata)

        self.situation_collection.add(
            documents=situations,
            metadatas=metadatas,
            embeddings=embeddings,
            ids=ids,
        )

    def get_memories(self, current_situation, n_matches=1):
        """Find matching recommendations using OpenAI embeddings"""
        prepared_text, _ = self.prepare_text_for_embedding(current_situation)
        query_embedding = self._embed_prepared_text(prepared_text)

        results = self.situation_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_matches,
            include=["metadatas", "documents", "distances"],
        )

        matched_results = []
        for i in range(len(results["documents"][0])):
            matched_results.append(
                {
                    "matched_situation": results["documents"][0][i],
                    "recommendation": results["metadatas"][0][i]["recommendation"],
                    "similarity_score": 1 - results["distances"][0][i],
                }
            )

        return matched_results


if __name__ == "__main__":
    # Example usage
    matcher = FinancialSituationMemory()

    # Example data
    example_data = [
        (
            "High inflation rate with rising interest rates and declining consumer spending",
            "Consider defensive sectors like consumer staples and utilities. Review fixed-income portfolio duration.",
        ),
        (
            "Tech sector showing high volatility with increasing institutional selling pressure",
            "Reduce exposure to high-growth tech stocks. Look for value opportunities in established tech companies with strong cash flows.",
        ),
        (
            "Strong dollar affecting emerging markets with increasing forex volatility",
            "Hedge currency exposure in international positions. Consider reducing allocation to emerging market debt.",
        ),
        (
            "Market showing signs of sector rotation with rising yields",
            "Rebalance portfolio to maintain target allocations. Consider increasing exposure to sectors benefiting from higher rates.",
        ),
    ]

    # Add the example situations and recommendations
    matcher.add_situations(example_data)

    # Example query
    current_situation = """
    Market showing increased volatility in tech sector, with institutional investors 
    reducing positions and rising interest rates affecting growth stock valuations
    """

    try:
        recommendations = matcher.get_memories(current_situation, n_matches=2)

        for i, rec in enumerate(recommendations, 1):
            print(f"\nMatch {i}:")
            print(f"Similarity Score: {rec['similarity_score']:.2f}")
            print(f"Matched Situation: {rec['matched_situation']}")
            print(f"Recommendation: {rec['recommendation']}")

    except Exception as e:
        print(f"Error during recommendation: {str(e)}")
