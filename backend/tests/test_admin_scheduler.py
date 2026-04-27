"""Tests Page Admin Planificateur (cron + jobs FIFO + maintenance + notifs).

Couverture :
  - SchedulerManager : add / remove / cron validation / next_run
  - runner : verrou FIFO global, pause chat, notifications
  - endpoints CRUD (POST/PUT/DELETE schedules) via TestClient FastAPI
  - endpoint run-now (planifié + one-shot)
  - endpoint jobs filtré
  - maintenance : reembed_source (mock connecteur), optimize_qdrant
    (mock client), integrity_check (mock client)

Mocks : tous les appels HTTP externes (BOSS/URSSAF/Qdrant) sont remplacés
par des stubs locaux. Aucun réseau requis pour faire passer ces tests.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Permet l'exécution directe depuis backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _reload_scheduler_modules() -> None:
    """Force le rechargement des modules scheduler avec le nouveau DATA_DIR."""
    from rag import config as rag_config
    importlib.reload(rag_config)
    from rag.scheduler import db as sched_db
    importlib.reload(sched_db)
    from rag.scheduler import runner as sched_runner
    importlib.reload(sched_runner)
    from rag.scheduler import manager as sched_manager
    importlib.reload(sched_manager)


# ---------------------------------------------------------------------------
# 1) SchedulerManager + cron validation
# ---------------------------------------------------------------------------


class TestSchedulerManagerAddRemove(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="sched_v311_")
        os.environ["DATA_DIR"] = cls._tmp
        _reload_scheduler_modules()
        from rag.scheduler import db as sched_db
        cls.db = sched_db
        cls.db.init_scheduler_db()

    def setUp(self) -> None:
        with self.db._connect() as conn:
            conn.execute("DELETE FROM scheduled_refreshes")
            conn.execute("DELETE FROM refresh_jobs")
            conn.execute("DELETE FROM app_notifications")
            conn.execute("DELETE FROM app_settings")

    def test_add_then_list_returns_schedule(self) -> None:
        from rag.scheduler.manager import SchedulerManager
        mgr = SchedulerManager.instance()
        # Empêche APScheduler de démarrer un thread BackgroundScheduler.
        mgr._scheduler = None
        mgr._started = True
        sched = mgr.add_schedule(
            source="boss",
            cron_expression="0 3 * * 1",
            label="BOSS hebdo",
            pause_chat_during_refresh=True,
        )
        self.assertEqual(sched["source"], "boss")
        self.assertEqual(sched["cron_expression"], "0 3 * * 1")
        self.assertTrue(sched["enabled"])
        self.assertTrue(sched["pause_chat_during_refresh"])
        self.assertIsNotNone(sched.get("next_run_at"))
        listing = self.db.list_schedules()
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["id"], sched["id"])

    def test_delete_schedule_removes_row(self) -> None:
        from rag.scheduler.manager import SchedulerManager
        mgr = SchedulerManager.instance()
        mgr._scheduler = None
        mgr._started = True
        sched = mgr.add_schedule(
            source="urssaf",
            cron_expression="0 4 * * 0",
        )
        ok = mgr.delete_schedule(sched["id"])
        self.assertTrue(ok)
        self.assertEqual(self.db.list_schedules(), [])


class TestSchedulerCronValidation(unittest.TestCase):
    def test_refuse_expression_invalide(self) -> None:
        from rag.scheduler.manager import _validate_cron
        with self.assertRaises(ValueError):
            _validate_cron("")
        with self.assertRaises(ValueError):
            _validate_cron("plop")
        with self.assertRaises(ValueError):
            _validate_cron("0 3 * *")  # 4 champs

    def test_accepte_expression_valide(self) -> None:
        from rag.scheduler.manager import _validate_cron, _next_run_iso
        # 5 champs valides → pas d'exception
        _validate_cron("0 3 * * 1")
        nxt = _next_run_iso("0 3 * * 1")
        self.assertIsNotNone(nxt)


# ---------------------------------------------------------------------------
# 2) Runner — FIFO + pause chat + notifications
# ---------------------------------------------------------------------------


class TestRunnerFifoLockAndPauseChat(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="sched_runner_")
        os.environ["DATA_DIR"] = cls._tmp
        _reload_scheduler_modules()
        from rag.scheduler import db as sched_db
        from rag.scheduler import runner as sched_runner
        cls.db = sched_db
        cls.runner = sched_runner
        cls.db.init_scheduler_db()

    def setUp(self) -> None:
        with self.db._connect() as conn:
            conn.execute("DELETE FROM scheduled_refreshes")
            conn.execute("DELETE FROM refresh_jobs")
            conn.execute("DELETE FROM app_notifications")
            conn.execute("DELETE FROM app_settings")

    def _wait_until(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_runner_fifo_lock_serialise_les_jobs(self) -> None:
        # Dispatcher mocké : compte les invocations concurrentes via un
        # registre process-wide, et bloque artificiellement chaque exécution.
        in_flight: list[int] = []
        max_seen: list[int] = [0]

        def fake_dispatch(source, job_id, optimize_target):
            in_flight.append(job_id)
            max_seen[0] = max(max_seen[0], len(in_flight))
            time.sleep(0.2)
            in_flight.remove(job_id)
            return {
                "pages_fetched": 1,
                "chunks_indexed": 2,
                "log_excerpt": f"job={job_id}",
            }

        self.runner.set_dispatch_override(fake_dispatch)
        try:
            j1 = self.runner.submit_job(source="boss", trigger="manual")
            j2 = self.runner.submit_job(source="urssaf", trigger="manual")
            self.assertIsNotNone(j1)
            self.assertIsNotNone(j2)
            # On attend que les deux jobs aient terminé.
            ok = self._wait_until(
                lambda: (
                    self.db.get_job(j1["id"]) is not None
                    and self.db.get_job(j1["id"])["status"] == "success"
                    and self.db.get_job(j2["id"])["status"] == "success"
                ),
                timeout=5.0,
            )
            self.assertTrue(ok, "les 2 jobs auraient dû passer en success")
            # Verrou FIFO : jamais deux jobs en simultané.
            self.assertLessEqual(max_seen[0], 1)
        finally:
            self.runner.set_dispatch_override(None)

    def test_runner_pause_chat_set_then_unset(self) -> None:
        # Dispatcher mocké : pendant l'exécution, on observe le flag.
        observed: dict[str, bool] = {}

        def fake_dispatch(source, job_id, optimize_target):
            observed["during"] = self.db.is_chat_paused()
            return {"pages_fetched": 0, "chunks_indexed": 0, "log_excerpt": ""}

        self.runner.set_dispatch_override(fake_dispatch)
        try:
            self.runner.submit_job(
                source="boss", trigger="manual", pause_chat=True,
            )
            ok = self._wait_until(
                lambda: not self.db.is_chat_paused()
                and "during" in observed,
                timeout=3.0,
            )
            self.assertTrue(ok)
            # Pendant le job → True ; à la fin → False.
            self.assertTrue(observed["during"])
            self.assertFalse(self.db.is_chat_paused())
        finally:
            self.runner.set_dispatch_override(None)

    def test_runner_emit_notification_a_la_fin_succes(self) -> None:
        def fake_dispatch(source, job_id, optimize_target):
            return {"pages_fetched": 5, "chunks_indexed": 10, "log_excerpt": ""}

        self.runner.set_dispatch_override(fake_dispatch)
        try:
            self.runner.submit_job(source="urssaf", trigger="manual")
            ok = self._wait_until(
                lambda: self.db.count_unread_notifications("daniel") >= 1,
                timeout=3.0,
            )
            self.assertTrue(ok)
            items = self.db.list_notifications("daniel", unread_only=True)
            self.assertEqual(items[0]["level"], "info")
            self.assertIn("urssaf", items[0]["title"])
        finally:
            self.runner.set_dispatch_override(None)

    def test_runner_emit_notification_erreur(self) -> None:
        def fake_dispatch(source, job_id, optimize_target):
            raise RuntimeError("boum")

        self.runner.set_dispatch_override(fake_dispatch)
        try:
            self.runner.submit_job(source="boss", trigger="manual")
            ok = self._wait_until(
                lambda: self.db.count_unread_notifications("daniel") >= 1,
                timeout=3.0,
            )
            self.assertTrue(ok)
            items = self.db.list_notifications("daniel", unread_only=True)
            self.assertEqual(items[0]["level"], "error")
            self.assertIn("boum", items[0]["body"] or "")
        finally:
            self.runner.set_dispatch_override(None)


# ---------------------------------------------------------------------------
# 3) Endpoints (TestClient FastAPI)
# ---------------------------------------------------------------------------


class TestEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="sched_api_")
        os.environ["DATA_DIR"] = cls._tmp
        os.environ["JWT_SECRET"] = "test-secret"
        _reload_scheduler_modules()
        # On évite que l'init de main.py démarre APScheduler / les workers :
        # on patch le démarrage du scheduler.
        with patch(
            "rag.scheduler.manager.SchedulerManager.start",
            lambda self: None,
        ):
            sys.modules.pop("main", None)
            import main  # type: ignore
            cls.main = main
        from fastapi.testclient import TestClient
        cls.client = TestClient(cls.main.app)
        # Override la dépendance require_admin + get_current_user pour
        # éviter la chaîne JWT complète.
        from main import get_current_user, require_admin

        def _stub_user() -> str:
            return "daniel"

        cls.main.app.dependency_overrides[get_current_user] = _stub_user
        cls.main.app.dependency_overrides[require_admin] = _stub_user

    def setUp(self) -> None:
        from rag.scheduler import db as sched_db
        with sched_db._connect() as conn:
            conn.execute("DELETE FROM scheduled_refreshes")
            conn.execute("DELETE FROM refresh_jobs")
            conn.execute("DELETE FROM app_notifications")
            conn.execute("DELETE FROM app_settings")

    def test_endpoints_crud_schedules(self) -> None:
        # CREATE
        r = self.client.post(
            "/admin/schedules",
            json={
                "source": "boss",
                "cron_expression": "0 3 * * 1",
                "label": "BOSS hebdo",
                "pause_chat_during_refresh": True,
                "enabled": True,
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        sched = r.json()
        sid = sched["id"]
        self.assertEqual(sched["source"], "boss")
        # LIST
        r = self.client.get("/admin/schedules")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["schedules"]), 1)
        # UPDATE
        r = self.client.put(
            f"/admin/schedules/{sid}",
            json={"label": "BOSS lundi 3h"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["label"], "BOSS lundi 3h")
        # DELETE
        r = self.client.delete(f"/admin/schedules/{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["deleted"])
        r = self.client.get("/admin/schedules")
        self.assertEqual(r.json()["schedules"], [])

    def test_endpoints_crud_refuse_source_invalide(self) -> None:
        r = self.client.post(
            "/admin/schedules",
            json={"source": "evil", "cron_expression": "0 3 * * 1"},
        )
        self.assertEqual(r.status_code, 400)

    def test_endpoints_crud_refuse_cron_invalide(self) -> None:
        r = self.client.post(
            "/admin/schedules",
            json={"source": "boss", "cron_expression": "0 3 * *"},
        )
        self.assertEqual(r.status_code, 400)

    def test_endpoint_run_now_one_shot(self) -> None:
        from rag.scheduler import runner as sched_runner

        captured: list[str] = []

        def fake_dispatch(source, job_id, optimize_target):
            captured.append(source)
            return {"pages_fetched": 0, "chunks_indexed": 0, "log_excerpt": ""}

        sched_runner.set_dispatch_override(fake_dispatch)
        try:
            r = self.client.post("/admin/sources/boss/run-now")
            self.assertEqual(r.status_code, 202, r.text)
            job = r.json()
            self.assertEqual(job["source"], "boss")
            self.assertEqual(job["trigger"], "manual")
            # Attendre que le worker traite et appelle le dispatcher
            deadline = time.time() + 3.0
            while time.time() < deadline and not captured:
                time.sleep(0.05)
            self.assertEqual(captured, ["boss"])
        finally:
            sched_runner.set_dispatch_override(None)

    def test_endpoint_jobs_history_filters(self) -> None:
        from rag.scheduler import db as sched_db
        sched_db.insert_job(source="boss", trigger="manual", status="success")
        sched_db.insert_job(source="urssaf", trigger="manual", status="error")
        sched_db.insert_job(source="boss", trigger="cron", status="success")

        r = self.client.get("/admin/jobs", params={"source": "boss"})
        self.assertEqual(r.status_code, 200)
        jobs = r.json()["jobs"]
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(j["source"] == "boss" for j in jobs))

        r = self.client.get("/admin/jobs", params={"status": "error"})
        jobs = r.json()["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "error")

    def test_endpoint_jobs_current_renvoie_running_si_present(self) -> None:
        from rag.scheduler import db as sched_db
        sched_db.insert_job(
            source="boss", trigger="manual", status="running",
        )
        r = self.client.get("/admin/jobs/current")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()["job"])
        self.assertEqual(r.json()["job"]["status"], "running")


# ---------------------------------------------------------------------------
# 4) Maintenance (reembed_source / optimize / integrity_check)
# ---------------------------------------------------------------------------


class TestMaintenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="sched_maint_")
        os.environ["DATA_DIR"] = cls._tmp
        _reload_scheduler_modules()

    def test_reembed_source_appelle_le_pipeline_public(self) -> None:
        # On mocke _run_public_connector pour ne pas toucher au réseau.
        from rag.scheduler import maintenance, runner
        with patch.object(
            runner, "_run_public_connector",
            return_value={
                "pages_fetched": 7, "chunks_indexed": 42,
                "log_excerpt": "ok",
            },
        ) as mocked:
            out = maintenance.reembed_source("boss")
            mocked.assert_called_once_with("boss", 0)
            self.assertEqual(out["pages_fetched"], 7)
            self.assertEqual(out["chunks_indexed"], 42)

    def test_reembed_source_refuse_source_inconnue(self) -> None:
        from rag.scheduler import maintenance
        with self.assertRaises(ValueError):
            maintenance.reembed_source("ghost")

    def test_optimize_qdrant_appelle_update_collection(self) -> None:
        from rag.scheduler import maintenance

        fake_client = MagicMock()
        # MagicMock(name=...) ne contrôle pas .name — on patch :
        col_mock = MagicMock()
        col_mock.name = "kb"
        fake_client.get_collections.return_value.collections = [col_mock]
        info = MagicMock()
        info.points_count = 100
        info.segments_count = 5
        fake_client.get_collection.return_value = info

        with patch.object(
            maintenance, "get_qdrant_client", return_value=fake_client,
        ):
            out = maintenance.optimize_qdrant_collection("kb")

        fake_client.update_collection.assert_called_once()
        self.assertEqual(out["chunks_indexed"], 100)
        self.assertIn("collection=kb", out["log_excerpt"])

    def test_optimize_qdrant_refuse_collection_inconnue(self) -> None:
        from rag.scheduler import maintenance

        fake_client = MagicMock()
        col_mock = MagicMock()
        col_mock.name = "kb"
        fake_client.get_collections.return_value.collections = [col_mock]
        with patch.object(
            maintenance, "get_qdrant_client", return_value=fake_client,
        ):
            with self.assertRaises(ValueError):
                maintenance.optimize_qdrant_collection("absente")

    def test_integrity_check_compte_orphelins_et_sources(self) -> None:
        from rag.scheduler import maintenance

        # Faux client Qdrant : 3 points, 1 sans source (orphan).
        col_mock = MagicMock()
        col_mock.name = "knowledge_base"

        fake_client = MagicMock()
        fake_client.get_collections.return_value.collections = [col_mock]
        info = MagicMock()
        info.points_count = 3
        fake_client.get_collection.return_value = info

        # scroll : itère une seule page de 3 points
        p1 = MagicMock(payload={"metadata": {"source": "boss",
                                              "chunk_id": "c1"}})
        p2 = MagicMock(payload={"metadata": {"source": "boss",
                                              "chunk_id": "c2"}})
        p3 = MagicMock(payload={"metadata": {}})  # orphan
        fake_client.scroll.side_effect = [
            ([p1, p2, p3], None),
        ]

        with patch.object(
            maintenance, "get_qdrant_client", return_value=fake_client,
        ):
            report = maintenance.run_integrity_check()

        self.assertEqual(len(report["collections"]), 2)  # kb + referentiels
        kb = next(
            c for c in report["collections"]
            if c["name"] == "knowledge_base"
        )
        self.assertEqual(kb["points"], 3)
        self.assertEqual(kb["orphans"], 1)
        self.assertEqual(kb["sources"], ["boss"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
