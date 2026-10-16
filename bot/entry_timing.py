"""Contract-aligned entry timing experiments using settled Connectome snapshots.

Each market contributes at most one observation per timing bucket. Results are
research estimates, not executable fills; spread-aware entry uses the observed
ask for the chosen outcome and assumes a binary $1 settlement payout.
"""
import json
from collections import defaultdict


TARGETS = [
    ("first_seen", None),
    ("10m", 600),
    ("5m", 300),
    ("3m", 180),
    ("1m", 60),
]


def summarize(graph, min_samples=30):
    """Compare fixed time-to-close entries and one-minute continuous buckets."""
    with graph._connect() as con:
        rows = con.execute(
            "SELECT market_id,observed_at,settled_at,features_json,actual_up FROM ("
            "SELECT market_id,observed_at,settled_at,features_json,actual_up FROM observations "
            "WHERE outcome IS NOT NULL AND actual_up IS NOT NULL "
            "AND settled_at IS NOT NULL AND market_id IS NOT NULL "
            "ORDER BY observed_at DESC LIMIT 50000) ORDER BY observed_at ASC"
        ).fetchall()

    contracts = defaultdict(list)
    for row in rows:
        try:
            f = json.loads(row["features_json"])
            remaining = float(f.get("_snapshot_time_remaining_seconds"))
            up_p = float(f.get("_forecast_up_probability"))
            if not (0.0 < up_p < 1.0) or remaining < 0:
                continue
            contracts[str(row["market_id"])].append({
                "observed_at": float(row["observed_at"]),
                "remaining": remaining,
                "features": f,
                "actual_up": bool(row["actual_up"]),
                "up_p": up_p,
            })
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    buckets = defaultdict(list)
    for market_id, snapshots in contracts.items():
        snapshots.sort(key=lambda x: x["observed_at"])
        # First observed quote after the contract is discovered.
        buckets["first_seen"].append(snapshots[0])
        for label, target in TARGETS[1:]:
            eligible = [s for s in snapshots if abs(s["remaining"] - target) <= 45]
            if eligible:
                buckets[label].append(min(eligible, key=lambda s: abs(s["remaining"] - target)))
        # A minute-by-minute profile reveals whether entry quality changes
        # throughout the contract. Each contract is counted once per minute bin.
        for target in range(840, 0, -60):
            eligible = [s for s in snapshots if abs(s["remaining"] - target) <= 30]
            if eligible:
                label = f"{int(target // 60)}m_remaining"
                buckets[label].append(min(eligible, key=lambda s: abs(s["remaining"] - target)))

    output = []
    for label, samples in buckets.items():
        if not samples:
            continue
        correct = 0
        brier = 0.0
        pnl = []
        for s in samples:
            f = s["features"]
            actual_up = s["actual_up"]
            up_p = s["up_p"]
            correct += int((up_p >= 0.5) == actual_up)
            brier += (up_p - int(actual_up)) ** 2
            # Estimate buying the selected outcome at the observed ask.
            # DOWN token ask is the complement of the UP bid.
            entry = f.get("_snapshot_ask") if up_p >= 0.5 else (
                1.0 - f.get("_snapshot_bid") if f.get("_snapshot_bid") is not None else None
            )
            if entry is None:
                continue
            try:
                entry = float(entry)
            except (TypeError, ValueError):
                continue
            if not (0.0 < entry < 1.0):
                continue
            pnl.append((1.0 / entry - 1.0) if ((up_p >= 0.5) == actual_up) else -1.0)
        n = len(samples)
        output.append({
            "bucket": label,
            "contracts": n,
            "accuracy": correct / n,
            "brier": brier / n,
            "priced_entries": len(pnl),
            "mean_return_per_dollar": sum(pnl) / len(pnl) if pnl else None,
            "positive_return_rate": sum(1 for x in pnl if x > 0) / len(pnl) if pnl else None,
            "eligible": n >= min_samples,
        })
    order = {label: i for i, (label, _) in enumerate(TARGETS)}
    output.sort(key=lambda x: (0, order[x["bucket"]]) if x["bucket"] in order else
                (1, -int(x["bucket"].split("m_")[0])))
    eligible = [x for x in output if x["eligible"] and x["mean_return_per_dollar"] is not None]
    best = max(eligible, key=lambda x: x["mean_return_per_dollar"]) if eligible else None
    # Evaluate explicit feature combinations, not only single timing indicators.
    # Select at most one snapshot per contract per checkpoint, then group contracts
    # by exact categorical signal combinations to avoid counting repeated refreshes.
    from itertools import combinations
    combo_fields = [
        ("midpoint", "midpoint_fine"), ("depth", "depth"),
        ("odds_momentum", "odds_momentum"), ("exchange_relationship", "exchange_relationship"),
        ("consensus", "consensus"), ("direction", "direction"),
    ]
    checkpoint_targets = [("10m", 600), ("5m", 300), ("3m", 180), ("1m", 60)]
    combo_groups = defaultdict(dict)
    for market_id, snapshots in contracts.items():
        snapshots.sort(key=lambda x: x["observed_at"])
        chosen = [("first_seen", snapshots[0])]
        for label, target in checkpoint_targets:
            eligible = [s for s in snapshots if abs(s["remaining"] - target) <= 45]
            if eligible:
                chosen.append((label, min(eligible, key=lambda s: abs(s["remaining"] - target))))
        for checkpoint, snap in chosen:
            f = snap["features"]
            available = [(name, f.get(key)) for name, key in combo_fields
                         if f.get(key) not in (None, "", "unknown", "unavailable")]
            for width in (2, 3):
                for fields in combinations(available, width):
                    names = tuple(x[0] for x in fields)
                    signature = tuple(str(x[1]) for x in fields)
                    combo_id = checkpoint + "|" + "|".join(
                        [name + "=" + value for name, value in zip(names, signature)])
                    existing = combo_groups[combo_id].get(market_id)
                    target = dict(checkpoint_targets).get(checkpoint, snap["remaining"])
                    sample = {"snapshot": snap, "checkpoint": checkpoint, "fields": list(names),
                              "signature": list(signature), "distance": abs(snap["remaining"] - target)}
                    if existing is None or sample["distance"] < existing["distance"]:
                        combo_groups[combo_id][market_id] = sample
    combo_candidates = []
    for combo_id, by_market in combo_groups.items():
        samples = [v["snapshot"] for v in by_market.values()]
        if not samples:
            continue
        correct = 0
        brier = 0.0
        pnl = []
        for sample in samples:
            f = sample["features"]
            actual_up = sample["actual_up"]
            up_p = sample["up_p"]
            predicted_up = up_p >= 0.5
            correct += int(predicted_up == actual_up)
            brier += (up_p - int(actual_up)) ** 2
            entry = f.get("_snapshot_ask") if predicted_up else (
                1.0 - f.get("_snapshot_bid") if f.get("_snapshot_bid") is not None else None)
            try:
                entry = float(entry) if entry is not None else None
            except (TypeError, ValueError):
                entry = None
            if entry is not None and 0.0 < entry < 1.0:
                pnl.append((1.0 / entry - 1.0) if predicted_up == actual_up else -1.0)
        n = len(samples)
        first = next(iter(by_market.values()))
        combo_candidates.append({
            "combo_key": combo_id, "checkpoint": first["checkpoint"],
            "features": [{"name": name, "value": value}
                         for name, value in zip(first["fields"], first["signature"])],
            "contracts": n, "accuracy": correct / n, "brier": brier / n,
            "priced_entries": len(pnl),
            "mean_return_per_dollar": sum(pnl) / len(pnl) if pnl else None,
            "positive_return_rate": sum(1 for x in pnl if x > 0) / len(pnl) if pnl else None,
            "eligible": n >= min_samples,
            "metric_source": "one_sample_per_settled_contract_exact_feature_combo_quote_estimate",
        })
    combo_candidates.sort(key=lambda x: (
        x["contracts"] >= min_samples, x["mean_return_per_dollar"] is not None,
        x["mean_return_per_dollar"] if x["mean_return_per_dollar"] is not None else -999,
        x["accuracy"], -x["brier"]), reverse=True)
    return {
        "method": "one_observation_per_contract_per_entry_bucket_plus_explicit_feature_combinations",
        "combo_candidates": combo_candidates,
        "settled_contracts": len(contracts),
        "minimum_contracts_per_bucket": min_samples,
        "buckets": output,
        "best_entry_bucket": best["bucket"] if best else None,
        "best_entry_return_per_dollar": best["mean_return_per_dollar"] if best else None,
        "note": "Estimated spread-aware binary settlement returns from observed quotes; excludes fees, slippage and fill uncertainty. Require at least 30 settled contracts per bucket before treating a ranking as eligible; these remain exploratory quote-based estimates, not verified fills, and exclude fees, slippage and latency.",
    }
