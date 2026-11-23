import os
import json
import re
import logging
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass

try:
    import google.generativeai as genai
except ImportError:
    genai = None
    logger = logging.getLogger(__name__)
    logger.warning("google-generativeai not installed. EntityGlossaryService will not work.")

logger = logging.getLogger(__name__)


@dataclass
class GlossaryEntry:
    source_term: str
    policy: str  # TRANSLATE | KEEP_ORIGINAL | ROMANIZE_EN
    display_name: str
    tts_phonetic_km: str
    entity_type: str  # person, place, brand, tech, other


class EntityGlossaryService:
    """
    Pre-translation episode glossary extractor using Gemini Flash.
    Token-locked translation guardrail with regex verification.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self._model = None

    def _get_model(self):
        if genai is None:
            return None
        if self._model is None and self.api_key:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
        return self._model

    def extract_glossary(self, full_transcript: str,
                         progress_callback: Optional[Callable[[float, str], None]] = None) -> List[GlossaryEntry]:
        """
        Extract proper nouns, names, brands, tech terms from full transcript.
        Single pass over entire transcript before translation.
        """
        model = self._get_model()
        if not model:
            logger.warning("Gemini not configured, returning empty glossary")
            return []

        if progress_callback:
            progress_callback(0.2, "Extracting entities with Gemini...")

        prompt = f"""Analyze this Chinese/English drama transcript and extract ALL proper nouns, character names,
brand names, tech terms, and untranslatable terms that should NOT be translated to Khmer.

Transcript:
{full_transcript[:50000]}

For each unique entity found, classify with policy:
- TRANSLATE: Standard terms with natural Khmer equivalents (e.g., 总裁 -> ប្រធានក្រុមហ៊ុន)
- KEEP_ORIGINAL: Untranslatable names, brands, terms left in English/original (e.g., Kawasaki H2, VIP, iPhone)
- ROMANIZE_EN: Non-Latin names (Chinese/Japanese/Korean) with no Khmer equivalent -> clean English (e.g., 李明 -> Li Ming)

Also provide phonetic Khmer approximation for KEEP_ORIGINAL/ROMANIZE_EN entries
(e.g., "Kawasaki H2" -> "កាវ៉ាសាគី អេច ពីរ").

Return strict JSON array:
[
  {{"source_term": "总裁", "policy": "TRANSLATE", "display_name": "ប្រធានក្រុមហ៊ុន", "tts_phonetic_km": "", "entity_type": "title"}},
  {{"source_term": "Kawasaki H2", "policy": "KEEP_ORIGINAL", "display_name": "Kawasaki H2", "tts_phonetic_km": "កាវ៉ាសាគី អេច ពីរ", "entity_type": "brand"}},
  ...
]"""

        try:
            response = model.generate_content(prompt)
            # Parse JSON from response
            text = response.text.strip()
            # Extract JSON array from markdown if present
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0]
            elif '```' in text:
                text = text.split('```')[1].split('```')[0]

            data = json.loads(text)

            entries = []
            for item in data:
                entries.append(GlossaryEntry(
                    source_term=item['source_term'],
                    policy=item['policy'],
                    display_name=item['display_name'],
                    tts_phonetic_km=item.get('tts_phonetic_km', ''),
                    entity_type=item.get('entity_type', 'other')
                ))

            if progress_callback:
                progress_callback(1.0, f"Extracted {len(entries)} glossary entries")

            return entries
        except Exception as e:
            logger.error(f"Glossary extraction failed: {e}")
            if progress_callback:
                progress_callback(1.0, f"Error: {e}")
            return []

    def build_token_map(self, entries: List[GlossaryEntry]) -> Dict[str, str]:
        """Build token -> source_term mapping for locked translation.
        The token_map maps token -> source_term (what appears in source text).
        display_name is used for unlocking and TTS segments.
        """
        token_map = {}
        for i, entry in enumerate(entries):
            if entry.policy in ('KEEP_ORIGINAL', 'ROMANIZE_EN'):
                token = f"[[ENT_{i:03d}]]"  # Use 3 digits to support 1000+ entities
                token_map[token] = entry.source_term
        return token_map

    def get_display_map(self, entries: List[GlossaryEntry]) -> Dict[str, str]:
        """Build token -> display_name mapping for unlocking and TTS."""
        display_map = {}
        for i, entry in enumerate(entries):
            if entry.policy in ('KEEP_ORIGINAL', 'ROMANIZE_EN'):
                token = f"[[ENT_{i:03d}]]"  # Use 3 digits to support 1000+ entities
                display_map[token] = entry.display_name
        return display_map

    def lock_tokens(self, text: str, token_map: Dict[str, str]) -> str:
        """
        Replace locked terms with immutable tokens in text.
        token_map: token -> source_term (what to find in text)
        Uses exact string replacement or non-word boundary matching.
        """
        result = text
        # Sort by length descending to handle overlapping terms
        sorted_terms = sorted(token_map.items(), key=lambda x: len(x[1]), reverse=True)
        for token, term in sorted_terms:
            if term in result:
                result = result.replace(term, token)
        return result

    def unlock_tokens(self, text: str, display_map: Dict[str, str]) -> str:
        """Restore locked terms from tokens to display_name.
        display_map: token -> display_name (what to show in output)
        """
        result = text
        for token, term in display_map.items():
            result = result.replace(token, term)
        return result

    def verify_tokens(self, text: str, token_map: Dict[str, str]) -> bool:
        """Verify all tokens survived translation."""
        for token in token_map.keys():
            if token not in text:
                return False
        return True

    def build_tts_segments(self, display_text: str, entries: List[GlossaryEntry]) -> List[Dict]:
        """
        Build tts_segments array from display_text and glossary.
        Segments alternate between Khmer and locked terms with phonetic fallbacks.
        """
        # Use display_name for token matching in display_text
        display_map = self.get_display_map(entries)
        segments = []

        # Split by tokens in the display_text
        # Use regex that handles multi-digit entity indices
        parts = re.split(r'(\[\[ENT_\d+\]\])', display_text)

        for part in parts:
            if not part:
                continue
            if part.startswith('[[ENT_') and part.endswith(']]'):
                # Locked term - look up display_name
                token = part
                # Extract index using regex to handle 1-3+ digits
                match = re.match(r'\[\[ENT_(\d+)\]\]', part)
                if match:
                    entry_idx = int(match.group(1))
                    if entry_idx < len(entries):
                        entry = entries[entry_idx]
                        segments.append({
                            "text": entry.display_name,
                            "lang": "en",
                            "phonetic_km": entry.tts_phonetic_km
                        })
                    else:
                        # Fallback for malformed token
                        segments.append({
                            "text": part,
                            "lang": "en",
                            "phonetic_km": ""
                        })
            else:
                # Khmer text
                if part.strip():
                    segments.append({
                        "text": part.strip(),
                        "lang": "km",
                        "phonetic_km": ""
                    })

        return segments


class TranslationGuardrail:
    """
    Token-locked translation with regex verification and auto-retry.
    """

    def __init__(self, glossary_service: EntityGlossaryService):
        self.glossary = glossary_service

    def translate_with_guardrail(self, source_text: str, entries: List[GlossaryEntry],
                                 target_lang: str = "Khmer",
                                 context: str = "drama dialogue",
                                 progress_callback: Optional[Callable[[float, str], None]] = None,
                                 max_retries: int = 1) -> Dict:
        """
        Translate text while preserving locked entities.
        Returns: {display_text, tts_segments, success}
        """
        token_map = self.glossary.build_token_map(entries)  # token -> source_term
        display_map = self.glossary.get_display_map(entries)  # token -> display_name

        # Lock tokens in source (replace source_term with tokens)
        locked_text = self.glossary.lock_tokens(source_text, token_map)

        # Build translation prompt
        glossary_context = "\n".join([
            f"- {e.source_term} -> {e.display_name} ({e.policy})"
            for e in entries if e.policy != 'TRANSLATE'
        ])

        model = self.glossary._get_model()
        if not model:
            return {
                "display_text": source_text,
                "tts_segments": [{"text": source_text, "lang": "km", "phonetic_km": ""}],
                "success": False,
                "error": "Gemini not configured"
            }

        prompt = f"""Translate the following drama dialogue to natural spoken {target_lang}.
Context: {context}

IMPORTANT: The text contains LOCKED TOKENS like [[ENT_000]] that MUST remain EXACTLY UNCHANGED.
Do not translate, modify, or reorder these tokens. Build natural {target_lang} grammar around them.

Locked terms reference:
{glossary_context}

Text to translate:
{locked_text}

Return ONLY the translated text with tokens preserved."""

        for attempt in range(max_retries + 1):
            if progress_callback:
                progress_callback(0.3 + 0.4 * attempt, f"Translating (attempt {attempt + 1})...")

            try:
                response = model.generate_content(prompt)
                translated = response.text.strip()

                # Verify all tokens survived
                if self.glossary.verify_tokens(translated, token_map):
                    # Success - unlock tokens to display_name
                    display_text = self.glossary.unlock_tokens(translated, display_map)
                    # Build TTS segments from LOCKED translated text (which still has tokens)
                    tts_segments = self.glossary.build_tts_segments(translated, entries)

                    if progress_callback:
                        progress_callback(1.0, "Translation complete")

                    return {
                        "display_text": display_text,
                        "tts_segments": tts_segments,
                        "success": True
                    }
                else:
                    logger.warning(f"Token verification failed on attempt {attempt + 1}")
                    if attempt == max_retries:
                        # Last attempt failed - force restore
                        display_text = self.glossary.unlock_tokens(translated, display_map)
                        tts_segments = self.glossary.build_tts_segments(translated, entries)
                        return {
                            "display_text": display_text,
                            "tts_segments": tts_segments,
                            "success": False,
                            "error": "Token verification failed after retries"
                        }
            except Exception as e:
                logger.error(f"Translation error: {e}")
                if attempt == max_retries:
                    return {
                        "display_text": source_text,
                        "tts_segments": [{"text": source_text, "lang": "km", "phonetic_km": ""}],
                        "success": False,
                        "error": str(e)
                    }

        return {
            "display_text": source_text,
            "tts_segments": [{"text": source_text, "lang": "km", "phonetic_km": ""}],
            "success": False,
            "error": "Max retries exceeded"
        }


def extract_glossary_job(transcript: str, progress_callback=None):
    """Celery task wrapper for glossary extraction."""
    service = EntityGlossaryService()
    entries = service.extract_glossary(transcript, progress_callback)
    return [e.__dict__ for e in entries]


def translate_line_job(source_text: str, glossary_entries: List[Dict], progress_callback=None):
    """Celery task wrapper for single line translation."""
    service = EntityGlossaryService()
    guardrail = TranslationGuardrail(service)
    entries = [GlossaryEntry(**e) for e in glossary_entries]
    return guardrail.translate_with_guardrail(source_text, entries, progress_callback=progress_callback)