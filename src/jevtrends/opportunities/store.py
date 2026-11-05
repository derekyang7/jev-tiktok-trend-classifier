"""SQLite persistence for startup opportunities: core tables plus trend, brief and label tables (spec §8)."""

import json

from jevtrends.core.store import CORE_SCHEMA, Store, _now
from jevtrends.opportunities.config import NicheConfig, Settings
from jevtrends.opportunities.models import Trend, TrendScore

OPPORTUNITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trends (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL,
  PRIMARY KEY (run_id, trend_id));
CREATE TABLE IF NOT EXISTS trend_members (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, video_id TEXT NOT NULL, probability REAL NOT NULL,
  PRIMARY KEY (run_id, trend_id, video_id));
CREATE TABLE IF NOT EXISTS trend_scores (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, data TEXT NOT NULL, opportunity REAL NOT NULL,
  rank INTEGER NOT NULL, PRIMARY KEY (run_id, trend_id));
CREATE TABLE IF NOT EXISTS briefs (
  run_id INTEGER NOT NULL, trend_id TEXT NOT NULL, model TEXT NOT NULL, brief TEXT, status TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (run_id, trend_id));
CREATE TABLE IF NOT EXISTS labels (
  video_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, stratum TEXT NOT NULL,
  labeled_at TEXT NOT NULL, PRIMARY KEY (video_id, field));
"""


class OpportunitiesStore(Store):
    def schema(self) -> str:
        return CORE_SCHEMA + OPPORTUNITIES_SCHEMA

    def get_run(self, run_id: int) -> dict:
        row = self._run_row(run_id)
        return {**self.run_basics(run_id), "settings": Settings.model_validate_json(row["settings_snapshot"]),
                "niches": NicheConfig.model_validate_json(row["niches_snapshot"])}

    # --- trends -----------------------------------------------------------
    def upsert_trend(self, run_id: int, trend: Trend) -> None:
        self._write(
            """INSERT INTO trends (run_id, trend_id, data, status) VALUES (?, ?, ?, ?)
               ON CONFLICT(run_id, trend_id) DO UPDATE SET data = excluded.data, status = excluded.status""",
            (run_id, trend.trend_id, trend.model_dump_json(), trend.status))

    def list_trends(self, run_id: int, status: str | None = None) -> list[Trend]:
        sql, params = "SELECT data FROM trends WHERE run_id = ?", [run_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        rows = self.conn.execute(sql + " ORDER BY trend_id", params)
        return [Trend.model_validate_json(r["data"]) for r in rows]

    def replace_trend_members(self, run_id: int, rows: list[tuple[str, str, float]]) -> None:
        self.conn.execute("DELETE FROM trend_members WHERE run_id = ?", (run_id,))
        self.conn.executemany("INSERT INTO trend_members (run_id, trend_id, video_id, probability) VALUES (?, ?, ?, ?)",
                              [(run_id, t, v, p) for t, v, p in rows])
        self.conn.commit()

    def trend_members(self, run_id: int) -> dict[str, dict[str, float]]:
        members: dict[str, dict[str, float]] = {}
        for r in self.conn.execute("SELECT trend_id, video_id, probability FROM trend_members WHERE run_id = ?", (run_id,)):
            members.setdefault(r["trend_id"], {})[r["video_id"]] = r["probability"]
        return members

    def upsert_trend_score(self, run_id: int, score: TrendScore) -> None:
        self._write(
            """INSERT INTO trend_scores (run_id, trend_id, data, opportunity, rank) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id, trend_id) DO UPDATE SET data = excluded.data,
                 opportunity = excluded.opportunity, rank = excluded.rank""",
            (run_id, score.trend_id, score.model_dump_json(), score.opportunity, score.rank))

    def list_trend_scores(self, run_id: int) -> list[TrendScore]:
        rows = self.conn.execute(
            "SELECT data FROM trend_scores WHERE run_id = ? ORDER BY rank, opportunity DESC", (run_id,))
        return [TrendScore.model_validate_json(r["data"]) for r in rows]

    # --- briefs -----------------------------------------------------------
    def upsert_brief(self, run_id: int, trend_id: str, model: str, brief: dict | None, status: str) -> None:
        self._write(
            """INSERT INTO briefs (run_id, trend_id, model, brief, status, created_at) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, trend_id) DO UPDATE SET model = excluded.model, brief = excluded.brief,
                 status = excluded.status, created_at = excluded.created_at""",
            (run_id, trend_id, model, json.dumps(brief) if brief is not None else None, status, _now()))

    def list_briefs(self, run_id: int) -> dict[str, dict]:
        rows = self.conn.execute("SELECT trend_id, brief, status FROM briefs WHERE run_id = ?", (run_id,))
        return {r["trend_id"]: {"status": r["status"], "brief": json.loads(r["brief"]) if r["brief"] else None}
                for r in rows}

    # --- labels -----------------------------------------------------------
    def add_label(self, video_id: str, field: str, value: object, stratum: str) -> None:
        self._write(
            """INSERT INTO labels (video_id, field, value, stratum, labeled_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(video_id, field) DO UPDATE SET value = excluded.value, stratum = excluded.stratum,
                 labeled_at = excluded.labeled_at""",
            (video_id, field, json.dumps(value), stratum, _now()))

    def list_labels(self) -> list[dict]:
        rows = self.conn.execute("SELECT video_id, field, value, stratum FROM labels ORDER BY video_id, field")
        return [{"video_id": r["video_id"], "field": r["field"], "value": json.loads(r["value"]),
                 "stratum": r["stratum"]} for r in rows]
