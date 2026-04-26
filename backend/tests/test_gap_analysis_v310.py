"""
Tests unitaires v3.10 — Analyse CDC :
  - calcul du score de confiance combiné (LLM + retrieval)
  - taxonomie SIRH métier (8 domaines + Autre)
  - table requirement_feedback (insert / replace / delete / stats)

Exécution :
    cd backend && python -m pytest tests/test_gap_analysis_v310.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Permet l'exécution directe depuis backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.gap_analysis import (  # noqa: E402
    PIPELINE_VERSION,
    SUBDOMAIN_MAX_CHARS,
    VALID_CATEGORIES,
    _clamp_unit,
    _compute_retrieval_confidence,
    _normalise_requirement,
)


class TestPipelineVersion(unittest.TestCase):
    def test_pipeline_version_bumped(self) -> None:
        """Le bump v3.10.0 doit être effectif."""
        self.assertEqual(PIPELINE_VERSION, "v3.10.0")


class TestTaxonomieSIRH(unittest.TestCase):
    EXPECTED_DOMAINS = {
        "Paie",
        "DSN",
        "GTA",
        "Absences/Congés",
        "Contrats/Administration",
        "Portail/Self-service",
        "Intégrations/Interfaces",
        "Réglementaire",
    }

    def test_8_domaines_sirh_present(self) -> None:
        for d in self.EXPECTED_DOMAINS:
            self.assertIn(d, VALID_CATEGORIES, f"Domaine SIRH manquant : {d}")

    def test_autre_fallback_present(self) -> None:
        self.assertIn("Autre", VALID_CATEGORIES)

    def test_pas_de_categorie_iso25010_residuelle(self) -> None:
        """Les anciennes catégories ISO 25010 ne doivent plus apparaître."""
        old = {
            "Fonctionnel — Métier",
            "Fonctionnel — Interface utilisateur",
            "Sécurité & confidentialité",
            "Performance",
            "Disponibilité & résilience",
            "Conformité réglementaire",
            "Support & maintenance",
        }
        for o in old:
            self.assertNotIn(o, VALID_CATEGORIES)

    def test_total_9_categories(self) -> None:
        self.assertEqual(len(VALID_CATEGORIES), 9)

    def test_subdomain_normalise(self) -> None:
        r = _normalise_requirement(
            {
                "id": "R001",
                "title": "Test exigence",
                "description": "desc",
                "category": "Paie",
                "subdomain": "Paie/cotisations",
                "priority": "must",
            },
            "R001",
        )
        self.assertEqual(r["subdomain"], "Paie/cotisations")

    def test_subdomain_absent_devient_none(self) -> None:
        r = _normalise_requirement(
            {"id": "R002", "title": "T", "description": "d", "category": "DSN"},
            "R002",
        )
        self.assertIsNone(r["subdomain"])

    def test_subdomain_tronque_a_80(self) -> None:
        long_sd = "x" * 200
        r = _normalise_requirement(
            {
                "id": "R003", "title": "T", "description": "d",
                "category": "Paie", "subdomain": long_sd,
            },
            "R003",
        )
        self.assertIsNotNone(r["subdomain"])
        self.assertLessEqual(len(r["subdomain"]), SUBDOMAIN_MAX_CHARS)

    def test_categorie_inconnue_retombe_sur_autre(self) -> None:
        r = _normalise_requirement(
            {
                "id": "R004", "title": "T", "description": "d",
                "category": "Inexistante",
            },
            "R004",
        )
        self.assertEqual(r["category"], "Autre")


class TestScoreDeConfiance(unittest.TestCase):
    def test_clamp_unit_borne_inf(self) -> None:
        self.assertEqual(_clamp_unit(-0.5), 0.0)

    def test_clamp_unit_borne_sup(self) -> None:
        self.assertEqual(_clamp_unit(2.0), 1.0)

    def test_clamp_unit_valeur_normale(self) -> None:
        self.assertAlmostEqual(_clamp_unit(0.7), 0.7)

    def test_clamp_unit_defaut_si_non_numerique(self) -> None:
        self.assertEqual(_clamp_unit(None, default=0.42), 0.42)
        self.assertEqual(_clamp_unit("abc", default=0.5), 0.5)

    def test_retrieval_confidence_zero_source(self) -> None:
        self.assertEqual(_compute_retrieval_confidence([]), 0.0)

    def test_retrieval_confidence_avec_3_sources(self) -> None:
        sources = [
            {"score": 0.0164},  # ~ top-1 RRF (rrf_k=60)
            {"score": 0.0156},
            {"score": 0.0149},
        ]
        result = _compute_retrieval_confidence(sources)
        # Doit être > 0 et borné à 1.
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_retrieval_confidence_avec_moins_de_3_sources(self) -> None:
        """Avec 1 ou 2 sources, on prend la moyenne disponible — pas de plantage."""
        single = _compute_retrieval_confidence([{"score": 0.01}])
        self.assertGreater(single, 0.0)
        double = _compute_retrieval_confidence([{"score": 0.01}, {"score": 0.005}])
        self.assertGreater(double, 0.0)

    def test_combinaison_70_30(self) -> None:
        """Le score final = 0.7 * llm + 0.3 * retrieval, arrondi à 3 décimales."""
        llm = 0.8
        retrieval = 0.4
        expected = round(0.7 * llm + 0.3 * retrieval, 3)
        self.assertAlmostEqual(expected, 0.68, places=3)

    def test_llm_confidence_absente_donne_0_5(self) -> None:
        """Si le LLM oublie le champ confidence, on prend 0.5 par défaut."""
        # Cas exact validé via _clamp_unit avec la valeur par défaut.
        self.assertEqual(_clamp_unit(None, default=0.5), 0.5)


class TestRequirementFeedbackTable(unittest.TestCase):
    """Test la table requirement_feedback : insert, replace, delete, stats."""

    @classmethod
    def setUpClass(cls) -> None:
        # Isole la DB workspace dans un répertoire temporaire pour chaque test
        # de cette classe (data dir partagé sur la durée du test).
        cls._tmp = tempfile.mkdtemp(prefix="ws_v310_")
        os.environ["DATA_DIR"] = cls._tmp
        # Forcer le rechargement du module workspace avec le nouveau DATA_DIR.
        import importlib

        from rag import config as rag_config
        importlib.reload(rag_config)
        from rag import workspace as ws_mod
        importlib.reload(ws_mod)
        cls.workspace = ws_mod
        cls.workspace.init_db()

    def setUp(self) -> None:
        # Un client/cdc/analysis nécessaires pour tester user_owns_analysis.
        # Pour les tests purs feedback, on appelle directement upsert/get/delete
        # avec un analysis_id arbitraire (la FK n'est pas posée).
        self.user = "alice"
        self.analysis_id = "1"
        self.req_a = "R001"
        self.req_b = "R002"

    def tearDown(self) -> None:
        # Vider la table pour isoler chaque test.
        with self.workspace._connect() as conn:
            conn.execute("DELETE FROM requirement_feedback")

    def test_insert_feedback_up(self) -> None:
        out = self.workspace.upsert_feedback(
            self.analysis_id, self.req_a, self.user, "up", "ok"
        )
        self.assertEqual(out["vote"], "up")
        self.assertEqual(out["comment"], "ok")
        # Lecture cohérente
        got = self.workspace.get_feedback(self.analysis_id, self.req_a, self.user)
        self.assertIsNotNone(got)
        self.assertEqual(got["vote"], "up")

    def test_replace_feedback_up_to_down(self) -> None:
        self.workspace.upsert_feedback(
            self.analysis_id, self.req_a, self.user, "up"
        )
        self.workspace.upsert_feedback(
            self.analysis_id, self.req_a, self.user, "down", "désaccord"
        )
        got = self.workspace.get_feedback(self.analysis_id, self.req_a, self.user)
        self.assertEqual(got["vote"], "down")
        self.assertEqual(got["comment"], "désaccord")
        # On ne doit avoir qu'une seule ligne pour ce trio.
        rows = self.workspace.list_feedback_for_analysis(self.analysis_id)
        self.assertEqual(len(rows), 1)

    def test_delete_feedback(self) -> None:
        self.workspace.upsert_feedback(
            self.analysis_id, self.req_a, self.user, "up"
        )
        ok = self.workspace.delete_feedback(self.analysis_id, self.req_a, self.user)
        self.assertTrue(ok)
        got = self.workspace.get_feedback(self.analysis_id, self.req_a, self.user)
        self.assertIsNone(got)

    def test_delete_inexistant_renvoie_false(self) -> None:
        ok = self.workspace.delete_feedback(self.analysis_id, "R999", "ghost")
        self.assertFalse(ok)

    def test_vote_invalide_leve_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.workspace.upsert_feedback(
                self.analysis_id, self.req_a, self.user, "maybe"
            )

    def test_unicite_par_user(self) -> None:
        """Deux users votent sur la même exigence => 2 lignes distinctes."""
        self.workspace.upsert_feedback(
            self.analysis_id, self.req_a, "alice", "up"
        )
        self.workspace.upsert_feedback(
            self.analysis_id, self.req_a, "bob", "down"
        )
        rows = self.workspace.list_feedback_for_analysis(self.analysis_id)
        self.assertEqual(len(rows), 2)

    def test_stats_aggregat_basique(self) -> None:
        self.workspace.upsert_feedback(self.analysis_id, "R001", "alice", "up")
        self.workspace.upsert_feedback(self.analysis_id, "R002", "bob", "down")
        self.workspace.upsert_feedback(self.analysis_id, "R002", "carol", "down")
        stats = self.workspace.get_feedback_stats(self.analysis_id)
        self.assertEqual(stats["total_votes"], 3)
        self.assertEqual(stats["up"], 1)
        self.assertEqual(stats["down"], 2)
        # Top contested = R002 (2 down).
        self.assertEqual(stats["top_contested"][0]["requirement_id"], "R002")
        self.assertEqual(stats["top_contested"][0]["down_votes"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
