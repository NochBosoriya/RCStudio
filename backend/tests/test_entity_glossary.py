"""
Unit tests for token-locked entity preservation (TranslationGuardrail).

Tests the core entity glossary extraction, token locking, and translation
verification.

NOTE: ``google-generativeai`` is an optional dependency that may not be
installed in the test environment; the Gemini client is mocked throughout so the
suite does not require it.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.entity_glossary_service import (
    EntityGlossaryService,
    GlossaryEntry,
    TranslationGuardrail,
)


class TestGlossaryEntry:
    """Test GlossaryEntry dataclass."""

    def test_glossary_entry_creation(self):
        entry = GlossaryEntry(
            source_term="总裁",
            policy="TRANSLATE",
            display_name="ប្រធានក្រុមហ៊ុន",
            tts_phonetic_km="",
            entity_type="title"
        )
        assert entry.source_term == "总裁"
        assert entry.policy == "TRANSLATE"
        assert entry.display_name == "ប្រធានក្រុមហ៊ុន"
        assert entry.entity_type == "title"

    def test_glossary_entry_keep_original(self):
        entry = GlossaryEntry(
            source_term="Kawasaki H2",
            policy="KEEP_ORIGINAL",
            display_name="Kawasaki H2",
            tts_phonetic_km="កាវ៉ាសាគី អេច ពីរ",
            entity_type="brand"
        )
        assert entry.policy == "KEEP_ORIGINAL"
        assert entry.tts_phonetic_km == "កាវ៉ាសាគី អេច ពីរ"

    def test_glossary_entry_romanize_en(self):
        entry = GlossaryEntry(
            source_term="李明",
            policy="ROMANIZE_EN",
            display_name="Li Ming",
            tts_phonetic_km="លី មីង",
            entity_type="person"
        )
        assert entry.policy == "ROMANIZE_EN"
        assert entry.display_name == "Li Ming"


class TestEntityGlossaryService:
    """Test EntityGlossaryService core functionality."""

    @pytest.fixture
    def service(self):
        return EntityGlossaryService(api_key="test-key")

    @pytest.fixture
    def sample_entries(self):
        return [
            GlossaryEntry("总裁", "TRANSLATE", "ប្រធានក្រុមហ៊ុន", "", "title"),
            GlossaryEntry("Kawasaki H2", "KEEP_ORIGINAL", "Kawasaki H2", "កាវ៉ាសាគី អេច ពីរ", "brand"),
            GlossaryEntry("李明", "ROMANIZE_EN", "Li Ming", "លី មីង", "person"),
            GlossaryEntry("VIP", "KEEP_ORIGINAL", "VIP", "វីអាយពី", "tech"),
        ]

    def test_build_token_map(self, service, sample_entries):
        """Test token map building for KEEP_ORIGINAL and ROMANIZE_EN entries.
        token_map maps token -> source_term (what appears in source text).

        Tokens use a 3-digit zero-padded index (e.g. ``[[ENT_001]]``) so that
        indices >= 1000 are unambiguous.
        """
        token_map = service.build_token_map(sample_entries)

        # KEEP_ORIGINAL / ROMANIZE_EN entries are locked; TRANSLATE is not.
        # With the sample list, the locked entries sit at indices 1..3.
        assert "[[ENT_001]]" in token_map  # Kawasaki H2 (index 1)
        assert "[[ENT_002]]" in token_map  # 李明 (index 2)
        assert "[[ENT_003]]" in token_map  # VIP (index 3)
        assert "[[ENT_000]]" not in token_map  # TRANSLATE entries not locked

        assert token_map["[[ENT_001]]"] == "Kawasaki H2"  # source_term
        assert token_map["[[ENT_002]]"] == "李明"  # source_term (Chinese)
        assert token_map["[[ENT_003]]"] == "VIP"

    def test_lock_tokens(self, service, sample_entries):
        """Test locking tokens in text."""
        token_map = service.build_token_map(sample_entries)
        text = "总裁驾驶Kawasaki H2去见李明，他是VIP"

        locked = service.lock_tokens(text, token_map)

        # TRANSLATE entry should NOT be locked
        assert "总裁" in locked
        # KEEP_ORIGINAL/ROMANIZE_EN should be locked
        assert "[[ENT_001]]" in locked  # Kawasaki H2
        assert "[[ENT_002]]" in locked  # Li Ming
        assert "[[ENT_003]]" in locked  # VIP
        assert "Kawasaki H2" not in locked
        assert "李明" not in locked
        assert "VIP" not in locked

    def test_lock_tokens_overlapping(self, service):
        """Test token locking with overlapping terms (longer first)."""
        entries = [
            GlossaryEntry("Kawasaki", "KEEP_ORIGINAL", "Kawasaki", "កាវ៉ាសាគី", "brand"),
            GlossaryEntry("Kawasaki H2", "KEEP_ORIGINAL", "Kawasaki H2", "កាវ៉ាសាគី អេច ពីរ", "brand"),
        ]
        token_map = service.build_token_map(entries)
        text = "Kawasaki H2 is a Kawasaki bike"

        locked = service.lock_tokens(text, token_map)

        # Longer term should be matched first (Kawasaki H2)
        assert "[[ENT_001]]" in locked  # Kawasaki H2
        # The standalone "Kawasaki" in "a Kawasaki bike" should also be locked
        assert "[[ENT_000]]" in locked  # standalone Kawasaki
        # Should not have partial overlap like "Kawasaki" inside "Kawasaki H2"
        assert "Kawasaki H2" not in locked

    def test_unlock_tokens(self, service, sample_entries):
        """Test unlocking tokens back to display_name."""
        display_map = service.get_display_map(sample_entries)
        locked = "总裁驾驶[[ENT_001]]去见[[ENT_002]]，他是[[ENT_003]]"

        unlocked = service.unlock_tokens(locked, display_map)

        assert "Kawasaki H2" in unlocked
        assert "Li Ming" in unlocked
        assert "VIP" in unlocked
        assert "[[ENT_001]]" not in unlocked
        assert "[[ENT_002]]" not in unlocked
        assert "[[ENT_003]]" not in unlocked

    def test_verify_tokens_success(self, service, sample_entries):
        """Test token verification when all tokens present."""
        token_map = service.build_token_map(sample_entries)
        text = "总裁驾驶[[ENT_001]]去见[[ENT_002]]，他是[[ENT_003]]"

        assert service.verify_tokens(text, token_map) is True

    def test_verify_tokens_failure(self, service, sample_entries):
        """Test token verification when tokens missing."""
        token_map = service.build_token_map(sample_entries)
        text = "总裁驾驶[[ENT_001]]去见[[ENT_002]]"  # Missing VIP token

        assert service.verify_tokens(text, token_map) is False

    def test_build_tts_segments(self, service, sample_entries):
        """Test building TTS segments from display text.
        The text "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_001]]និង[[ENT_002]]"
        splits into: Khmer "ប្រធានក្រុមហ៊ុនចូលមើល" + [[ENT_001]] + Khmer "និង" + [[ENT_002]] = 4 segments
        """
        display_text = "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_001]]និង[[ENT_002]]"

        segments = service.build_tts_segments(display_text, sample_entries)

        assert len(segments) == 4
        # Khmer segment 1
        assert segments[0]["text"] == "ប្រធានក្រុមហ៊ុនចូលមើល"
        assert segments[0]["lang"] == "km"
        # Locked term 1 (Kawasaki H2) - index 1
        assert segments[1]["text"] == "Kawasaki H2"
        assert segments[1]["lang"] == "en"
        assert segments[1]["phonetic_km"] == "កាវ៉ាសាគី អេច ពីរ"
        # Khmer segment 2 ("និង" = "and")
        assert segments[2]["text"] == "និង"
        assert segments[2]["lang"] == "km"
        # Locked term 2 (Li Ming) - index 2
        assert segments[3]["text"] == "Li Ming"
        assert segments[3]["lang"] == "en"
        assert segments[3]["phonetic_km"] == "លី មីង"

    def test_build_tts_segments_no_locked_terms(self, service):
        """Test TTS segments with no locked terms."""
        entries = [
            GlossaryEntry("总裁", "TRANSLATE", "ប្រធានក្រុមហ៊ុន", "", "title"),
        ]
        display_text = "ប្រធានក្រុមហ៊ុនមកដល់ហើយ"

        segments = service.build_tts_segments(display_text, entries)

        assert len(segments) == 1
        assert segments[0]["lang"] == "km"
        assert segments[0]["text"] == display_text


class TestTranslationGuardrail:
    """Test TranslationGuardrail with mocked Gemini."""

    @pytest.fixture
    def mock_model(self):
        model = Mock()
        model.generate_content = Mock()
        return model

    @pytest.fixture
    def service(self, mock_model):
        with patch('app.services.entity_glossary_service.genai') as mock_genai:
            mock_genai.GenerativeModel.return_value = mock_model
            service = EntityGlossaryService(api_key="test-key")
            service._model = mock_model
            return service

    @pytest.fixture
    def guardrail(self, service):
        return TranslationGuardrail(service)

    @pytest.fixture
    def entries(self):
        return [
            GlossaryEntry("Kawasaki H2", "KEEP_ORIGINAL", "Kawasaki H2", "កាវ៉ាសាគី អេច ពីរ", "brand"),
            GlossaryEntry("李明", "ROMANIZE_EN", "Li Ming", "លី មីង", "person"),
        ]

    def test_translate_preserves_tokens(self, guardrail, entries, mock_model):
        """Test translation preserves locked tokens.
        Note: token indices are based on position in full entries list.
        entries[0] = Kawasaki H2 -> [[ENT_000]]
        entries[1] = 李明 -> [[ENT_001]]
        The Khmer translation "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_000]]និង[[ENT_001]]"
        splits into: Khmer + [[ENT_000]] + Khmer "និង" + [[ENT_001]] = 4 segments
        """
        # Mock response with tokens preserved (using correct indices 00 and 01)
        mock_response = Mock()
        mock_response.text = "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_000]]និង[[ENT_001]]"
        mock_model.generate_content.return_value = mock_response

        source = "总裁来看Kawasaki H2和李明"
        result = guardrail.translate_with_guardrail(source, entries, max_retries=0)

        assert result["success"] is True
        assert "Kawasaki H2" in result["display_text"]
        assert "Li Ming" in result["display_text"]
        assert "[[ENT_000]]" not in result["display_text"]
        assert "[[ENT_001]]" not in result["display_text"]

        # Verify TTS segments built correctly from locked translated text
        assert len(result["tts_segments"]) == 4
        # Khmer segment 1
        assert result["tts_segments"][0]["text"] == "ប្រធានក្រុមហ៊ុនចូលមើល"
        assert result["tts_segments"][0]["lang"] == "km"
        # Locked term 1 (Kawasaki H2)
        assert result["tts_segments"][1]["text"] == "Kawasaki H2"
        assert result["tts_segments"][1]["lang"] == "en"
        # Khmer segment 2 ("និង" = "and")
        assert result["tts_segments"][2]["text"] == "និង"
        assert result["tts_segments"][2]["lang"] == "km"
        # Locked term 2 (Li Ming)
        assert result["tts_segments"][3]["text"] == "Li Ming"
        assert result["tts_segments"][3]["lang"] == "en"

    def test_translate_token_verification_failure_retry(self, guardrail, entries, mock_model):
        """Test auto-retry when token verification fails."""
        # First call: missing token
        # Second call: tokens preserved
        mock_response1 = Mock()
        mock_response1.text = "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_000]]"  # Missing [[ENT_001]]

        mock_response2 = Mock()
        mock_response2.text = "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_000]]និង[[ENT_001]]"

        mock_model.generate_content.side_effect = [mock_response1, mock_response2]

        source = "总裁来看Kawasaki H2和李明"
        result = guardrail.translate_with_guardrail(source, entries, max_retries=1)

        assert result["success"] is True
        assert mock_model.generate_content.call_count == 2

    def test_translate_max_retries_exceeded(self, guardrail, entries, mock_model):
        """Test failure after max retries."""
        # Always return text with missing token
        mock_response = Mock()
        mock_response.text = "ប្រធានក្រុមហ៊ុនចូលមើល[[ENT_000]]"  # Missing [[ENT_001]]
        mock_model.generate_content.return_value = mock_response

        source = "总裁来看Kawasaki H2和李明"
        result = guardrail.translate_with_guardrail(source, entries, max_retries=1)

        assert result["success"] is False
        assert "Token verification failed" in result["error"]
        assert mock_model.generate_content.call_count == 2  # Initial + 1 retry

    def test_translate_no_gemini(self, guardrail, entries):
        """Test fallback when Gemini not configured."""
        guardrail.glossary._model = None
        guardrail.glossary.api_key = None

        source = "总裁来看Kawasaki H2"
        result = guardrail.translate_with_guardrail(source, entries)

        assert result["success"] is False
        assert "Gemini not configured" in result["error"]

    def test_translate_exception_handling(self, guardrail, entries, mock_model):
        """Test exception handling during translation."""
        mock_model.generate_content.side_effect = Exception("API Error")

        source = "总裁来看Kawasaki H2"
        result = guardrail.translate_with_guardrail(source, entries, max_retries=0)

        assert result["success"] is False
        assert "API Error" in result["error"]


class TestURLRouting:
    """Test FastAPI URL routing."""

    def test_download_routes(self):
        """Test download router has all expected routes."""
        from app.routers.download import router

        routes = [route.path for route in router.routes]
        expected = [
            "/api/download/info",
            "/api/download/start",
            "/api/download/job/{job_id}",
            "/api/download/hongguo/parse",
            "/api/download/project/{project_id}/assets",
        ]

        for exp in expected:
            assert exp in routes, f"Missing route: {exp}"

    def test_dubbing_routes(self):
        """Test dubbing router has all expected routes."""
        from app.routers.dubbing import router

        routes = [route.path for route in router.routes]
        expected = [
            "/api/dubbing/separate",
            "/api/dubbing/transcribe",
            "/api/dubbing/diarize",
            "/api/dubbing/detect-characters",
            "/api/dubbing/project/{project_id}/lines",
            "/api/dubbing/project/{project_id}/characters",
            "/api/dubbing/line/{line_id}",
        ]

        for exp in expected:
            assert exp in routes, f"Missing route: {exp}"

    def test_all_registered_routes(self):
        """Test all routes are registered in main app."""
        from app.main import app

        # Get all routes including those from included routers
        all_routes = []
        for route in app.routes:
            if hasattr(route, 'path') and not hasattr(route, 'original_router'):
                all_routes.append(route.path)
            elif hasattr(route, 'original_router'):
                # Included router - get routes from the original router
                for r in route.original_router.routes:
                    all_routes.append(r.path)

        routes = all_routes

        # Check core routes
        assert "/" in routes
        assert "/health" in routes

        # Check download routes
        download_routes = [r for r in routes if r.startswith("/api/download")]
        assert len(download_routes) == 5

        # Check dubbing routes
        dubbing_routes = [r for r in routes if r.startswith("/api/dubbing")]
        assert len(dubbing_routes) == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
