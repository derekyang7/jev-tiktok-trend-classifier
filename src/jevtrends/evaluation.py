"""Labeling sampler and quality metrics (spec §14.4)."""

import random

from jevtrends.jev.questions import IS_SIGNAL, MAYBE_SIGNAL, SIGNAL_TYPE, niche_question
from jevtrends.stages.context import RunContext
from jevtrends.stages.gate import gate_survivors
from jevtrends.stages.report import report_context
from jevtrends.store import Store

PRECISION_TARGET = 0.80


def is_borderline(ctx: RunContext, video_id: str) -> bool:
    low, high = ctx.settings.thresholds.borderline
    probs = [ctx.answers(IS_SIGNAL).get(video_id)] + [ctx.answers(niche_question(n)).get(video_id)
                                                     for n in ctx.niches.niches]
    return any(a is not None and low <= float(a.value) <= high for a in probs)


def sample_for_labeling(store: Store, run_id: int, n: int = 100, seed: int = 0) -> list[tuple[str, str]]:
    ctx = report_context(store, run_id)
    rng = random.Random(seed)
    labeled = {row["video_id"] for row in store.list_labels()}
    survivors = set(gate_survivors(ctx))
    gate_answers, signal_answers = ctx.answers(MAYBE_SIGNAL), ctx.answers(IS_SIGNAL)
    judged = [v for v in store.run_video_ids(run_id) if v in signal_answers and v not in labeled]
    dropped = [v for v in store.run_video_ids(run_id) if v in gate_answers and v not in survivors and v not in labeled]
    random_pick = rng.sample(judged, min(n // 2, len(judged)))
    borderline_pool = [v for v in judged if v not in random_pick and is_borderline(ctx, v)]
    borderline_pick = rng.sample(borderline_pool, min(n * 3 // 10, len(borderline_pool)))
    dropped_pick = rng.sample(dropped, min(n - n // 2 - n * 3 // 10, len(dropped)))
    return ([(v, "random") for v in random_pick] + [(v, "borderline") for v in borderline_pick]
            + [(v, "gate_dropped") for v in dropped_pick])


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _precision_recall(pairs: list[tuple[float, bool]], threshold: float) -> tuple[float | None, float | None]:
    tp = sum(p >= threshold and truth for p, truth in pairs)
    fp = sum(p >= threshold and not truth for p, truth in pairs)
    fn = sum(p < threshold and truth for p, truth in pairs)
    return _ratio(tp, tp + fp), _ratio(tp, tp + fn)


def compute_metrics(store: Store, run_id: int) -> dict:
    ctx = report_context(store, run_id)
    thresholds = ctx.settings.thresholds
    labels: dict[str, dict] = {}
    for row in store.list_labels():
        labels.setdefault(row["video_id"], {"stratum": row["stratum"]})[row["field"]] = row["value"]
    signal = {v: float(a.value) for v, a in ctx.answers(IS_SIGNAL).items()}
    types = {v: str(a.value) for v, a in ctx.answers(SIGNAL_TYPE).items()}
    niche_probs = {n.id: {v: float(a.value) for v, a in ctx.answers(niche_question(n)).items()}
                   for n in ctx.niches.niches}

    random_ids = [v for v, lab in labels.items() if lab["stratum"] == "random" and v in signal and "is_signal" in lab]
    pairs = [(signal[v], bool(labels[v]["is_signal"])) for v in random_ids]
    precision, recall = _precision_recall(pairs, thresholds.is_signal)

    tp = fp = fn = 0
    for v in random_ids:
        truth = set(labels[v].get("niches", []))
        for niche_id, probs in niche_probs.items():
            predicted = probs.get(v, 0.0) >= thresholds.niche_member
            tp += predicted and niche_id in truth
            fp += predicted and niche_id not in truth
            fn += (not predicted) and niche_id in truth

    dropped = [bool(lab["is_signal"]) for lab in labels.values() if lab["stratum"] == "gate_dropped" and "is_signal" in lab]
    typed = [v for v in random_ids if labels[v].get("is_signal") and "signal_type" in labels[v] and v in types]

    best = None
    for threshold in (round(0.05 * i, 2) for i in range(1, 20)):
        p, r = _precision_recall(pairs, threshold)
        if p is not None and p >= PRECISION_TARGET and r is not None and (best is None or r > best[1]):
            best = (threshold, r)

    calibration = []
    judged_labeled = [(signal[v], bool(lab["is_signal"])) for v, lab in labels.items() if v in signal and "is_signal" in lab]
    for low in (0.0, 0.2, 0.4, 0.6, 0.8):
        bucket = [(p, t) for p, t in judged_labeled if low <= p < low + 0.2 or (low == 0.8 and p == 1.0)]
        calibration.append({"range": f"{low:.1f}-{low + 0.2:.1f}", "count": len(bucket),
                            "predicted": _ratio(sum(p for p, _ in bucket), len(bucket)) if bucket else None,
                            "observed": _ratio(sum(t for _, t in bucket), len(bucket))})
    return {
        "labeled_random": len(random_ids),
        "is_signal": {"threshold": thresholds.is_signal, "precision": precision, "recall": recall},
        "niches": {"threshold": thresholds.niche_member, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)},
        "gate_miss_rate": _ratio(sum(dropped), len(dropped)),
        "signal_type_accuracy": _ratio(sum(types[v] == labels[v]["signal_type"] for v in typed), len(typed)),
        "suggested_is_signal_threshold": best[0] if best else None,
        "calibration": calibration,
    }
