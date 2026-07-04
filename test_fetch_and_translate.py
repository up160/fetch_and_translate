"""
Unit tests for the translation layer of fetch_and_translate.py.

These run fully offline: every backend call is replaced by a fake "completer",
so no network, no Ollama and no Anthropic credits are needed. They cover the
parts that actually broke or were reworked — backend selection/fallback, tolerant
JSON parsing of model output, and the chunk translator's English-fallback safety.

Run:  python -m unittest test_fetch_and_translate -v
"""
import json
import unittest
from unittest import mock

import fetch_and_translate as fat


class ParseTranslationsTests(unittest.TestCase):
    def test_plain_json_array(self):
        raw = '[{"id": "a", "title_es": "Hola", "summary_es": "Mundo"}]'
        self.assertEqual(fat._parse_translations(raw), [
            {"id": "a", "title_es": "Hola", "summary_es": "Mundo"}
        ])

    def test_code_fenced_json(self):
        raw = '```json\n[{"id": "a", "title_es": "Hola"}]\n```'
        self.assertEqual(fat._parse_translations(raw), [{"id": "a", "title_es": "Hola"}])

    def test_object_wrapper_from_local_models(self):
        # format=json Ollama models often wrap the array in a key.
        raw = '{"items": [{"id": "a", "title_es": "Hola"}]}'
        self.assertEqual(fat._parse_translations(raw), [{"id": "a", "title_es": "Hola"}])

    def test_prose_around_array_is_stripped(self):
        raw = 'Sure, here you go: [{"id": "a", "title_es": "Hola"}] hope that helps'
        self.assertEqual(fat._parse_translations(raw), [{"id": "a", "title_es": "Hola"}])

    def test_single_object_becomes_list(self):
        raw = '{"id": "a", "title_es": "Hola", "summary_es": "x"}'
        self.assertEqual(fat._parse_translations(raw),
                         [{"id": "a", "title_es": "Hola", "summary_es": "x"}])


class BuildCompleterTests(unittest.TestCase):
    """Backend ordering is the crux of the graceful-fallback behaviour."""

    def _build(self, backend, ollama_enabled, api_key):
        with mock.patch.object(fat, "TRANSLATE_BACKEND", backend), \
             mock.patch.object(fat, "OLLAMA_ENABLED", ollama_enabled), \
             mock.patch.object(fat, "ANTHROPIC_API_KEY", api_key), \
             mock.patch.object(fat.anthropic, "Anthropic", return_value=object()):
            return fat.build_completer()

    def test_claude_only(self):
        _, names = self._build("claude", False, "sk-test")
        self.assertEqual(names, ["claude"])

    def test_claude_without_key_has_no_backend(self):
        completer, names = self._build("claude", False, None)
        self.assertIsNone(completer)
        self.assertEqual(names, [])

    def test_ollama_primary_claude_fallback(self):
        _, names = self._build("ollama", True, "sk-test")
        self.assertEqual(names, ["ollama", "claude"])

    def test_ollama_without_key_is_ollama_only(self):
        _, names = self._build("ollama", True, None)
        self.assertEqual(names, ["ollama"])

    def test_auto_with_ollama_host_prefers_ollama(self):
        _, names = self._build("auto", True, "sk-test")
        self.assertEqual(names, ["ollama", "claude"])

    def test_auto_without_ollama_host_is_claude(self):
        _, names = self._build("auto", False, "sk-test")
        self.assertEqual(names, ["claude"])


class ChainedCompleterTests(unittest.TestCase):
    def test_primary_success_short_circuits(self):
        primary = mock.Mock(return_value="primary-out")
        secondary = mock.Mock(return_value="secondary-out")
        complete = fat._chained_completer([("a", primary), ("b", secondary)])
        self.assertEqual(complete("p"), "primary-out")
        secondary.assert_not_called()

    def test_falls_through_to_secondary_on_failure(self):
        primary = mock.Mock(side_effect=RuntimeError("credits too low"))
        secondary = mock.Mock(return_value="secondary-out")
        complete = fat._chained_completer([("a", primary), ("b", secondary)])
        self.assertEqual(complete("p"), "secondary-out")

    def test_all_failing_raises_last_error(self):
        primary = mock.Mock(side_effect=RuntimeError("down"))
        secondary = mock.Mock(side_effect=ValueError("also down"))
        complete = fat._chained_completer([("a", primary), ("b", secondary)])
        with self.assertRaises(ValueError):
            complete("p")


def _items(n):
    return [
        {"id": f"id{i}", "title_en": f"Title {i}", "summary_en": f"Summary {i}"}
        for i in range(n)
    ]


class TranslateChunkTests(unittest.TestCase):
    def test_matches_by_id_and_sets_spanish(self):
        chunk = _items(2)

        def complete(_prompt):
            return json.dumps([
                {"id": "id0", "title_es": "Titulo 0", "summary_es": "Resumen 0"},
                {"id": "id1", "title_es": "Titulo 1", "summary_es": "Resumen 1"},
            ])

        changed = fat._translate_chunk(chunk, complete)
        self.assertEqual(changed, 2)
        self.assertEqual(chunk[0]["title_es"], "Titulo 0")
        self.assertEqual(chunk[1]["summary_es"], "Resumen 1")

    def test_accepts_input_key_names(self):
        # Models sometimes echo the translation under "title"/"summary".
        chunk = _items(1)

        def complete(_prompt):
            return json.dumps([{"id": "id0", "title": "Titulo", "summary": "Resumen"}])

        fat._translate_chunk(chunk, complete)
        self.assertEqual(chunk[0]["title_es"], "Titulo")
        self.assertEqual(chunk[0]["summary_es"], "Resumen")

    def test_positional_fallback_when_ids_missing(self):
        chunk = _items(1)

        def complete(_prompt):
            return json.dumps([{"title_es": "Titulo", "summary_es": "Resumen"}])

        fat._translate_chunk(chunk, complete)
        self.assertEqual(chunk[0]["title_es"], "Titulo")

    def test_empty_title_falls_back_to_english(self):
        chunk = _items(1)

        def complete(_prompt):
            return json.dumps([{"id": "id0", "title_es": "", "summary_es": "Resumen"}])

        fat._translate_chunk(chunk, complete)
        self.assertEqual(chunk[0]["title_es"], "Title 0")   # English kept
        self.assertEqual(chunk[0]["summary_es"], "Resumen")


class TranslateBatchTests(unittest.TestCase):
    def test_full_translation_marks_every_item(self):
        items = _items(10)   # spans two chunks (CHUNK_SIZE=8)

        def complete(prompt):
            payload = json.loads(prompt[prompt.index("["):])
            return json.dumps([
                {"id": obj["id"], "title_es": "ES " + obj["title"],
                 "summary_es": "ES " + obj["summary"]}
                for obj in payload
            ])

        result = fat.translate_batch(items, complete)
        self.assertTrue(all(i["title_es"].startswith("ES ") for i in result))

    def test_backend_failure_leaves_english_not_crash(self):
        items = _items(3)

        def complete(_prompt):
            raise RuntimeError("all backends down")

        # Must not raise — the site degrades to English rather than breaking.
        result = fat.translate_batch(items, complete)
        for i in result:
            self.assertEqual(i["title_es"], i["title_en"])
            self.assertEqual(i["summary_es"], i["summary_en"])


if __name__ == "__main__":
    unittest.main()
