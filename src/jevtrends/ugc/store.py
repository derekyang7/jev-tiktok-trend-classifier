"""SQLite persistence for the UGC version: V1's core tables plus facet tables (UGC spec §8)."""

import json

from jevtrends.store import SCHEMA, Store, _now
from jevtrends.ugc.config import RunProfiles, UgcSettings
from jevtrends.ugc.models import FacetTrend, SoundCandidate, UgcTrendScore

UGC_SCHEMA = """
CREATE TABLE IF NOT EXISTS ugc_trends (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, facet TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL,
  PRIMARY KEY (run_id, trend_id));
CREATE TABLE IF NOT EXISTS ugc_trend_members (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, video_id TEXT NOT NULL, probability REAL NOT NULL,
  PRIMARY KEY (run_id, trend_id, video_id));
CREATE TABLE IF NOT EXISTS ugc_sounds (
  run_id INTEGER NOT NULL, sound_id TEXT NOT NULL, data TEXT NOT NULL, niche_creators INTEGER NOT NULL DEFAULT 0,
  niche_share REAL, PRIMARY KEY (run_id, sound_id));
CREATE TABLE IF NOT EXISTS ugc_sound_samples (
  run_id INTEGER NOT NULL, sound_id TEXT NOT NULL, video_id TEXT NOT NULL, relevant REAL,
  PRIMARY KEY (run_id, sound_id, video_id));
CREATE TABLE IF NOT EXISTS ugc_trend_scores (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, facet TEXT NOT NULL, data TEXT NOT NULL, score REAL NOT NULL,
  rank_overall INTEGER NOT NULL, rank_in_facet INTEGER NOT NULL, PRIMARY KEY (run_id, trend_id));
CREATE TABLE IF NOT EXISTS ugc_pairs (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, partner_id TEXT NOT NULL, co REAL NOT NULL, lift REAL NOT NULL,
  PRIMARY KEY (run_id, trend_id, partner_id));
CREATE TABLE IF NOT EXISTS ugc_briefs (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, model TEXT NOT NULL, brief TEXT, status TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (run_id, trend_id));
CREATE TABLE IF NOT EXISTS ugc_reviews (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, video_id TEXT NOT NULL DEFAULT '', field TEXT NOT NULL,
  value TEXT NOT NULL, reviewed_at TEXT NOT NULL, PRIMARY KEY (run_id, trend_id, video_id, field));
"""


class UgcStore(Store):
    def schema(self) -> str:
        return SCHEMA + UGC_SCHEMA

    def get_run(self, run_id: int) -> dict:
        row = self._run_row(run_id)
        profiles = RunProfiles.model_validate_json(row["niches_snapshot"])
        return {**self.run_basics(run_id), "settings": UgcSettings.model_validate_json(row["settings_snapshot"]),
                "niche": profiles.niche, "product": profiles.product}

    # --- trends -----------------------------------------------------------
    def upsert_facet_trend(self, run_id: int, trend: FacetTrend) -> None:
        self._write(
            """INSERT INTO ugc_trends (run_id, trend_id, facet, data, status) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id, trend_id) DO UPDATE SET facet = excluded.facet, data = excluded.data,
                 status = excluded.status""",
            (run_id, trend.trend_id, trend.facet, trend.model_dump_json(), trend.status))

    def list_facet_trends(self, run_id: int, facet: str | None = None, status: str | None = None) -> list[FacetTrend]:
        sql, params = "SELECT data FROM ugc_trends WHERE run_id = ?", [run_id]
        if facet is not None:
            sql += " AND facet = ?"
            params.append(facet)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        return [FacetTrend.model_validate_json(r["data"]) for r in self.conn.execute(sql + " ORDER BY trend_id", params)]

    def replace_members(self, run_id: int, trend_ids: list[str], rows: list[tuple[str, str, float]]) -> None:
        """Replaces only the listed trends' members, so sounds and LLM facets are written separately."""
        self.conn.executemany("DELETE FROM ugc_trend_members WHERE run_id = ? AND trend_id = ?",
                              [(run_id, trend_id) for trend_id in trend_ids])
        self.conn.executemany(
            "INSERT INTO ugc_trend_members (run_id, trend_id, video_id, probability) VALUES (?, ?, ?, ?)",
            [(run_id, t, v, p) for t, v, p in rows])
        self.conn.commit()

    def facet_members(self, run_id: int) -> dict[str, dict[str, float]]:
        members: dict[str, dict[str, float]] = {}
        rows = self.conn.execute(
            "SELECT trend_id, video_id, probability FROM ugc_trend_members WHERE run_id = ? ORDER BY rowid", (run_id,))
        for r in rows:
            members.setdefault(r["trend_id"], {})[r["video_id"]] = r["probability"]
        return members

    # --- sounds -----------------------------------------------------------
    def upsert_sound(self, run_id: int, sound: SoundCandidate) -> None:
        self._write(
            """INSERT INTO ugc_sounds (run_id, sound_id, data, niche_creators, niche_share) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id, sound_id) DO UPDATE SET data = excluded.data,
                 niche_creators = excluded.niche_creators, niche_share = excluded.niche_share""",
            (run_id, sound.sound_id, sound.model_dump_json(), sound.niche_creators, sound.niche_share))

    def list_sounds(self, run_id: int) -> list[SoundCandidate]:
        rows = self.conn.execute("SELECT data FROM ugc_sounds WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [SoundCandidate.model_validate_json(r["data"]) for r in rows]

    def upsert_sound_sample(self, run_id: int, sound_id: str, video_id: str, relevant: float | None) -> None:
        self._write(
            """INSERT INTO ugc_sound_samples (run_id, sound_id, video_id, relevant) VALUES (?, ?, ?, ?)
               ON CONFLICT(run_id, sound_id, video_id) DO UPDATE SET relevant = excluded.relevant""",
            (run_id, sound_id, video_id, relevant))

    def sound_samples(self, run_id: int) -> dict[str, dict[str, float | None]]:
        samples: dict[str, dict[str, float | None]] = {}
        rows = self.conn.execute(
            "SELECT sound_id, video_id, relevant FROM ugc_sound_samples WHERE run_id = ? ORDER BY rowid", (run_id,))
        for r in rows:
            samples.setdefault(r["sound_id"], {})[r["video_id"]] = r["relevant"]
        return samples

    # --- scores and pairs -------------------------------------------------
    def replace_ugc_scores(self, run_id: int, scores: list[UgcTrendScore]) -> None:
        self.conn.execute("DELETE FROM ugc_trend_scores WHERE run_id = ?", (run_id,))
        self.conn.executemany(
            """INSERT INTO ugc_trend_scores (run_id, trend_id, facet, data, score, rank_overall, rank_in_facet)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(run_id, s.trend_id, s.facet, s.model_dump_json(), s.score, s.rank_overall, s.rank_in_facet)
             for s in scores])
        self.conn.commit()

    def list_ugc_scores(self, run_id: int) -> list[UgcTrendScore]:
        rows = self.conn.execute(
            "SELECT data FROM ugc_trend_scores WHERE run_id = ? ORDER BY rank_overall, trend_id", (run_id,))
        return [UgcTrendScore.model_validate_json(r["data"]) for r in rows]

    def replace_pairs(self, run_id: int, rows: list[tuple[str, str, float, float]]) -> None:
        self.conn.execute("DELETE FROM ugc_pairs WHERE run_id = ?", (run_id,))
        self.conn.executemany("INSERT INTO ugc_pairs (run_id, trend_id, partner_id, co, lift) VALUES (?, ?, ?, ?, ?)",
                              [(run_id, a, b, co, lift) for a, b, co, lift in rows])
        self.conn.commit()

    def pairs(self, run_id: int) -> dict[str, list[tuple[str, float, float]]]:
        result: dict[str, list[tuple[str, float, float]]] = {}
        rows = self.conn.execute(
            "SELECT trend_id, partner_id, co, lift FROM ugc_pairs WHERE run_id = ? ORDER BY trend_id, co DESC, partner_id",
            (run_id,))
        for r in rows:
            result.setdefault(r["trend_id"], []).append((r["partner_id"], r["co"], r["lift"]))
        return result

    # --- briefs and reviews -----------------------------------------------
    def upsert_ugc_brief(self, run_id: int, trend_id: str, model: str, brief: dict | None, status: str) -> None:
        self._write(
            """INSERT INTO ugc_briefs (run_id, trend_id, model, brief, status, created_at) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, trend_id) DO UPDATE SET model = excluded.model, brief = excluded.brief,
                 status = excluded.status, created_at = excluded.created_at""",
            (run_id, trend_id, model, json.dumps(brief) if brief is not None else None, status, _now()))

    def list_ugc_briefs(self, run_id: int) -> dict[str, dict]:
        rows = self.conn.execute("SELECT trend_id, brief, status FROM ugc_briefs WHERE run_id = ?", (run_id,))
        return {r["trend_id"]: {"status": r["status"], "brief": json.loads(r["brief"]) if r["brief"] else None}
                for r in rows}

    def add_review(self, run_id: int, trend_id: str, video_id: str, field: str, value: object) -> None:
        self._write(
            """INSERT INTO ugc_reviews (run_id, trend_id, video_id, field, value, reviewed_at) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, trend_id, video_id, field) DO UPDATE SET value = excluded.value,
                 reviewed_at = excluded.reviewed_at""",
            (run_id, trend_id, video_id, field, json.dumps(value), _now()))

    def list_reviews(self, run_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT trend_id, video_id, field, value FROM ugc_reviews WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [{"trend_id": r["trend_id"], "video_id": r["video_id"], "field": r["field"],
                 "value": json.loads(r["value"])} for r in rows]
