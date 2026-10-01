"""SQLite persistence (spec §8). JSON-valued columns are stored as TEXT."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from jevtrends.config import NicheConfig, Settings
from jevtrends.models import Answer, Enrichment, Trend, TrendScore, Video

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
  params TEXT NOT NULL, settings_snapshot TEXT NOT NULL, niches_snapshot TEXT NOT NULL,
  stage_status TEXT NOT NULL DEFAULT '{}', cost_by_provider TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_videos (
  run_id INTEGER NOT NULL, video_id TEXT NOT NULL, seed_queries TEXT NOT NULL DEFAULT '[]', short_id TEXT,
  PRIMARY KEY (run_id, video_id));
CREATE TABLE IF NOT EXISTS enrichments (
  video_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS judgments (
  run_id INTEGER NOT NULL, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, question_id TEXT NOT NULL,
  question_version INTEGER NOT NULL, value TEXT NOT NULL, probabilities TEXT, confidence REAL,
  created_at TEXT NOT NULL, PRIMARY KEY (run_id, subject_type, subject_id, question_id, question_version));
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
CREATE TABLE IF NOT EXISTS api_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, stage TEXT NOT NULL, provider TEXT NOT NULL,
  endpoint TEXT NOT NULL, units TEXT NOT NULL, cost_usd REAL NOT NULL, status TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS labels (
  video_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, stratum TEXT NOT NULL,
  labeled_at TEXT NOT NULL, PRIMARY KEY (video_id, field));
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(self.schema())
        self.conn.commit()

    def schema(self) -> str:
        """Tables to create; the UGC store adds its own (UGC spec §8)."""
        return SCHEMA

    def close(self) -> None:
        self.conn.close()

    def _write(self, sql: str, params: tuple = ()) -> None:
        self.conn.execute(sql, params)
        self.conn.commit()

    # --- runs -------------------------------------------------------------
    def create_run(self, params: dict, settings: BaseModel, niches: BaseModel, started_at: datetime) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, status, params, settings_snapshot, niches_snapshot) VALUES (?, ?, ?, ?, ?)",
            (started_at.isoformat(), "running", json.dumps(params), settings.model_dump_json(), niches.model_dump_json()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _run_row(self, run_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run {run_id} not found")
        return row

    def run_basics(self, run_id: int) -> dict:
        """Fields every pipeline's runs share; config snapshots are parsed by get_run."""
        row = self._run_row(run_id)
        return {"id": row["id"], "started_at": datetime.fromisoformat(row["started_at"]),
                "finished_at": row["finished_at"], "status": row["status"], "params": json.loads(row["params"]),
                "stage_status": json.loads(row["stage_status"])}

    def get_run(self, run_id: int) -> dict:
        row = self._run_row(run_id)
        return {**self.run_basics(run_id), "settings": Settings.model_validate_json(row["settings_snapshot"]),
                "niches": NicheConfig.model_validate_json(row["niches_snapshot"])}

    def list_runs(self) -> list[dict]:
        rows = self.conn.execute("SELECT id, started_at, status FROM runs ORDER BY id").fetchall()
        return [{"id": r["id"], "started_at": r["started_at"], "status": r["status"],
                 "cost_usd": self.total_spend(r["id"])} for r in rows]

    def set_run_status(self, run_id: int, status: str, finished: bool = False) -> None:
        self._write("UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                    (status, _now() if finished else None, run_id))

    def mark_stage_done(self, run_id: int, stage: str) -> None:
        status = self.run_basics(run_id)["stage_status"]
        status[stage] = "done"
        self._write("UPDATE runs SET stage_status = ? WHERE id = ?", (json.dumps(status), run_id))

    def stage_done(self, run_id: int, stage: str) -> bool:
        return self.run_basics(run_id)["stage_status"].get(stage) == "done"

    def add_note(self, run_id: int, note: str) -> None:
        params = self.run_basics(run_id)["params"]
        notes = params.setdefault("notes", [])
        if note not in notes:
            notes.append(note)
            self._write("UPDATE runs SET params = ? WHERE id = ?", (json.dumps(params), run_id))

    def notes(self, run_id: int) -> list[str]:
        return self.run_basics(run_id)["params"].get("notes", [])

    def mark_query_done(self, run_id: int, query: str) -> None:
        params = self.run_basics(run_id)["params"]
        done = params.setdefault("collect_done", [])
        if query not in done:
            done.append(query)
            self._write("UPDATE runs SET params = ? WHERE id = ?", (json.dumps(params), run_id))

    def done_queries(self, run_id: int) -> set[str]:
        return set(self.run_basics(run_id)["params"].get("collect_done", []))

    def query_counts(self, run_id: int) -> dict[str, int]:
        """Videos each seed query contributed, counting a video for the first query that found it."""
        counts: dict[str, int] = {}
        for row in self.conn.execute("SELECT seed_queries FROM run_videos WHERE run_id = ?", (run_id,)):
            queries = json.loads(row["seed_queries"])
            if queries:
                counts[queries[0]] = counts.get(queries[0], 0) + 1
        return counts

    # --- videos -----------------------------------------------------------
    def upsert_video(self, video: Video) -> None:
        self._write("INSERT INTO videos (id, data) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                    (video.id, video.model_dump_json()))

    def get_video(self, video_id: str) -> Video:
        row = self.conn.execute("SELECT data FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            raise KeyError(f"video {video_id} not found")
        return Video.model_validate_json(row["data"])

    def get_videos(self, ids: list[str]) -> dict[str, Video]:
        return {vid: self.get_video(vid) for vid in ids}

    def add_run_video(self, run_id: int, video_id: str, seed_query: str) -> None:
        row = self.conn.execute("SELECT seed_queries FROM run_videos WHERE run_id = ? AND video_id = ?",
                                (run_id, video_id)).fetchone()
        if row is None:
            self._write("INSERT INTO run_videos (run_id, video_id, seed_queries) VALUES (?, ?, ?)",
                        (run_id, video_id, json.dumps([seed_query])))
            return
        queries = json.loads(row["seed_queries"])
        if seed_query not in queries:
            queries.append(seed_query)
            self._write("UPDATE run_videos SET seed_queries = ? WHERE run_id = ? AND video_id = ?",
                        (json.dumps(queries), run_id, video_id))

    def run_video_ids(self, run_id: int) -> list[str]:
        rows = self.conn.execute("SELECT video_id FROM run_videos WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [r["video_id"] for r in rows]

    def set_short_id(self, run_id: int, video_id: str, short_id: str) -> None:
        self._write("UPDATE run_videos SET short_id = ? WHERE run_id = ? AND video_id = ?", (short_id, run_id, video_id))

    def short_ids(self, run_id: int) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT short_id, video_id FROM run_videos WHERE run_id = ? AND short_id IS NOT NULL", (run_id,))
        return {r["short_id"]: r["video_id"] for r in rows}

    # --- enrichments ------------------------------------------------------
    def upsert_enrichment(self, enrichment: Enrichment) -> None:
        self._write(
            "INSERT INTO enrichments (video_id, data) VALUES (?, ?) ON CONFLICT(video_id) DO UPDATE SET data = excluded.data",
            (enrichment.video_id, enrichment.model_dump_json()))

    def get_enrichment(self, video_id: str) -> Enrichment | None:
        row = self.conn.execute("SELECT data FROM enrichments WHERE video_id = ?", (video_id,)).fetchone()
        return Enrichment.model_validate_json(row["data"]) if row else None

    # --- judgments --------------------------------------------------------
    def upsert_judgment(self, run_id: int, subject_type: str, subject_id: str, question_id: str,
                        version: int, answer: Answer) -> None:
        self._write(
            """INSERT INTO judgments (run_id, subject_type, subject_id, question_id, question_version, value,
                                      probabilities, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, subject_type, subject_id, question_id, question_version) DO UPDATE SET
                 value = excluded.value, probabilities = excluded.probabilities,
                 confidence = excluded.confidence, created_at = excluded.created_at""",
            (run_id, subject_type, subject_id, question_id, version, json.dumps(answer.value),
             json.dumps(answer.probabilities) if answer.probabilities is not None else None,
             answer.confidence, _now()))

    def get_answers(self, run_id: int, subject_type: str, question_id: str, version: int) -> dict[str, Answer]:
        rows = self.conn.execute(
            """SELECT subject_id, value, probabilities, confidence FROM judgments
               WHERE run_id = ? AND subject_type = ? AND question_id = ? AND question_version = ?""",
            (run_id, subject_type, question_id, version))
        return {
            r["subject_id"]: Answer(value=json.loads(r["value"]),
                                    probabilities=json.loads(r["probabilities"]) if r["probabilities"] else None,
                                    confidence=r["confidence"])
            for r in rows
        }

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

    # --- spend ------------------------------------------------------------
    def record_api_call(self, run_id: int, stage: str, provider: str, endpoint: str, units: dict,
                        cost_usd: float, status: str) -> None:
        self._write(
            """INSERT INTO api_calls (run_id, stage, provider, endpoint, units, cost_usd, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, stage, provider, endpoint, json.dumps(units), cost_usd, status, _now()))

    def spend_by_provider(self, run_id: int) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT provider, SUM(cost_usd) AS total FROM api_calls WHERE run_id = ? GROUP BY provider ORDER BY provider",
            (run_id,))
        return {r["provider"]: round(r["total"], 6) for r in rows}

    def total_spend(self, run_id: int) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls WHERE run_id = ?", (run_id,)).fetchone()
        return float(row[0])

    def failures_by_stage(self, run_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT stage, COUNT(*) AS n FROM api_calls WHERE run_id = ? AND status = 'failed' GROUP BY stage ORDER BY stage",
            (run_id,))
        return {r["stage"]: r["n"] for r in rows}

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
