"""
Tests unitaires pour la construction du prompt LLM (rag.chain).

Couvre :
  - construction des messages avec deux sections (privé + KB),
  - cas où une seule section retourne des chunks (l'autre doit être absente),
  - injection de l'historique conversationnel (5 derniers tours, troncature),
  - cas sans conversation_id / sans historique (comportement antérieur).

Exécution autonome (sans pytest) :
    cd backend && python -m tests.test_chain_prompt
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Permet l'exécution directe : `python tests/test_chain_prompt.py` depuis backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402

from rag.chain import (  # noqa: E402
    HISTORY_MESSAGE_MAX_CHARS,
    SECTION_KB_TITLE,
    SECTION_PRIVATE_TITLE,
    _build_messages,
    _build_system_prompt,
    _history_to_messages,
)


def _chunk(text: str, source: str, page: int, scope: str, **extra) -> dict:
    meta = {"source": source, "page": page, "scope": scope}
    meta.update(extra)
    return {"text": text, "metadata": meta, "rrf_score": 0.5}


class TestSystemPrompt(unittest.TestCase):
    def test_two_sections_when_both_have_chunks(self) -> None:
        prompt = _build_system_prompt(has_private=True, has_kb=True)
        self.assertIn(SECTION_PRIVATE_TITLE, prompt)
        self.assertIn(SECTION_KB_TITLE, prompt)
        self.assertIn("deux sections", prompt)

    def test_sirh_business_context_present(self) -> None:
        """Le system prompt doit fixer le contexte métier SIRH."""
        for has_private, has_kb in [(True, True), (True, False), (False, True)]:
            prompt = _build_system_prompt(has_private=has_private, has_kb=has_kb)
            self.assertIn("SIRH", prompt)
            # Mentions clés du contexte métier (paie / DSN / droit du travail).
            self.assertIn("paie", prompt)
            self.assertIn("DSN", prompt)

    def test_only_private_section(self) -> None:
        prompt = _build_system_prompt(has_private=True, has_kb=False)
        self.assertIn(SECTION_PRIVATE_TITLE, prompt)
        self.assertNotIn(SECTION_KB_TITLE, prompt)
        # La consigne doit explicitement interdire d'inventer la section absente.
        self.assertIn("N'invente PAS", prompt)

    def test_only_kb_section(self) -> None:
        prompt = _build_system_prompt(has_private=False, has_kb=True)
        self.assertIn(SECTION_KB_TITLE, prompt)
        self.assertNotIn(SECTION_PRIVATE_TITLE, prompt)

    def test_ambiguity_handling_instructions_present(self) -> None:
        """Le system prompt doit instruire le LLM sur la gestion des questions ambiguës."""
        for has_private, has_kb in [(True, True), (True, False), (False, True)]:
            prompt = _build_system_prompt(has_private=has_private, has_kb=has_kb)
            lower = prompt.lower()
            # Présence de l'intention « clarification / précision / ambiguïté ».
            self.assertTrue(
                ("ambig" in lower) and ("clarif" in lower or "précision" in lower),
                "Le prompt doit mentionner la gestion des questions ambiguës "
                "(mots-clés : ambig + clarif/précision).",
            )
            # Préfixe imposé pour la question de clarification.
            self.assertIn("Précision nécessaire", prompt)
            # Doit mentionner explicitement l'usage du contexte conversationnel.
            self.assertTrue(
                "contexte conversationnel" in lower or "échanges précédents" in lower,
                "Le prompt doit indiquer d'utiliser l'historique conversationnel "
                "avant de redemander une précision.",
            )
            # Doit interdire les puces et listes multiples dans la clarification.
            self.assertIn("une seule question", lower)


class TestBuildMessages(unittest.TestCase):
    def test_both_collections_produce_dual_sections(self) -> None:
        priv = [_chunk("contenu privé", "rapport.pdf", 3, "private")]
        kb = [_chunk("contenu public", "boss.gouv.fr", 1, "kb",
                     url_canonique="https://boss.gouv.fr/x")]
        msgs = _build_messages("Quelle est la règle ?", priv, kb)

        self.assertEqual(len(msgs), 2)  # system + human
        self.assertIsInstance(msgs[0], SystemMessage)
        self.assertIsInstance(msgs[1], HumanMessage)

        sys_content = msgs[0].content
        # Les deux titres doivent être mentionnés dans la consigne.
        self.assertIn(SECTION_PRIVATE_TITLE, sys_content)
        self.assertIn(SECTION_KB_TITLE, sys_content)
        # Les deux blocs de contexte doivent être présents.
        self.assertIn("Chunks privés", sys_content)
        self.assertIn("Chunks publics", sys_content)
        self.assertIn("[rapport.pdf p.3]", sys_content)
        self.assertIn("[KB — boss.gouv.fr p.1]", sys_content)
        self.assertIn("https://boss.gouv.fr/x", sys_content)
        self.assertEqual(msgs[1].content, "Quelle est la règle ?")

    def test_private_only_omits_kb_section(self) -> None:
        priv = [_chunk("X", "doc.pdf", 1, "private")]
        msgs = _build_messages("q?", priv, [])

        sys_content = msgs[0].content
        self.assertIn(SECTION_PRIVATE_TITLE, sys_content)
        self.assertNotIn(SECTION_KB_TITLE, sys_content)
        self.assertIn("Chunks privés", sys_content)
        self.assertNotIn("Chunks publics", sys_content)

    def test_kb_only_omits_private_section(self) -> None:
        kb = [_chunk("Y", "service-public.fr", 2, "kb")]
        msgs = _build_messages("q?", [], kb)

        sys_content = msgs[0].content
        self.assertIn(SECTION_KB_TITLE, sys_content)
        self.assertNotIn(SECTION_PRIVATE_TITLE, sys_content)
        self.assertIn("Chunks publics", sys_content)
        self.assertNotIn("Chunks privés", sys_content)

    def test_history_inserted_between_system_and_question(self) -> None:
        priv = [_chunk("X", "doc.pdf", 1, "private")]
        history = [
            {"role": "user", "content": "première question"},
            {"role": "assistant", "content": "première réponse"},
            {"role": "user", "content": "deuxième question"},
            {"role": "assistant", "content": "deuxième réponse"},
        ]
        msgs = _build_messages("q3?", priv, [], history=history)

        # system + 4 history + human = 6
        self.assertEqual(len(msgs), 6)
        self.assertIsInstance(msgs[0], SystemMessage)
        self.assertIsInstance(msgs[1], HumanMessage)
        self.assertEqual(msgs[1].content, "première question")
        self.assertIsInstance(msgs[2], AIMessage)
        self.assertIsInstance(msgs[5], HumanMessage)
        self.assertEqual(msgs[5].content, "q3?")


class TestHistoryToMessages(unittest.TestCase):
    def test_no_history_returns_empty(self) -> None:
        self.assertEqual(_history_to_messages(None), [])
        self.assertEqual(_history_to_messages([]), [])

    def test_keeps_only_last_5_turns(self) -> None:
        # 7 tours = 14 messages
        history = []
        for i in range(7):
            history.append({"role": "user", "content": f"q{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        msgs = _history_to_messages(history, max_turns=5)
        # Doit garder 10 messages (5 tours).
        self.assertEqual(len(msgs), 10)
        # Le premier conservé doit être la question du 3e tour (indice 2).
        self.assertEqual(msgs[0].content, "q2")
        self.assertEqual(msgs[-1].content, "a6")

    def test_truncates_long_messages(self) -> None:
        long_content = "x" * (HISTORY_MESSAGE_MAX_CHARS + 500)
        history = [{"role": "assistant", "content": long_content}]
        msgs = _history_to_messages(history)
        self.assertEqual(len(msgs), 1)
        # Le message tronqué se termine par l'ellipse.
        self.assertTrue(msgs[0].content.endswith("…"))
        self.assertLessEqual(len(msgs[0].content), HISTORY_MESSAGE_MAX_CHARS + 1)

    def test_skips_empty_and_unknown_roles(self) -> None:
        history = [
            {"role": "user", "content": "  "},  # vide -> ignoré
            {"role": "system", "content": "ignored"},  # rôle non géré
            {"role": "user", "content": "ok"},
        ]
        msgs = _history_to_messages(history)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
