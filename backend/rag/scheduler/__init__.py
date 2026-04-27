"""Page Admin Planificateur — module scheduler.

Sous-modules :
  - db        : schéma SQLite (scheduled_refreshes, refresh_jobs, app_notifications)
                + helpers CRUD purs (sans logique métier).
  - runner    : exécution d'un job (lock FIFO, pause chat, notifications).
  - manager   : façade APScheduler — singleton chargé au démarrage FastAPI.

Volontairement simple : SQLite + un seul thread worker. Pas de queue distribuée,
pas de Redis. Le verrou « un seul job actif à la fois » est implémenté en SQL
(SELECT WHERE status='running').
"""
from .db import (
    SCHEDULER_DB_PATH,
    VALID_SOURCES,
    init_scheduler_db,
)
from .manager import SchedulerManager, get_scheduler_manager

__all__ = [
    "SCHEDULER_DB_PATH",
    "VALID_SOURCES",
    "SchedulerManager",
    "get_scheduler_manager",
    "init_scheduler_db",
]
