from __future__ import annotations

import json
import time
import uuid

from .db import Database, utc_now
from .providers import ProviderManager


async def benchmark_provider(
    database: Database, providers: ProviderManager, provider_id: str, model_id: str
) -> dict[str, object]:
    provider = providers.get(provider_id)
    started = time.perf_counter()
    result = await provider.chat(
        model_id,
        [
            {"role": "system", "content": "Answer briefly and accurately."},
            {"role": "user", "content": "In two sentences, explain why local AI can improve privacy."},
        ],
        options={"temperature": 0},
    )
    elapsed = max(time.perf_counter() - started, 0.001)
    tokens_per_second = result.completion_tokens / elapsed if result.completion_tokens else None
    structured_ok = False
    try:
        structured = await provider.chat(
            model_id,
            [{"role": "user", "content": "Return JSON with a boolean field named ok set to true."}],
            response_format={"type": "json_object"},
            options={"temperature": 0},
        )
        structured_ok = json.loads(structured.content).get("ok") is True
    except Exception:
        structured_ok = False
    identifier = uuid.uuid4().hex
    database.execute(
        """INSERT INTO benchmarks(id,provider_id,model_id,tokens_per_second,first_token_ms,
           structured_output_ok,tool_calling_ok,measured_at) VALUES(?,?,?,?,?,?,?,?)""",
        (identifier, provider_id, model_id, tokens_per_second, elapsed * 1000, int(structured_ok), 0, utc_now()),
    )
    return {
        "id": identifier,
        "provider_id": provider_id,
        "model_id": model_id,
        "tokens_per_second": tokens_per_second,
        "first_token_ms": elapsed * 1000,
        "structured_output_ok": structured_ok,
        "tool_calling_ok": False,
    }
