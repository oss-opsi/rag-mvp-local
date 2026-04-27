"""Connecteur DSN-info — fiches CustHelp net-entreprises (dsn-info.custhelp.com).

Stratégie P0 : 14 fiches identifiées par leur `a_id` direct (consignes par
événement : embauche, arrêt maladie, FCT, reprise, rupture conventionnelle,
versement mobilité, etc.). Pas de crawl du moteur de recherche CustHelp.

httpx HTTP/1.1 suffit (pas de Cloudflare). Pause politesse 1.5s.

Métadonnées harmonisées KB : source, source_id (dsn_info/a_id/<n>),
url_canonique, date_maj (parsée depuis #rn_AnswerInfo), domaine[], scope='kb'.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from .base import BaseConnector, KBChunk
from .http_fetcher import BaseHttpFetcher

logger = logging.getLogger(__name__)

BASE_URL = "https://dsn-info.custhelp.com/app/answers/detail_dsn/a_id/"

# 14 fiches P0 (a_id, sujet, domaine[])
P0_FICHES: list[tuple[int, str, list[str]]] = [
    (638, "Périodicité DSN", ["dsn"]),
    (1548, "Embauche / DPAE-DSN", ["dsn", "rh"]),
    (1652, "Contrat à temps partiel", ["dsn", "paie"]),
    (1620, "Arrêt maladie", ["dsn", "absences"]),
    (3373, "Signalement Fin Contrat de Travail", ["dsn"]),
    (3372, "Signalement Reprise", ["dsn"]),
    (2640, "Maintien salaire arrêt", ["dsn", "paie", "absences"]),
    (3369, "Versement Mobilité", ["dsn", "paie"]),
    (2960, "Indemnités journalières", ["dsn", "paie", "absences"]),
    (3277, "Régularisation", ["dsn", "paie"]),
    (3364, "Rupture conventionnelle", ["dsn", "rh"]),
    (3036, "Apprentissage", ["dsn", "paie"]),
    (1911, "Mise à pied conservatoire", ["dsn", "rh"]),
    (1921, "Préavis non effectué", ["dsn", "rh"]),
]

DROP_SELECTORS = [
    "nav", "header", "footer", "script", "style",
    "#rn_Header", "#rn_Footer", "#rn_PageNavigation",
    ".rn_NavigationLink", ".rn_PageContent .rn_Header",
]

DATE_RE = re.compile(
    r"Date\s+de\s+la\s+derni[èe]re\s+mise\s+à\s+jour\s*:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


def _date_fr_to_iso(date_fr: str | None) -> str | None:
    if not date_fr:
        return None
    try:
        d, m, y = date_fr.split("/")
        return f"{y}-{m}-{d}"
    except ValueError:
        return date_fr


class DsnInfoConnector(BaseConnector):
    """Connecteur DSN-info (CustHelp net-entreprises) — fiches a_id P0."""

    NAME = "dsn_info"
    DEFAULT_DOMAINES = ["dsn", "paie"]

    def __init__(
        self,
        *,
        max_chars_per_chunk: int = 1800,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.max_chars_per_chunk = max_chars_per_chunk
        self._fetcher = BaseHttpFetcher(
            source_name=self.NAME,
            http2=False,
            use_urllib=False,
            polite_delay=1.5,
            timeout=30.0,
            cache_ttl_seconds=24 * 3600,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TellMe-Indexer/1.0)",
            },
        )

    # ------------------------------------------------------------------
    # FETCH
    # ------------------------------------------------------------------

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        for a_id, sujet, domaine in P0_FICHES:
            url = f"{BASE_URL}{a_id}"
            logger.info("[%s] GET %s", self.NAME, url)
            try:
                res = self._fetcher.get_html(url, use_cache=True)
            except Exception as exc:
                logger.warning("[%s] fetch a_id=%s a échoué : %s",
                               self.NAME, a_id, exc)
                continue
            if not res.ok:
                logger.warning("[%s] HTTP %s sur a_id=%s — fiche ignorée",
                               self.NAME, res.status_code, a_id)
                continue
            # Filtrage page d'erreur CustHelp : la plateforme redirige les
            # fiches manquantes vers /app/error/error_id/N. Le HTML rendu n'a
            # pas de #rn_AnswerText et peut contenir des blocs JS qui ne sont
            # pas du contenu utile (et qui peuvent perturber le pipeline
            # d'embedding s'ils sont chunkés tels quels).
            final_url = (res.url or "").lower()
            if "/app/error/" in final_url:
                logger.warning(
                    "[%s] a_id=%s redirigé vers page d'erreur (%s) — fiche ignorée",
                    self.NAME, a_id, res.url,
                )
                continue
            html_text = res.text or ""
            if len(html_text) < 200 or "rn_AnswerText" not in html_text:
                logger.warning(
                    "[%s] a_id=%s : HTML sans rn_AnswerText (taille=%d) — fiche ignorée",
                    self.NAME, a_id, len(html_text),
                )
                continue
            yield {
                "a_id": a_id,
                "sujet": sujet,
                "url": url,
                "html": html_text,
                "domaine": domaine,
            }

    # ------------------------------------------------------------------
    # PARSE
    # ------------------------------------------------------------------

    def parse(self, raw: dict[str, Any]) -> dict[str, Any]:
        soup = BaseHttpFetcher.parse_html(raw["html"], drop_selectors=DROP_SELECTORS)

        # Titre : #rn_AnswerTitle (souvent un <p> à l'intérieur)
        title_node = soup.select_one("#rn_AnswerTitle p") or soup.select_one("#rn_AnswerTitle")
        title = title_node.get_text(strip=True) if title_node else raw.get("sujet", "")

        # Métadonnées : #rn_AnswerInfo (date publication, dernière maj)
        info_node = soup.select_one("#rn_AnswerInfo")
        info_text = info_node.get_text(separator=" ", strip=True) if info_node else ""
        m = DATE_RE.search(info_text)
        date_maj = _date_fr_to_iso(m.group(1)) if m else None

        # Corps : #rn_AnswerText
        body_node = soup.select_one("#rn_AnswerText")
        if body_node is None:
            return {"_skip": True, "reason": "no #rn_AnswerText"}

        body_parts: list[str] = []
        for tag in body_node.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            txt = tag.get_text(separator=" ", strip=True)
            if not txt or len(txt) < 3:
                continue
            if tag.name in ("h1", "h2", "h3", "h4"):
                body_parts.append(f"\n{txt}\n")
            else:
                body_parts.append(txt)

        text = "\n".join(p for p in body_parts if p)
        if not text:
            text = body_node.get_text(separator="\n", strip=True)

        return {
            "_skip": False,
            "a_id": raw["a_id"],
            "title": title or raw.get("sujet", ""),
            "url_canonique": raw["url"],
            "date_maj": date_maj,
            "domaine": raw["domaine"],
            "text": text,
        }

    # ------------------------------------------------------------------
    # CHUNK
    # ------------------------------------------------------------------

    def chunk(self, doc: dict[str, Any]) -> list[KBChunk]:
        if doc.get("_skip"):
            return []
        text = doc.get("text", "")
        if not text:
            return []

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks_text: list[str] = []
        buf = ""
        for para in paragraphs:
            if not buf:
                buf = para
                continue
            if len(buf) + len(para) + 2 <= self.max_chars_per_chunk:
                buf = f"{buf}\n\n{para}"
            else:
                chunks_text.append(buf)
                buf = para
        if buf:
            chunks_text.append(buf)
        if not chunks_text:
            chunks_text = [text[: self.max_chars_per_chunk]]

        kb_chunks: list[KBChunk] = []
        for idx, ct in enumerate(chunks_text, start=1):
            metadata = self._base_metadata(
                source_id=f"dsn_info/a_id/{doc['a_id']}",
                title=doc["title"],
                url_canonique=doc["url_canonique"],
                date_maj=doc.get("date_maj"),
                page=f"section-{idx}/{len(chunks_text)}",
            )
            metadata["domaine"] = list(doc.get("domaine", self.domaines))
            kb_chunks.append(KBChunk(text=ct, metadata=metadata))
        return kb_chunks

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------

    def run(self, **kwargs: Any) -> Any:
        from .base import ConnectorRunResult
        from .kb_upsert import upsert_kb_chunks

        result = ConnectorRunResult(source=self.NAME)
        all_chunks: list[KBChunk] = []
        try:
            for raw in self.fetch(**kwargs):
                result.fetched += 1
                try:
                    doc = self.parse(raw)
                    chunks = self.chunk(doc)
                    if chunks:
                        result.chunks += len(chunks)
                        all_chunks.extend(chunks)
                except Exception as exc:
                    msg = f"parse/chunk failed for a_id={raw.get('a_id')}: {exc}"
                    logger.warning("[%s] %s", self.NAME, msg)
                    result.errors.append(msg)
        except Exception as exc:
            msg = f"fetch failed: {exc}"
            logger.warning("[%s] %s", self.NAME, msg)
            result.errors.append(msg)

        if all_chunks:
            try:
                result.upserted = upsert_kb_chunks(
                    all_chunks, collection_name=self.kb_collection
                )
            except Exception as exc:
                msg = f"upsert failed: {exc}"
                logger.warning("[%s] %s", self.NAME, msg)
                result.errors.append(msg)

        return result
