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


def summarize(graph, min_samples=5):
    """Compare fixed time-to-close entries and one-minute continuous buckets."""
    with graph._connect() as con:
        rows = con.execute(
            "SELECT market_id,observed_at,settled_at,features_json,actual_up "
            "FROM observations WHERE outcome IS NOT NULL AND actual_up IS NOT NULL "
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
    return {
        "method": "one_observation_per_contract_per_entry_bucket",
        "settled_contracts": len(contracts),
        "minimum_contracts_per_bucket": min_samples,
        "buckets": output,
        "best_entry_bucket": best["bucket"] if best else None,
        "best_entry_return_per_dollar": best["mean_return_per_dollar"] if best else None,
        "note": "Estimated spread-aware binary settlement returns from observed quotes; excludes fees, slippage and fill uncertainty. Use chronological holdout before selecting a live strategy.",
    }
