"""SchedulerManager — façade APScheduler pour la Page Admin Planificateur.

Architecture :
  - Un seul ``BackgroundScheduler`` partagé par le process FastAPI.
  - À chaque planification SQLite (``scheduled_refreshes``), on arme un job
    APScheduler avec la même expression cron. Le callback insère un job
    SQLite ``queued`` via :func:`runner.submit_job`.
  - Le worker FIFO (côté ``runner.py``) sérialise l'exécution.

L'override des stores APScheduler est volontairement minimal : on utilise
le store mémoire par défaut (``MemoryJobStore``). C'est la table
``scheduled_refreshes`` qui est la source de vérité — APScheduler n'est
qu'un déclencheur cron en mémoire, rechargé au boot.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from . import db, runner

logger = logging.getLogger(__name__)


def _validate_cron(expression: str) -> None:
    """Lève ``ValueError`` si l'expression cron 5 champs est invalide."""
    if not expression or not expression.strip():
        raise ValueError("Expression cron vide.")
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(
            "Expression cron invalide : 5 champs attendus "
            "(minute, heure, jour, mois, jour_semaine)."
        )
    try:
        from croniter import croniter
        if not croniter.is_valid(expression):
            raise ValueError(f"Expression cron invalide : '{expression}'.")
    except ImportError:
        # Si croniter n'est pas dispo, on se contente du contrôle 5 champs.
        logger.warning("croniter indisponible — validation cron limitée.")


def _next_run_iso(expression: str) -> Optional[str]:
    """Renvoie la prochaine exécution au format ISO 8601, ou None si invalide."""
    try:
        from croniter import croniter
        from datetime import datetime, timezone
        base = datetime.now(timezone.utc)
        it = croniter(expression, base)
        nxt = it.get_next(datetime)
        return nxt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


class SchedulerManager:
    """Singleton pour piloter APScheduler depuis FastAPI."""

    _instance: "SchedulerManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._scheduler = None
        self._started = False

    # ------------------------------------------------------------------
    # Accès singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "SchedulerManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler(timezone="UTC")
            self._scheduler.start()
        except Exception as exc:
            logger.warning(
                "APScheduler indisponible (%s) — déclenchement cron désactivé. "
                "Les jobs manuels (run-now) restent fonctionnels.", exc,
            )
            self._scheduler = None
            self._started = True
            return
        self._started = True
        # Charge toutes les planifications activées et arme les jobs cron.
        for sched in db.list_schedules(enabled_only=True):
            self._arm_job(sched)
        logger.info(
            "SchedulerManager démarré — %d planification(s) armée(s).",
            len(db.list_schedules(enabled_only=True)),
        )

    def shutdown(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                logger.exception("Erreur shutdown APScheduler")
        self._scheduler = None
        self._started = False

    # ------------------------------------------------------------------
    # Méthodes publiques (CRUD planifications)
    # ------------------------------------------------------------------

    def add_schedule(
        self,
        *,
        source: str,
        cron_expression: str,
        enabled: bool = True,
        pause_chat_during_refresh: bool = False,
        label: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        _validate_cron(cron_expression)
        sched = db.create_schedule(
            source=source,
            cron_expression=cron_expression,
            enabled=enabled,
            pause_chat_during_refresh=pause_chat_during_refresh,
            label=label,
            created_by=created_by,
        )
        # Calcule le prochain run et le persiste.
        next_run = _next_run_iso(cron_expression)
        if next_run:
            db.set_schedule_runtime(sched["id"], next_run_at=next_run)
            sched["next_run_at"] = next_run
        if enabled:
            self._arm_job(sched)
        return sched

    def update_schedule(
        self,
        schedule_id: int,
        *,
        cron_expression: Optional[str] = None,
        enabled: Optional[bool] = None,
        pause_chat_during_refresh: Optional[bool] = None,
        label: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if cron_expression is not None:
            _validate_cron(cron_expression)
        sched = db.update_schedule(
            schedule_id,
            cron_expression=cron_expression,
            enabled=enabled,
            pause_chat_during_refresh=pause_chat_during_refresh,
            label=label,
        )
        if sched is None:
            return None
        # Re-arme : on retire l'ancien job APScheduler puis on rearme si enabled.
        self._unarm_job(schedule_id)
        if cron_expression is not None or enabled is not None:
            next_run = _next_run_iso(sched["cron_expression"])
            if next_run:
                db.set_schedule_runtime(schedule_id, next_run_at=next_run)
                sched["next_run_at"] = next_run
        if sched["enabled"]:
            self._arm_job(sched)
        return sched

    def delete_schedule(self, schedule_id: int) -> bool:
        self._unarm_job(schedule_id)
        return db.delete_schedule(schedule_id)

    def trigger_now(
        self,
        *,
        source: str,
        schedule_id: Optional[int] = None,
        pause_chat: bool = False,
        optimize_target: Optional[str] = None,
    ) -> dict[str, Any]:
        return runner.submit_job(
            source=source,
            trigger="manual" if schedule_id is None else "manual",
            schedule_id=schedule_id,
            pause_chat=pause_chat,
            optimize_target=optimize_target,
        )

    # ------------------------------------------------------------------
    # APScheduler wiring
    # ------------------------------------------------------------------

    def _arm_job(self, sched: dict[str, Any]) -> None:
        if self._scheduler is None:
            return
        try:
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            return
        m, h, dom, mon, dow = sched["cron_expression"].split()
        trigger = CronTrigger(
            minute=m, hour=h, day=dom, month=mon, day_of_week=dow,
            timezone="UTC",
        )
        job_id = self._aps_job_id(sched["id"])
        # remove + add pour idempotence
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        self._scheduler.add_job(
            func=_aps_callback,
            trigger=trigger,
            id=job_id,
            args=[int(sched["id"])],
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(
            "Planification armée : id=%s source=%s cron=%s",
            sched["id"], sched["source"], sched["cron_expression"],
        )

    def _unarm_job(self, schedule_id: int) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.remove_job(self._aps_job_id(schedule_id))
        except Exception:
            pass

    @staticmethod
    def _aps_job_id(schedule_id: int) -> str:
        return f"sched-{int(schedule_id)}"


def _aps_callback(schedule_id: int) -> None:
    """Callback exécuté par APScheduler à l'heure programmée.

    On charge la planification, on calcule le prochain run, puis on submit
    un job ``queued`` dans la file FIFO.
    """
    sched = db.get_schedule(schedule_id)
    if sched is None:
        logger.warning(
            "_aps_callback : planification %s introuvable.", schedule_id
        )
        return
    if not sched.get("enabled"):
        return
    pause_chat = bool(sched.get("pause_chat_during_refresh"))
    runner.submit_job(
        source=sched["source"],
        trigger="cron",
        schedule_id=schedule_id,
        pause_chat=pause_chat,
    )
    # Recalcule next_run pour affichage.
    next_run = _next_run_iso(sched["cron_expression"])
    if next_run:
        db.set_schedule_runtime(schedule_id, next_run_at=next_run)


def get_scheduler_manager() -> SchedulerManager:
    """Helper utilisé par main.py et les routers FastAPI."""
    return SchedulerManager.instance()


__all__ = [
    "SchedulerManager",
    "get_scheduler_manager",
    "_validate_cron",
    "_next_run_iso",
]
