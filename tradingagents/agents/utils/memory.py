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
        """
        Heuristic token estimator used as a fallback when exact tokenization is unavailable.
        """
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return int(non_ascii_chars + (ascii_chars / 4))

    def _count_tokens(self, text: str, *, model: str | None = None) -> int:
        """
        Best-effort token counter.

        - If `tiktoken` is available, use it for a closer-to-real count.
        - Otherwise, fall back to a heuristic estimator.
        """
        cleaned = text or ""
        if not cleaned:
            return 0

        try:
            import tiktoken  # type: ignore

            encoding = None
            if model:
                try:
                    encoding = tiktoken.encoding_for_model(model)
                except Exception:
                    encoding = None
            if encoding is None:
                encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(cleaned))
        except Exception:
            return self._estimate_tokens(cleaned)

    def _truncate_middle(self, text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        if max_chars < 200:
            return text[:max_chars]
        head = max_chars // 2
        tail = max_chars - head
        return f"{text[:head]}\n...\n{text[-tail:]}"

    def _shrink_to_token_budget(
        self, text: str, token_budget: int, *, model: str | None = None
    ) -> str:
        token_budget = max(64, int(token_budget))
        current_tokens = self._count_tokens(text, model=model)
        if current_tokens <= token_budget:
            return text

        candidate = text
        for _ in range(10):
            current_tokens = self._count_tokens(candidate, model=model)
            if current_tokens <= token_budget:
                return candidate

            scale = token_budget / max(current_tokens, 1)
            max_chars = int(len(candidate) * scale * 0.9)
            candidate = self._truncate_middle(candidate, max_chars=max(200, max_chars))

        # Defensive fallback
        return self._truncate_middle(candidate, max_chars=max(200, len(candidate) // 2))

    def _ollama_extra_body(self) -> Dict[str, Any] | None:
        if self._config.get("backend_url") != "http://localhost:11434/v1":
            return None
        return {"options": {"num_ctx": int(self._config.get("ollama_num_ctx", 32768))}}

    def prepare_text_for_embedding(self, text: str) -> Tuple[str, Dict[str, Any]]:
        cleaned = (text or "").strip()
        if not cleaned:
            return " ", {"mode": "empty", "source_tokens_est": 0, "final_tokens_est": 1}

        source_tokens_est = self._count_tokens(cleaned, model=self.embedding)
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
                "final_tokens_est": self._count_tokens(cached, model=self.embedding),
            }

        prepared = self._summarize_for_embedding(cleaned)
        prepared = self._shrink_to_token_budget(
            prepared, token_budget=token_budget, model=self.embedding
        )

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
                self._count_tokens(prepared, model=self.embedding),
                self.quick_llm_model,
            )

        return prepared, {
            "mode": "summarized",
            "source_tokens_est": source_tokens_est,
            "final_tokens_est": self._count_tokens(prepared, model=self.embedding),
        }

    def _summarize_for_embedding(self, text: str) -> str:
        if not self.quick_llm_model:
            return self._shrink_to_token_budget(
                text,
                token_budget=self.embedding_context_length_tokens
                - self.embedding_summarize_margin_tokens,
                model=self.embedding,
            )

        safe_input_budget = int(self._config.get("embedding_summarize_input_max_tokens", 32000))
        safe_text = self._shrink_to_token_budget(
            text, token_budget=safe_input_budget, model=self.quick_llm_model
        )

        system_prompt = (
            "你是一个“交易情景记忆压缩器”，负责把很长的市场/交易上下文压缩成适合语义检索的“情景记忆”。\n"
            "目标：让后续检索能基于情景特征匹配（而不是复述原文）。\n"
            "规则：\n"
            "- 保留：标的/公司名、日期/时间范围、关键数字(价格/涨跌/估值/指标值)、主要事件/催化、关键风险。\n"
            "- 保留：技术信号/指标结论、情绪/新闻要点、基本面要点（只保留能区分情景的部分）。\n"
            "- 移除：重复、冗长背景、无信息密度的措辞。\n"
            "- 不要编造未知信息；不要给交易建议（建议在别处生成）。\n"
            "- 使用与输入相同的语言。\n"
            "- 输出纯文本（不要 markdown 表格），按固定小标题分段，每段 3-8 条要点。\n"
            "固定格式：\n"
            "情景标题：<一句话概括>\n"
            "标的/时间：...\n"
            "市场环境：...\n"
            "技术面信号：...\n"
            "消息&情绪：...\n"
            "基本面要点：...\n"
            "关键风险：...\n"
            "一句话结论：<仅描述局面，不给建议>"
        )

        user_prompt = (
            "请将以下文本压缩为“情景记忆”（用于向量检索）。尽量信息密集、结构化。\n\n"
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

        try:
            response = self.client.embeddings.create(
                model=self.embedding,
                input=prepared_text,
                encoding_format="float",
                **kwargs,
            )
            return response.data[0].embedding
        except Exception as exc:
            # Some providers enforce strict token limits; if we still exceeded it,
            # shrink and retry once with a stricter budget.
            msg = str(exc).lower()
            if "maximum context length" in msg or "context length" in msg:
                token_budget = self.embedding_context_length_tokens - self.embedding_summarize_margin_tokens
                tightened = self._shrink_to_token_budget(
                    prepared_text, token_budget=token_budget, model=self.embedding
                )
                if tightened != prepared_text:
                    response = self.client.embeddings.create(
                        model=self.embedding,
                        input=tightened,
                        encoding_format="float",
                        **kwargs,
                    )
                    return response.data[0].embedding
            raise

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
            metadata = (results.get("metadatas") or [[{}]])[0][i] or {}
            matched_document = results["documents"][0][i]
            matched_summary = metadata.get("embedding_summary")

            # Prefer the embedding summary for readability; fall back to a truncated raw document.
            display_situation = matched_summary or matched_document
            if isinstance(display_situation, str) and len(display_situation) > 4000:
                display_situation = self._truncate_middle(display_situation, max_chars=4000)

            matched_results.append(
                {
                    "matched_situation": display_situation,
                    "recommendation": metadata.get("recommendation", ""),
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
