"""Phase 1 bug fix tests — LLMNotReadyError + flush locking."""
import os
import threading
import time
import pytest
from app.domain.ports.llm_inference import LLMNotReadyError


class TestLLMNotReadyError:
    def test_exception_exists(self):
        assert issubclass(LLMNotReadyError, Exception)

    def test_mlx_adapter_raises_when_not_loaded(self):
        from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
        adapter = MLXInferenceAdapter.__new__(MLXInferenceAdapter)
        adapter.model = None
        adapter.tokenizer = None
        adapter._is_loading = False
        adapter._model_path = "fake_model_path"  # non-empty to skip cloud fallback
        adapter._temperature = 0.7
        adapter._max_new_tokens = 256
        with pytest.raises(LLMNotReadyError, match="failed to load"):
            adapter.predict("test", "test")

    def test_mlx_adapter_raises_when_loading(self):
        from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
        adapter = MLXInferenceAdapter.__new__(MLXInferenceAdapter)
        adapter.model = None
        adapter.tokenizer = None
        adapter._is_loading = True
        with pytest.raises(LLMNotReadyError, match="still loading"):
            adapter.predict("test", "test")

    def test_extract_json_candidate_returns_balanced_object(self):
        from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter

        text = '{"direction":"LONG","rationale":"test"} trailing text'

        assert MLXInferenceAdapter._extract_json_candidate(text) == '{"direction":"LONG","rationale":"test"}'

    def test_resolve_local_path_supports_repo_root_relative_adapter_paths(self):
        from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter

        resolved = MLXInferenceAdapter._resolve_local_path("gemma4_26b_clean_adapter")

        assert resolved.endswith("gemma4_26b_clean_adapter")
        assert os.path.isdir(resolved)


class TestFlushTicksSingleLock:
    def test_concurrent_flush_no_data_loss(self):
        from app.infrastructure.storage.database import SQLiteStorageAdapter
        adapter = SQLiteStorageAdapter(db_path=":memory:")

        errors = []

        def writer(n):
            for i in range(50):
                try:
                    adapter.save_tick("TEST", {
                        "time": f"2024-01-01T00:0{n}:{i:02d}",
                        "open": 100, "high": 101, "low": 99, "close": 100,
                        "volume": 1000, "delta": 10,
                    })
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Force final flush
        adapter._flush_ticks()

        assert not errors, f"Errors during concurrent writes: {errors}"

        # Verify all ticks were persisted
        with adapter._lock:
            cursor = adapter._conn.execute("SELECT COUNT(*) FROM ticks")
            count = cursor.fetchone()[0]
        assert count == 150, f"Expected 150 ticks, got {count}"
