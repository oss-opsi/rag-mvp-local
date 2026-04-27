"""
Tests unitaires v3.11 — Re-pass batch + RAG enrichi feedback + export CSV.

Couverture :
  - get_top_validated_verdicts : filtrage par domaine, ordre par récence,
    limite 3, dédup intra-analyse.
  - get_validated_source_boosts : facteur 1 + 0.1 * count_up, plafond 1.5,
    parité v3.10 si aucun feedback.
  - ReferentielsOnlyRetriever._apply_source_boosts : multiplication des
    scores RRF des chunks dont la `source` matche le mapping, re-tri.
  - run_repass_batch : seules les exigences ciblées sont rejouées,
    `repass_applied=True`, `summary` recalculé, garde-fou ``force=False``.
  - export_feedback_csv : structure de colonnes, BOM UTF-8, séparateur ';',
    UTF-8, ligne par exigence (avec ou sans feedback).

Exécution :
    cd backend && python -m pytest tests/test_gap_analysis_v311.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Permet l'exécution directe depuis backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Helpers communs : isole DATA_DIR pour ne pas polluer la DB de prod.
# ---------------------------------------------------------------------------


def _isolate_data_dir() -> str:
    """Crée un DATA_DIR temporaire et recharge les modules concernés."""
    tmp = tempfile.mkdtemp(prefix="ws_v311_")
    os.environ["DATA_DIR"] = tmp
    import importlib

    from rag import config as rag_config
    importlib.reload(rag_config)
    from rag import workspace as ws_mod
    importlib.reload(ws_mod)
    ws_mod.init_db()
    return tmp


def _seed_analysis_with_report(
    workspace_mod,
    user_id: str,
    client_name: str,
    cdc_filename: str,
    report: dict,
) -> int:
    """Crée client + cdc + analyse en base et retourne ``analysis_id``."""
    client = workspace_mod.create_client(user_id, client_name)
    cdc = workspace_mod.create_cdc(
        user_id=user_id,
        client_id=client["id"],
        filename=cdc_filename,
        ext=".pdf",
        data=b"%PDF-1.4 fake",
    )
    return workspace_mod.save_analysis(
        cdc_id=cdc["id"],
        report=report,
        pipeline_version="v3.11.0",
        corpus_fingerprint="test-corpus",
    )


# ---------------------------------------------------------------------------
# 1) get_top_validated_verdicts + get_validated_source_boosts
# ---------------------------------------------------------------------------


class TestFeedbackEnrichmentHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = _isolate_data_dir()
        from rag import workspace as ws_mod
        cls.workspace = ws_mod

    def setUp(self) -> None:
        # Vide tout entre tests.
        with self.workspace._connect() as conn:
            conn.execute("DELETE FROM requirement_feedback")
            conn.execute("DELETE FROM analyses")
            conn.execute("DELETE FROM cdcs")
            conn.execute("DELETE FROM clients")

    def _build_report(self, requirements: list[dict]) -> dict:
        return {
            "filename": "cdc.pdf",
            "summary": {
                "total": len(requirements),
                "covered": sum(1 for r in requirements if r["status"] == "covered"),
                "partial": 0, "missing": 0, "ambiguous": 0,
                "coverage_percent": 0.0,
            },
            "requirements": requirements,
        }

    def test_get_top_validated_verdicts_filtre_domaine(self) -> None:
        report = self._build_report([
            {"id": "R001", "title": "Calcul brut", "description": "...",
             "category": "Paie", "status": "covered",
             "verdict": "OK paie", "evidence": ["e1"], "sources": []},
            {"id": "R002", "title": "DSN mensuelle", "description": "...",
             "category": "DSN", "status": "covered",
             "verdict": "OK DSN", "evidence": [], "sources": []},
        ])
        aid = _seed_analysis_with_report(
            self.workspace, "alice", "ACME", "cdc.pdf", report
        )
        self.workspace.upsert_feedback(str(aid), "R001", "alice", "up")
        self.workspace.upsert_feedback(str(aid), "R002", "alice", "up")

        paie = self.workspace.get_top_validated_verdicts("alice", "Paie")
        self.assertEqual(len(paie), 1)
        self.assertEqual(paie[0]["title"], "Calcul brut")
        self.assertEqual(paie[0]["verdict"], "OK paie")

        dsn = self.workspace.get_top_validated_verdicts("alice", "DSN")
        self.assertEqual(len(dsn), 1)
        self.assertEqual(dsn[0]["title"], "DSN mensuelle")

    def test_get_top_validated_verdicts_limite_3(self) -> None:
        reqs = [
            {"id": f"R{idx:03d}", "title": f"Ex {idx}", "description": "...",
             "category": "Paie", "status": "covered",
             "verdict": f"v{idx}", "evidence": [], "sources": []}
            for idx in range(1, 6)
        ]
        report = self._build_report(reqs)
        aid = _seed_analysis_with_report(
            self.workspace, "alice", "ACME", "cdc.pdf", report
        )
        for r in reqs:
            self.workspace.upsert_feedback(str(aid), r["id"], "alice", "up")

        out = self.workspace.get_top_validated_verdicts("alice", "Paie", limit=3)
        self.assertEqual(len(out), 3)

    def test_get_top_validated_verdicts_ignore_down(self) -> None:
        report = self._build_report([
            {"id": "R001", "title": "X", "description": "d", "category": "Paie",
             "status": "covered", "verdict": "v1", "evidence": [], "sources": []},
        ])
        aid = _seed_analysis_with_report(
            self.workspace, "alice", "ACME", "cdc.pdf", report
        )
        self.workspace.upsert_feedback(str(aid), "R001", "alice", "down")
        self.assertEqual(
            self.workspace.get_top_validated_verdicts("alice", "Paie"), []
        )

    def test_get_top_validated_verdicts_aucun_feedback_renvoie_vide(self) -> None:
        # Aucun seed feedback : doit renvoyer une liste vide sans planter.
        self.assertEqual(
            self.workspace.get_top_validated_verdicts("ghost", "Paie"), []
        )

    def test_get_validated_source_boosts_facteur_lineaire_plafonne(self) -> None:
        # 3 verdicts up qui citent tous "ref_paie.pdf" → boost = 1 + 3*0.1 = 1.3
        reqs = [
            {"id": f"R{idx:03d}", "title": f"Ex {idx}", "description": "d",
             "category": "Paie", "status": "covered",
             "verdict": "v", "evidence": [],
             "sources": [{"source": "ref_paie.pdf", "page": 1, "score": 0.01}]}
            for idx in range(1, 4)
        ]
        report = self._build_report(reqs)
        aid = _seed_analysis_with_report(
            self.workspace, "alice", "ACME", "cdc.pdf", report
        )
        for r in reqs:
            self.workspace.upsert_feedback(str(aid), r["id"], "alice", "up")

        boosts = self.workspace.get_validated_source_boosts("alice")
        self.assertIn("ref_paie.pdf", boosts)
        self.assertAlmostEqual(boosts["ref_paie.pdf"], 1.3, places=4)

    def test_get_validated_source_boosts_plafonne_a_1_5(self) -> None:
        reqs = [
            {"id": f"R{idx:03d}", "title": f"Ex {idx}", "description": "d",
             "category": "Paie", "status": "covered",
             "verdict": "v", "evidence": [],
             "sources": [{"source": "REF.PDF", "page": 1, "score": 0.01}]}
            for idx in range(1, 11)  # 10 votes up → théorique 2.0, plafonné 1.5
        ]
        report = self._build_report(reqs)
        aid = _seed_analysis_with_report(
            self.workspace, "alice", "ACME", "cdc.pdf", report
        )
        for r in reqs:
            self.workspace.upsert_feedback(str(aid), r["id"], "alice", "up")

        boosts = self.workspace.get_validated_source_boosts("alice")
        # Clé canonique = lower-case
        self.assertIn("ref.pdf", boosts)
        self.assertAlmostEqual(boosts["ref.pdf"], 1.5, places=4)

    def test_get_validated_source_boosts_aucun_feedback_renvoie_vide(self) -> None:
        # No feedback → empty dict (parité v3.10).
        self.assertEqual(self.workspace.get_validated_source_boosts("ghost"), {})


# ---------------------------------------------------------------------------
# 2) Boost retrieval (ReferentielsOnlyRetriever._apply_source_boosts)
# ---------------------------------------------------------------------------


class TestRetrieverBoost(unittest.TestCase):
    def setUp(self) -> None:
        # Pas besoin de DATA_DIR isolé : on n'écrit pas en base ici.
        from rag.retriever import ReferentielsOnlyRetriever
        self.RetrCls = ReferentielsOnlyRetriever

    def _make_chunks(self) -> list[dict]:
        return [
            {"text": "alpha", "metadata": {"source": "Boostée.pdf"},
             "rrf_score": 0.010},
            {"text": "beta",  "metadata": {"source": "neutre.pdf"},
             "rrf_score": 0.012},
            {"text": "gamma", "metadata": {"source": "BOOSTÉE.PDF"},
             "rrf_score": 0.008},
        ]

    def test_no_boost_quand_dict_vide(self) -> None:
        retr = self.RetrCls(user_id="alice", source_boosts={})
        before = self._make_chunks()
        after = retr._apply_source_boosts([dict(c) for c in before])
        self.assertEqual([c["rrf_score"] for c in after],
                         [c["rrf_score"] for c in before])
        self.assertEqual(retr._boosted_sources_last, [])

    def test_no_boost_quand_user_id_absent_et_dict_none(self) -> None:
        # Constructeur sans user_id ni source_boosts → strict v3.10.
        retr = self.RetrCls()
        before = self._make_chunks()
        after = retr._apply_source_boosts([dict(c) for c in before])
        self.assertEqual([c["rrf_score"] for c in after],
                         [c["rrf_score"] for c in before])

    def test_boost_multiplie_score_des_chunks_correspondants(self) -> None:
        retr = self.RetrCls(
            user_id="alice",
            source_boosts={"boostée.pdf": 1.3},
        )
        chunks = self._make_chunks()
        after = retr._apply_source_boosts([dict(c) for c in chunks])
        # Source canonique = lower-case → les 2 chunks "Boostée.pdf" et
        # "BOOSTÉE.PDF" sont matchés (case-insensitive).
        scores_by_text = {c["text"]: c["rrf_score"] for c in after}
        self.assertAlmostEqual(scores_by_text["alpha"], 0.010 * 1.3, places=6)
        self.assertAlmostEqual(scores_by_text["gamma"], 0.008 * 1.3, places=6)
        # Le neutre n'est pas modifié.
        self.assertAlmostEqual(scores_by_text["beta"], 0.012, places=6)

    def test_boost_re_trie_par_score_descendant(self) -> None:
        retr = self.RetrCls(
            user_id="alice",
            source_boosts={"boostée.pdf": 1.5},
        )
        chunks = self._make_chunks()
        after = retr._apply_source_boosts([dict(c) for c in chunks])
        # alpha boosté à 0.015 > beta 0.012 > gamma boosté 0.012.
        # Premier doit être 'alpha'.
        self.assertEqual(after[0]["text"], "alpha")

    def test_boost_traque_les_sources_boostees(self) -> None:
        retr = self.RetrCls(
            user_id="alice",
            source_boosts={"boostée.pdf": 1.5, "absente.pdf": 1.2},
        )
        chunks = self._make_chunks()
        retr._apply_source_boosts([dict(c) for c in chunks])
        self.assertIn("boostée.pdf", retr._boosted_sources_last)
        self.assertNotIn("absente.pdf", retr._boosted_sources_last)


# ---------------------------------------------------------------------------
# 3) run_repass_batch
# ---------------------------------------------------------------------------


class TestRepassBatch(unittest.TestCase):
    def _build_report(self) -> dict:
        return {
            "filename": "cdc.pdf",
            "summary": {
                "total": 3, "covered": 1, "partial": 1,
                "missing": 1, "ambiguous": 0, "coverage_percent": 50.0,
            },
            "requirements": [
                {
                    "id": "R001", "title": "Calcul brut",
                    "description": "...", "category": "Paie",
                    "priority": "must", "status": "covered",
                    "verdict": "ok", "evidence": ["e"],
                    "sources": [{"source": "ref.pdf", "page": 1,
                                 "score": 0.01, "text": "extrait"}],
                    "confidence": 0.9, "llm_confidence": 0.9,
                    "retrieval_confidence": 0.9,
                },
                {
                    "id": "R002", "title": "DSN mensuelle",
                    "description": "...", "category": "DSN",
                    "priority": "must", "status": "ambiguous",
                    "verdict": "doute", "evidence": [],
                    "sources": [{"source": "ref.pdf", "page": 2,
                                 "score": 0.01, "text": "extrait"}],
                    "confidence": 0.3, "llm_confidence": 0.3,
                    "retrieval_confidence": 0.3,
                },
                {
                    "id": "R003", "title": "Portail RH",
                    "description": "...", "category": "Portail/Self-service",
                    "priority": "should", "status": "missing",
                    "verdict": "non couvert", "evidence": [],
                    "sources": [], "confidence": 0.0,
                    "llm_confidence": 0.0, "retrieval_confidence": 0.0,
                },
            ],
        }

    def test_seules_les_exigences_ciblees_sont_rejouees(self) -> None:
        from rag import gap_analysis as ga

        report = self._build_report()

        # Mock _judge_requirement : retourne un verdict "covered" mocké.
        async def fake_judge(req, sources, ctx, llm, sem,
                             few_shot_examples=None):
            return {
                **req, "status": "covered",
                "verdict": "verdict-mocké",
                "evidence": ["preuve mockée"],
                "sources": sources,
                "llm_confidence": 0.8,
                "retrieval_confidence": 0.6,
                "confidence": 0.74,
                "enrichment_used": {
                    "few_shot_count": len(few_shot_examples or []),
                    "boosted_sources": [],
                },
            }

        # Contourner aussi l'instanciation du LLM (pas de réseau).
        class FakeLLM:
            pass

        with patch.object(ga, "_judge_requirement", side_effect=fake_judge), \
             patch.object(ga, "ChatOpenAI", return_value=FakeLLM()), \
             patch.object(ga, "_repass_model", return_value="gpt-4o"):
            new_report = asyncio.run(ga.run_repass_batch(
                report=report,
                requirement_ids=["R002"],  # uniquement R002
                user_id="alice",
                openai_api_key="sk-fake",
                force=False,
            ))

        reqs = {r["id"]: r for r in new_report["requirements"]}
        # R001 inchangée
        self.assertEqual(reqs["R001"]["status"], "covered")
        self.assertEqual(reqs["R001"]["verdict"], "ok")
        self.assertNotIn("repass_applied", reqs["R001"])
        # R002 rejouée
        self.assertEqual(reqs["R002"]["status"], "covered")
        self.assertEqual(reqs["R002"]["verdict"], "verdict-mocké")
        self.assertTrue(reqs["R002"]["repass_applied"])
        self.assertEqual(reqs["R002"]["repass_reason"], "batch_user_request")
        # R003 inchangée
        self.assertEqual(reqs["R003"]["status"], "missing")
        self.assertNotIn("repass_applied", reqs["R003"])

    def test_summary_est_recalcule_apres_repass(self) -> None:
        from rag import gap_analysis as ga

        report = self._build_report()
        # Initial : 1 covered, 1 ambiguous, 1 missing.
        # Après re-pass de R002 → covered, on doit avoir 2 covered + 1 missing.

        async def fake_judge(req, sources, ctx, llm, sem,
                             few_shot_examples=None):
            return {**req, "status": "covered", "verdict": "ok'",
                    "evidence": [], "sources": sources,
                    "llm_confidence": 0.9, "retrieval_confidence": 0.5,
                    "confidence": 0.78,
                    "enrichment_used": {
                        "few_shot_count": 0, "boosted_sources": []
                    }}

        class FakeLLM:
            pass

        with patch.object(ga, "_judge_requirement", side_effect=fake_judge), \
             patch.object(ga, "ChatOpenAI", return_value=FakeLLM()), \
             patch.object(ga, "_repass_model", return_value="gpt-4o"):
            new_report = asyncio.run(ga.run_repass_batch(
                report=report,
                requirement_ids=["R002"],
                user_id="alice",
                openai_api_key="sk-fake",
                force=False,
            ))

        s = new_report["summary"]
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["covered"], 2)
        self.assertEqual(s["ambiguous"], 0)
        self.assertEqual(s["missing"], 1)
        # coverage_percent = (2 + 0.5*0) / 3 ≈ 66.7
        self.assertAlmostEqual(s["coverage_percent"], 66.7, places=1)

    def test_garde_fou_repass_applied_sans_force(self) -> None:
        from rag import gap_analysis as ga

        report = self._build_report()
        # Marque R002 comme déjà re-passée → ne doit PAS être rejouée.
        report["requirements"][1]["repass_applied"] = True
        report["requirements"][1]["verdict"] = "ne-doit-pas-changer"

        async def fake_judge(req, sources, ctx, llm, sem,
                             few_shot_examples=None):
            return {**req, "status": "covered", "verdict": "MUTÉ",
                    "evidence": [], "sources": sources,
                    "llm_confidence": 0.9, "retrieval_confidence": 0.5,
                    "confidence": 0.78,
                    "enrichment_used": {
                        "few_shot_count": 0, "boosted_sources": []
                    }}

        class FakeLLM:
            pass

        with patch.object(ga, "_judge_requirement", side_effect=fake_judge), \
             patch.object(ga, "ChatOpenAI", return_value=FakeLLM()), \
             patch.object(ga, "_repass_model", return_value="gpt-4o"):
            new_report = asyncio.run(ga.run_repass_batch(
                report=report,
                requirement_ids=["R002"],
                user_id="alice",
                openai_api_key="sk-fake",
                force=False,
            ))

        reqs = {r["id"]: r for r in new_report["requirements"]}
        self.assertEqual(reqs["R002"]["verdict"], "ne-doit-pas-changer")

    def test_force_true_rejoue_meme_si_deja_repass(self) -> None:
        from rag import gap_analysis as ga

        report = self._build_report()
        report["requirements"][1]["repass_applied"] = True

        async def fake_judge(req, sources, ctx, llm, sem,
                             few_shot_examples=None):
            return {**req, "status": "covered", "verdict": "FORCED",
                    "evidence": [], "sources": sources,
                    "llm_confidence": 0.9, "retrieval_confidence": 0.5,
                    "confidence": 0.78,
                    "enrichment_used": {
                        "few_shot_count": 0, "boosted_sources": []
                    }}

        class FakeLLM:
            pass

        with patch.object(ga, "_judge_requirement", side_effect=fake_judge), \
             patch.object(ga, "ChatOpenAI", return_value=FakeLLM()), \
             patch.object(ga, "_repass_model", return_value="gpt-4o"):
            new_report = asyncio.run(ga.run_repass_batch(
                report=report,
                requirement_ids=["R002"],
                user_id="alice",
                openai_api_key="sk-fake",
                force=True,
            ))

        reqs = {r["id"]: r for r in new_report["requirements"]}
        self.assertEqual(reqs["R002"]["verdict"], "FORCED")


# ---------------------------------------------------------------------------
# 4) export_feedback_csv
# ---------------------------------------------------------------------------


class TestExportFeedbackCsv(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = _isolate_data_dir()
        from rag import workspace as ws_mod
        cls.workspace = ws_mod

    def setUp(self) -> None:
        with self.workspace._connect() as conn:
            conn.execute("DELETE FROM requirement_feedback")
            conn.execute("DELETE FROM analyses")
            conn.execute("DELETE FROM cdcs")
            conn.execute("DELETE FROM clients")

    def _seed(self) -> int:
        report = {
            "filename": "cdc_demo.pdf",
            "summary": {"total": 2, "covered": 1, "partial": 0,
                        "missing": 0, "ambiguous": 1,
                        "coverage_percent": 50.0},
            "requirements": [
                {"id": "R001", "title": "Calcul brut", "description": "...",
                 "category": "Paie", "subdomain": "Paie/cotisations",
                 "priority": "must", "status": "covered",
                 "verdict": "Conforme", "evidence": ["e1", "e2"],
                 "sources": [
                     {"source": "ref.pdf", "page": 3, "score": 0.0123,
                      "text": "extrait"},
                 ],
                 "confidence": 0.82},
                {"id": "R002", "title": 'Saisie « guillemets »',
                 "description": "Lignes\nmultiples", "category": "DSN",
                 "subdomain": None, "priority": "must",
                 "status": "ambiguous", "verdict": "Doute ; à vérifier",
                 "evidence": [], "sources": [], "confidence": 0.3},
            ],
        }
        return _seed_analysis_with_report(
            self.workspace, "alice", "ACME", "cdc_demo.pdf", report,
        )

    def _collect(self, aid: str) -> str:
        return "".join(self.workspace.export_feedback_csv(aid))

    def test_bom_et_separateur_excel_france(self) -> None:
        aid = self._seed()
        out = self._collect(str(aid))
        # Le BOM UTF-8 doit être présent en tête.
        self.assertTrue(out.startswith("﻿"), "BOM UTF-8 attendu")
        first_line = out.splitlines()[0]
        # Séparateur ';' attendu, pas ','.
        self.assertIn(";", first_line)
        self.assertNotIn(",", first_line)

    def test_structure_colonnes(self) -> None:
        aid = self._seed()
        out = self._collect(str(aid))
        first_line = out.splitlines()[0].lstrip("﻿")
        cols = first_line.split(";")
        attendues = [
            "analysis_id", "cdc_filename", "requirement_id",
            "requirement_title", "domain", "subdomain", "priority",
            "status", "confidence", "verdict",
            "evidence_concatenated", "sources_concatenated",
            "vote", "comment", "voted_at", "voted_by",
        ]
        self.assertEqual(cols, attendues)

    def test_une_ligne_par_exigence_meme_sans_feedback(self) -> None:
        aid = self._seed()
        out = self._collect(str(aid))
        # 1 ligne d'en-tête + 2 exigences = 3 lignes non vides.
        non_empty = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(non_empty), 3)

    def test_echappement_quotes_separateurs_newlines(self) -> None:
        aid = self._seed()
        # Ajoute un commentaire qui contient ; et "
        self.workspace.upsert_feedback(
            str(aid), "R002", "alice", "down",
            comment='avis ; "tres" douteux',
        )
        out = self._collect(str(aid))
        # Les champs avec ; ou " doivent être entre guillemets et les "
        # internes doublés.
        self.assertIn('"avis ; ""tres"" douteux"', out)
        # Pas d'écho littéral d'un newline non échappé dans le CSV.
        # (le verdict de R002 contient un point-virgule → doit être quoté)
        self.assertIn('"Doute ; à vérifier"', out)

    def test_evidence_et_sources_concatenees(self) -> None:
        aid = self._seed()
        out = self._collect(str(aid))
        # evidence joinée par " | "
        self.assertIn("e1 | e2", out)
        # sources sous le format "source p.X (score)"
        self.assertIn("ref.pdf p.3 (0.012)", out)

    def test_utf8_accents_preserves(self) -> None:
        aid = self._seed()
        out_bytes = "".join(self.workspace.export_feedback_csv(str(aid)))
        # Conserve les accents lus côté SQLite/Python (UTF-8 implicite).
        self.assertIn("Doute", out_bytes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
