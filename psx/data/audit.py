"""PSX data audit (research/psx/DATA_PSX.md). DATA QUALITY ONLY: no strategy or portfolio returns.

Reads the write-once raw files in data/psx/raw/, writes research/psx/data_audit.json (counts only)
and the derived panels data/psx/derived/{closing,adjusted,histories}.parquet (gitignored).

Two price sources from dps.psx.com.pk:
  closing files  mkt_summary/<day>.Z: every instrument traded that day, with LDCP and ex-flags;
                 survivorship-free, because delisted names appear for as long as they traded.
  histories      historical/<snapshot>/<symbol>.html: unadjusted daily OHLCV per symbol.
Prices in Rs per share; traded value = close x volume in Rs (no turnover column in the source).

    venv\\Scripts\\python.exe -m psx.data.audit --snapshot 2026-10-14
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from psx.data.download import INDEX, KNOWN_DELISTED, RAW, REPO, safe_name
from psx.data.parse import company_status, parse_historical, parse_mkt_summary, parse_payouts

DERIVED = REPO / "data" / "psx" / "derived"
OUT_JSON = REPO / "research" / "psx" / "data_audit.json"
YEARS = range(2000, 2027)
MIN_PRICE_RS, MIN_VALUE_RS = 10.0, 5e6
LIMIT_FLOOR_RS = 1.0                    # PSX band: a percentage of LDCP or Rs 1, whichever is higher
REF_TOL = 0.005                         # LDCP counts as "adjusted" when it differs from the last close by > 0.5 %
NEAR_DAYS = 3                           # ex-flag within this many trading days of a move explains it
CANDIDATE_LIMITS = (0.05, 0.075, 0.10)  # daily price limits PSX is known to have used
STOPPED_BEFORE = pd.Timestamp("2026-07-01")   # no trade since: delisted, merged, renamed or long suspended
NON_EQUITY_SECTORS = ("BILLS AND BONDS", "EXCHANGE TRADED FUNDS", "CLOSE - END MUTUAL FUND", "FUTURE")


# ---------------------------------------------------------------- loading
def load_closing(raw: Path = RAW) -> tuple[pd.DataFrame, dict]:
    """All closing files, dated by their lines. A file whose lines carry another date (the server answers
    some holidays with a neighbouring day's file) is reported; its rows are kept only for (symbol, day)
    pairs that no correctly named file supplies."""
    frames, odd, formats = [], [], {"gzip": 0, "zip": 0, "plain": 0}
    for p in sorted((raw / "mkt_summary").glob("*.Z")):
        body = p.read_bytes()
        formats["gzip" if body[:2] == b"\x1f\x8b" else "zip" if body[:4] == b"PK\x03\x04" else "plain"] += 1
        df = parse_mkt_summary(body)
        named = pd.Timestamp(p.stem)
        df["named_ok"] = df["date"] == named
        if not df["named_ok"].all():
            odd.append({"file": p.name, "line_dates": sorted({str(d.date()) for d in df.loc[~df["named_ok"], "date"]}),
                        "rows": int((~df["named_ok"]).sum())})
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).sort_values(["symbol", "date", "named_ok"])
    info = {"formats": formats, "mislabelled_files": odd,
            "duplicate_rows_within_correct_files": int(out[out["named_ok"]].duplicated(["symbol", "date"]).sum())}
    out = out.drop_duplicates(["symbol", "date"], keep="last").drop(columns="named_ok")
    return out.sort_values(["date", "symbol"]).reset_index(drop=True), info


def load_histories(raw: Path, snapshot: str, symbols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Stored histories of `symbols`, and the symbols whose stored response held no rows."""
    frames, empty = [], []
    for s in symbols:
        p = raw / "historical" / snapshot / f"{safe_name(s)}.html"
        if p.exists():
            h = parse_historical(p.read_text(encoding="utf-8"))
            if h.empty:
                empty.append(s)
            else:
                frames.append(h.assign(symbol=s))
    return pd.concat(frames, ignore_index=True)[["symbol", "date", "open", "high", "low", "close", "volume"]], empty


def load_payouts(raw: Path, snapshot: str) -> pd.DataFrame:
    pages = sorted((raw / "payouts" / snapshot).glob("offset_*.html"))
    return pd.concat([parse_payouts(p.read_text(encoding="utf-8")) for p in pages], ignore_index=True)


# ---------------------------------------------------------------- universe
def sector_names(closing: pd.DataFrame, listed: pd.DataFrame) -> dict[str, str]:
    """Closing-file sector code -> sector name: the most common current sector of the listed symbols
    that ever carried the code (PSX renumbered its sector codes, so old codes map through the same symbols)."""
    pairs = closing[["symbol", "sector_code"]].drop_duplicates()
    pairs = pairs.merge(listed[["symbol", "sectorName"]].dropna(), on="symbol")
    return pairs.groupby("sector_code")["sectorName"].agg(lambda x: x.value_counts().index[0]).to_dict()


def listed_flag(listed: pd.DataFrame, col: str) -> pd.Series:
    """A boolean column of the /symbols list (PSX omits it when False)."""
    if col not in listed:
        return pd.Series(False, index=listed.index)
    return listed[col].astype("object").where(listed[col].notna(), False).astype(bool)


def derived_symbols(symbols: pd.Series, names: pd.Series) -> pd.Series:
    """Letters of right and preference shares: an existing symbol plus a suffix R, R1.., PS, CPS, NCPS, PSA
    (e.g. JSBLR1, SGMLPS, TCORPCPS), or a name marked '(R)' / 'right' / '(Pref'."""
    known = set(symbols)
    m = symbols.str.extract(r"^(?P<base>.+?)(?P<suffix>R\d?|NCPS|CPS|PSA|PS)$")
    by_symbol = m["base"].isin(known) & m["base"].ne(symbols)
    by_name = names.str.contains(r"\(R\)|\bright\b|\(Pref|Pref\.|\bPREF\b", case=False, regex=True)
    return by_symbol | by_name


def equity_mask(closing: pd.DataFrame, listed: pd.DataFrame) -> pd.Series:
    """Ordinary shares: no futures ('-' symbols, sector 40), debt, ETFs, closed-end funds, letters of right
    or preference shares."""
    names = sector_names(closing, listed)
    sector = closing["sector_code"].map(names).fillna("")
    nonequity = set(listed.loc[listed_flag(listed, "isDebt") | listed_flag(listed, "isETF"), "symbol"])
    bad_sector = sector.str.upper().str.contains("|".join(re.escape(s) for s in NON_EQUITY_SECTORS))
    return ((closing["sector_code"] != "40") & ~closing["symbol"].str.contains("-") & ~bad_sector
            & ~closing["symbol"].isin(nonequity) & ~derived_symbols(closing["symbol"], closing["name"]))


# ---------------------------------------------------------------- adjusted series (forward-chained)
def adjusted(closing_eq: pd.DataFrame, limits: pd.Series | float = CANDIDATE_LIMITS[-1]) -> pd.DataFrame:
    """Per symbol, chain prices forward from the first row, zero-volume rows included (they carry PSX's
    official close for a day without trades, which the next LDCP refers to). The step is close / LDCP,
    taking the exchange's reference adjustment out, when
      ex_flag       the day carries XD / XB / XR (dividend, bonus, right), or
      beyond_limit  LDCP differs from the last close by more than the price limit allows over the elapsed
                    weekdays (splits and consolidations, which carry no flag);
    otherwise close / last close: there an LDCP that differs from the last close means a missing closing
    file or an official-close update, not a corporate action (ldcp_mismatch_unflagged). Rows for day t use
    only rows up to t (no back-adjustment, so truncation never changes a past value)."""
    df = (closing_eq[closing_eq["close"] > 0].sort_values(["symbol", "date", "volume"])
          .drop_duplicates(["symbol", "date"], keep="last").reset_index(drop=True))
    prev = df.groupby("symbol")["close"].shift(1)
    prev_date = df.groupby("symbol")["date"].shift(1)
    df["prev_close"] = prev
    first = prev.isna()
    ok_ref = df["ldcp"] > 0
    flag = df["xd"] | df["xb"] | df["xr"]
    k = np.where(first, 1, np.busday_count(prev_date.fillna(df["date"]).values.astype("datetime64[D]"),
                                           df["date"].values.astype("datetime64[D]")))
    pct = limits if np.isscalar(limits) else df["date"].map(limits).fillna(CANDIDATE_LIMITS[-1]).to_numpy()
    allowed = np.maximum(((1 + pct) ** np.maximum(k, 1) - 1) * prev, LIMIT_FLOOR_RS * np.maximum(k, 1)) * 1.005 + 0.01
    beyond = ~first & ok_ref & ((df["ldcp"] - prev).abs() > allowed)
    use_ref = ~first & ok_ref & (flag | beyond)
    step = np.where(first, 1.0, np.where(use_ref, df["close"] / df["ldcp"], df["close"] / prev))
    moved = (df["ldcp"] / prev - 1).abs() > REF_TOL
    df["ref_reason"] = np.where(use_ref & flag, "ex_flag", np.where(use_ref, "beyond_limit", ""))
    df["ref_adjusted"] = use_ref & moved
    df["ldcp_mismatch_unflagged"] = ~first & ~use_ref & moved
    df["adj_factor"] = np.where(use_ref, df["ldcp"] / prev, 1.0)
    first_close = df.groupby("symbol")["close"].transform("first")
    df["adj_close"] = first_close * pd.Series(step, index=df.index).groupby(df["symbol"]).cumprod()
    return df


# ---------------------------------------------------------------- price limit
def ref_moves(closing_eq: pd.DataFrame) -> pd.DataFrame:
    """close / LDCP - 1 on traded rows: the move the exchange's circuit breaker is applied to."""
    df = closing_eq[(closing_eq["volume"] > 0) & (closing_eq["ldcp"] > 0)].copy()
    df["move"] = df["close"] / df["ldcp"] - 1
    return df


def limit_table(moves: pd.DataFrame, min_ref: float = 20.0) -> dict:
    """Per year, for LDCP >= min_ref (where the percentage band binds): share of |move| beyond
    candidate limits and the number of closes within 0.05 pp of each limit (lock-ups pile up there)."""
    m = moves[moves["ldcp"] >= min_ref]
    out = {}
    for y, g in m.groupby(m["date"].dt.year):
        a = g["move"].abs()
        out[int(y)] = {"n": int(len(a)), "p99_9_abs_move": float(a.quantile(0.999)), "max_abs_move": float(a.max()),
                       **{f"beyond_{c:g}": int((a > c + 0.0005).sum()) for c in CANDIDATE_LIMITS},
                       **{f"at_{c:g}": int(((a - c).abs() <= 0.0005).sum()) for c in CANDIDATE_LIMITS}}
    return out


def observed_limits(moves: pd.DataFrame, days: pd.DatetimeIndex, min_ref: float = 20.0,
                    window: int = 20) -> pd.Series:
    """Per trading day, the observed price limit: the smallest candidate that covers the day's largest
    |close / LDCP - 1| among LDCP >= min_ref (where the Rs 1 floor never binds), then the maximum over
    the trailing `window` trading days, so quiet days do not lower it. Uses each day and earlier days only."""
    m = moves[moves["ldcp"] >= min_ref]
    day_max = m["move"].abs().groupby(m["date"]).max().reindex(days)
    cover = lambda x: next((c for c in CANDIDATE_LIMITS if x <= c + 0.0005), CANDIDATE_LIMITS[-1])
    implied = day_max.map(lambda x: cover(x) if pd.notna(x) else np.nan)
    return implied.rolling(window, min_periods=1).max().ffill().fillna(CANDIDATE_LIMITS[-1]).astype(float)


def floor_check(moves: pd.DataFrame, limits: pd.Series) -> dict:
    """Where the percentage band is under Rs 1 (low LDCP): how many closes moved more than the percentage
    allows (so the Rs 1 floor is real), and the largest such move in Rs."""
    pct = moves["date"].map(limits)
    low = moves[pct * moves["ldcp"] < LIMIT_FLOOR_RS]
    d = (low["close"] - low["ldcp"]).abs()
    beyond_pct = d > (pct[low.index] * low["ldcp"]) * 1.005 + 0.01
    return {"rows_with_pct_band_under_rs1": int(len(low)), "moved_more_than_pct": int(beyond_pct.sum()),
            "max_move_rs": float(d.max()) if len(d) else None, "moved_more_than_rs1": int((d > LIMIT_FLOOR_RS + 0.01).sum())}


def limit_rs(ref: pd.Series, pct) -> pd.Series:
    return np.maximum(pct * ref, LIMIT_FLOOR_RS)


def breaches(hist: pd.DataFrame, limits, calendar: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Consecutive-row moves in the unadjusted histories larger than one day's band around the previous
    close (with half a percent and one tick of rounding slack). `limits`: one fraction, or a Series of the
    day's limit by date (observed_limits). `gap`: trading days between the two rows on `calendar`
    (1 = a single-day move). Uses rows up to t only."""
    h = hist[(hist["close"] > 0)].sort_values(["symbol", "date"]).copy()
    h["prev_close"] = h.groupby("symbol")["close"].shift(1)
    h["prev_date"] = h.groupby("symbol")["date"].shift(1)
    h = h.dropna(subset=["prev_close"])
    pct = limits if np.isscalar(limits) else h["date"].map(limits).fillna(CANDIDATE_LIMITS[-1]).to_numpy()
    lim = limit_rs(h["prev_close"], pct) * 1.005 + 0.01
    out = h[(h["close"] - h["prev_close"]).abs() > lim].copy()
    out["move"] = out["close"] / out["prev_close"] - 1
    if calendar is None:
        out["gap"] = 1
    else:
        pos = pd.Series(np.arange(len(calendar)), index=calendar)
        out["gap"] = (pos.reindex(out["date"]).to_numpy() - pos.reindex(out["prev_date"]).to_numpy())
    return out[["symbol", "date", "prev_date", "prev_close", "close", "move", "gap"]].reset_index(drop=True)


def classify(br: pd.DataFrame, adj: pd.DataFrame, payouts: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """Ex-post label for each breach (audit only; looks NEAR_DAYS ahead on purpose):
    exchange_adjusted  the exchange moved LDCP that day: an ex-date (XD/XB/XR) or a split/consolidation
    ex_flag_nearby     an XD/XB/XR flag for the symbol within NEAR_DAYS trading days
    payout_window      a payouts-listing book closure starting within 10 days after the move
    after_gap          not a single-day move: the symbol had no history row on the trading days between
    not_in_closing     the symbol has no closing-file row that day (cannot be checked)
    source_mismatch    closing-file close differs from the history's close by > 0.5 %
    history_prev_differs  the history's previous close differs from the closing file's official close
                       that day by > 0.5 % (seen on days without trades)
    unexplained        none of the above"""
    pos = pd.Series(np.arange(len(days)), index=days)
    a = adj.set_index(["symbol", "date"])
    flags = adj[adj["xd"] | adj["xb"] | adj["xr"]]
    flag_pos = {s: pos.reindex(g["date"]).dropna().to_numpy() for s, g in flags.groupby("symbol")}
    pay = {s: g for s, g in payouts.dropna(subset=["bc_from"]).groupby("symbol")}
    out = []
    for r in br.itertuples(index=False):
        key = (r.symbol, r.date)
        row = a.loc[key] if key in a.index else None
        p = pos.get(r.date)
        if row is not None and bool(row["ref_adjusted"]):
            out.append("exchange_adjusted")
        elif p is not None and r.symbol in flag_pos and np.any(np.abs(flag_pos[r.symbol] - p) <= NEAR_DAYS):
            out.append("ex_flag_nearby")
        elif r.symbol in pay and ((pay[r.symbol]["bc_from"] - r.date).dt.days.between(0, 10)).any():
            out.append("payout_window")
        elif getattr(r, "gap", 1) > 1:
            out.append("after_gap")
        elif row is None:
            out.append("not_in_closing")
        elif abs(row["close"] / r.close - 1) > 0.005:
            out.append("source_mismatch")
        elif ((r.symbol, getattr(r, "prev_date", None)) in a.index
              and abs(a.loc[(r.symbol, r.prev_date), "close"] / r.prev_close - 1) > 0.005):
            out.append("history_prev_differs")
        else:
            out.append("unexplained")
    return pd.Series(out, index=br.index, dtype="object")


def payout_pct(details: str, tag: str) -> float | None:
    """Percentage of face value attached to a (D) or (B) tag, e.g. '30%(i) (D) - 50% (B)' -> D 30, B 50."""
    m = re.search(r"([\d.]+)\s*%\s*(?:\([ivxIVXF]+\)\s*)?\(" + tag + r"\)", details)
    if m is None and tag == "D":
        m = re.search(r"DIVIDEND\s*=\s*([\d.]+)\s*%", details, flags=re.I)
    return float(m.group(1)) if m else None


def payout_check(adj: pd.DataFrame, payouts: pd.DataFrame, face_rs: float = 10.0) -> dict:
    """Does the exchange's LDCP reduction have the announced size? For each payout with a book closure,
    the last LDCP-reduced day carrying the matching flag (XB / XD) in [bc_from - 7 days, bc_from + 1 day]:
    bonus b % -> last close / LDCP ~ 1 + b/100
    (within 2 %); cash dividend d % -> last close - LDCP ~ d/100 x Rs 10 face value (within Rs 0.05)."""
    ev = adj[adj["ref_adjusted"]]
    res = {"bonus": {"n": 0, "ex_day_found": 0, "size_matches": 0},
           "dividend": {"n": 0, "ex_day_found": 0, "size_matches": 0}}
    for p in payouts.dropna(subset=["bc_from"]).itertuples(index=False):
        for kind, tag in (("bonus", "B"), ("dividend", "D")):
            if not getattr(p, kind) or (pct := payout_pct(p.details, tag)) is None:
                continue
            res[kind]["n"] += 1
            e = ev[(ev["symbol"] == p.symbol) & ev["xb" if kind == "bonus" else "xd"]
                   & ev["date"].between(p.bc_from - pd.Timedelta(days=7), p.bc_from + pd.Timedelta(days=1))]
            if e.empty:
                continue
            res[kind]["ex_day_found"] += 1
            e = e.iloc[-1]                                   # nearest to the book closure
            if kind == "bonus":
                ok = abs(e["prev_close"] / e["ldcp"] / (1 + pct / 100) - 1) <= 0.02
            else:
                ok = abs((e["prev_close"] - e["ldcp"]) - pct / 100 * face_rs) <= 0.05
            res[kind]["size_matches"] += int(ok)
    return res


# ---------------------------------------------------------------- liquidity and coverage
def liquidity_by_year(closing_eq: pd.DataFrame, days: pd.DatetimeIndex) -> dict[int, dict]:
    """Per year: equity symbols traded, and those with median close >= Rs 10 (traded days) and median
    daily traded value >= Rs 5 m over all the year's trading days (zero when not traded)."""
    df = closing_eq[closing_eq["volume"] > 0].assign(value=lambda x: x["close"] * x["volume"])
    out = {}
    for y, g in df.groupby(df["date"].dt.year):
        n_days = int((days.year == y).sum())
        def ok(s):
            vals = np.concatenate([s["value"].to_numpy(), np.zeros(max(n_days - len(s), 0))])
            return s["close"].median() >= MIN_PRICE_RS and np.median(vals) >= MIN_VALUE_RS
        flags = g.groupby("symbol")[["close", "value"]].apply(ok)
        out[int(y)] = {"trading_days": n_days, "traded_symbols": int(len(flags)), "liquid": int(flags.sum())}
    return out


def per_year_counts(df: pd.DataFrame) -> dict[int, int]:
    """Distinct symbols with at least one row in each year 2000-2026 (0 before the source starts)."""
    s = df.assign(y=df["date"].dt.year).groupby("y")["symbol"].nunique()
    return {y: int(s.get(y, 0)) for y in YEARS}


def possible_renames(adj: pd.DataFrame, days: pd.DatetimeIndex) -> list[tuple[str, str, str]]:
    """(old, new, day): old's last trade is the trading day before new's first, same sector, and new's
    first LDCP within 2 % of old's last close (a symbol change, not a delisting)."""
    pos = pd.Series(np.arange(len(days)), index=days)
    g = adj.sort_values("date").groupby("symbol")
    first, last = g.head(1).set_index("symbol"), g.tail(1).set_index("symbol")
    end_pos = pos.reindex(last["date"]).to_numpy()
    out = []
    for new, f in first.iterrows():
        p = pos.get(f["date"])
        if p is None or p == 0:
            continue
        cand = last[(end_pos == p - 1) & (last["sector_code"] == f["sector_code"]) & (last.index != new)]
        cand = cand[(f["ldcp"] / cand["close"] - 1).abs() < 0.02]
        out += [(old, new, str(f["date"].date())) for old in cand.index]
    return out


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", required=True)
    snap = ap.parse_args(argv).snapshot
    listed = pd.DataFrame(json.loads((RAW / "symbols" / f"{snap}.json").read_bytes()))
    closing, closing_info = load_closing()
    days = pd.DatetimeIndex(sorted(closing["date"].unique()))
    eq = closing[equity_mask(closing, listed)].copy()
    moves = ref_moves(eq)
    limits = observed_limits(moves, days)
    adj = adjusted(eq, limits)
    listed_set = set(listed["symbol"])
    unlisted = sorted(set(eq["symbol"]) - listed_set)
    hist_all, hist_empty = load_histories(RAW, snap, sorted(set(listed["symbol"]) | {INDEX} | set(unlisted)))
    hist = hist_all[hist_all["date"] <= days[-1]]               # histories run to today; closing files to snapshot - 1
    payouts = load_payouts(RAW, snap)
    DERIVED.mkdir(parents=True, exist_ok=True)
    closing.to_parquet(DERIVED / "closing.parquet", index=False)
    adj.to_parquet(DERIVED / "adjusted.parquet", index=False)
    hist.to_parquet(DERIVED / "histories.parquet", index=False)

    res: dict = {"snapshot": snap, "note": "data quality only; no strategy or portfolio returns computed"}
    eq_syms = set(eq["symbol"])
    h_eq = hist[hist["symbol"].isin(eq_syms)]
    first_h = h_eq.groupby("symbol")["date"].min()
    res["sources"] = {
        "closing_files": {"files": int(len(days)), "first": str(days[0].date()), "last": str(days[-1].date()),
                          "rows": int(len(closing)), "equity_symbols": len(eq_syms)},
        "histories": {"symbols_with_rows": int(hist["symbol"].nunique()), "symbols_empty": len(hist_empty),
                      "equity_symbols_empty": len(set(hist_empty) & set(eq["symbol"])), "rows": int(len(hist)),
                      "first": str(hist["date"].min().date()), "last_served": str(hist_all["date"].max().date()),
                      "rolling_window_note": "served history starts ten years before the request date",
                      "equity_symbols_with_rows": int(len(first_h)),
                      "equity_earliest_date_by_year": {int(k): int(v) for k, v in first_h.dt.year.value_counts().sort_index().items()},
                      "equity_symbols_starting_on_first_day": int((first_h == hist["date"].min()).sum())},
        "listed_now": {"symbols": int(len(listed)), "debt": int(listed_flag(listed, "isDebt").sum()),
                       "etf": int(listed_flag(listed, "isETF").sum()),
                       "equity_symbols_traded_in_closing_files": len(eq_syms & set(listed["symbol"]))},
        "closing_file_checks": closing_info,
        "excluded_rights_and_preference_symbols": int(closing.loc[derived_symbols(closing["symbol"], closing["name"]),
                                                                  "symbol"].nunique()),
        "payouts_listing": {"rows": int(len(payouts)), "first_announced": str(payouts["announced"].min()),
                            "last_announced": str(payouts["announced"].max()),
                            "dividend": int(payouts["dividend"].sum()), "bonus": int(payouts["bonus"].sum()),
                            "right": int(payouts["right"].sum())},
    }
    res["symbols_per_year"] = {"closing_files_equity": per_year_counts(eq[eq["volume"] > 0]),
                               "histories_equity": per_year_counts(h_eq[h_eq["volume"].fillna(0) > 0])}

    # survivorship
    last_trade = adj.groupby("symbol")["date"].max()
    renames = possible_renames(adj, days)
    h_syms = set(hist.loc[hist["close"].notna(), "symbol"])
    known = {}
    for s in KNOWN_DELISTED:
        c = adj[adj["symbol"] == s]
        hs = hist[hist["symbol"] == s]
        cp = RAW / "company" / snap / f"{safe_name(s)}.html"
        known[s] = {"closing_first": str(c["date"].min().date()) if len(c) else None,
                    "closing_last": str(c["date"].max().date()) if len(c) else None,
                    "history_rows": int(len(hs)), "history_last": str(hs["date"].max().date()) if len(hs) else None,
                    "listed_now": s in listed_set,
                    "company_badge": company_status(cp.read_text(encoding="utf-8")) if cp.exists() else None}
    traded = adj[adj["volume"] > 0]
    last_traded = traded.groupby("symbol")["date"].max()
    first_traded = traded.groupby("symbol")["date"].min()
    stopped = last_traded[last_traded < STOPPED_BEFORE]
    res["survivorship"] = {
        "equity_symbols_traded": int(len(last_traded)),
        f"stopped_trading_before_{STOPPED_BEFORE.date()}": int(len(stopped)),
        "stopped_by_year_of_last_trade": {int(k): int(v) for k, v in stopped.dt.year.value_counts().sort_index().items()},
        "stopped_after_history_start_with_history_served": int(len(set(stopped[stopped >= hist["date"].min()].index) & h_syms)),
        "stopped_after_history_start": int((stopped >= hist["date"].min()).sum()),
        "closing_first_trade_by_year": {int(k): int(v) for k, v in first_traded.dt.year.value_counts().sort_index().items()},
        "equity_symbols_not_listed_now": len(unlisted),
        "of_which_history_served": int(len(set(unlisted) & h_syms)),
        "unlisted_last_trade_by_year": {int(k): int(v) for k, v in
                                        last_trade.reindex(unlisted).dropna().dt.year.value_counts().sort_index().items()},
        "possible_renames": len(renames), "rename_examples": renames[:12], "known_delisted": known}

    # price limit, breaches, matching
    res["limit_vs_ldcp"] = limit_table(moves)
    regime = limits.ne(limits.shift()).cumsum()
    res["observed_limit_regimes"] = [{"limit": float(g.iloc[0]), "first": str(g.index[0].date()), "last": str(g.index[-1].date()),
                                      "days": int(len(g))} for _, g in limits.groupby(regime)]
    res["limit_rule_used"] = f"max(day's observed limit x reference, Rs {LIMIT_FLOOR_RS:g}), +0.5 % and Rs 0.01 rounding slack"
    res["rs1_floor_check"] = floor_check(moves, limits)
    pct = moves["date"].map(limits).to_numpy()
    exch = moves[(moves["close"] - moves["ldcp"]).abs() > limit_rs(moves["ldcp"], pct) * 1.005 + 0.01]
    first_day = exch.merge(adj.groupby("symbol")["date"].min().rename("first"), left_on="symbol", right_index=True)
    res["closes_beyond_band_vs_ldcp"] = {"n": int(len(exch)), "on_first_trading_day": int((first_day["date"] == first_day["first"]).sum()),
                                         "examples": exch.head(10)[["symbol", "date", "ldcp", "close"]].astype(str).values.tolist()}
    # KSE-100 history as the trading calendar: trading days whose closing file is missing
    idx = hist[hist["symbol"] == INDEX]
    missing_days = pd.DatetimeIndex(sorted(set(idx["date"]) - set(days)))
    calendar = days.union(missing_days)
    res["kse100"] = {"rows": int(len(idx)), "first": str(idx["date"].min().date()), "last": str(idx["date"].max().date()),
                     "index_days_without_closing_file": len(missing_days),
                     "missing_closing_days": [str(d.date()) for d in missing_days],
                     "closing_days_without_index_row": int((~days[days >= idx["date"].min()].isin(idx["date"])).sum())}

    br = breaches(hist[hist["symbol"].isin(eq_syms)], limits, calendar)
    br["cause"] = classify(br, adj, payouts, calendar)
    one = br[br["gap"] == 1]
    res["history_breaches"] = {"n": int(len(br)), "single_day": int(len(one)), "after_trading_gap": int((br["gap"] > 1).sum()),
                               "by_cause": {k: int(v) for k, v in br["cause"].value_counts().items()},
                               "single_day_by_cause": {k: int(v) for k, v in one["cause"].value_counts().items()},
                               "by_year": {int(k): int(v) for k, v in br["date"].dt.year.value_counts().sort_index().items()},
                               "exchange_adjusted_by_reason": {k: int(v) for k, v in br.loc[br["cause"] == "exchange_adjusted"].merge(
                                   adj[["symbol", "date", "ref_reason"]], on=["symbol", "date"])["ref_reason"].value_counts().items()},
                               "unexplained_examples": br[br["cause"] == "unexplained"].head(15).astype(str).values.tolist()}
    br.to_parquet(DERIVED / "history_breaches.parquet", index=False)

    # adjusted series quality
    flag = adj["xd"] | adj["xb"] | adj["xr"]
    run_start = flag & ~flag.groupby(adj["symbol"]).shift(1, fill_value=False) & adj["prev_close"].notna()
    ev = adj[adj["ref_adjusted"]]
    mis = adj[adj["ldcp_mismatch_unflagged"]]
    prev_date = adj.groupby("symbol")["date"].shift(1)[mis.index]
    after_missing = [bool(((missing_days > p) & (missing_days < d)).any()) for p, d in zip(prev_date, mis["date"])]
    with_prev = adj[adj["prev_close"].notna()]
    share = with_prev["ldcp_mismatch_unflagged"].groupby(with_prev["date"]).mean()
    cluster_days = share[share > 0.2].index                 # a whole market's LDCP off: the previous file is missing
    res["adjusted_series"] = {
        "rule": "flagged day: close/LDCP; other days: close/last close; forward-chained, never back-adjusted",
        "rows": int(len(adj)), "flag_runs": int(run_start.sum()),
        "flag_runs_with_ldcp_reduced_on_first_day": int((run_start & adj["ref_adjusted"] & (adj["ldcp"] < adj["prev_close"])).sum()),
        "flag_runs_with_ldcp_unchanged_on_first_day": int((run_start & ~adj["ref_adjusted"]).sum()),
        "exchange_adjustments_applied": int(len(ev)),
        "by_reason": {k: int(v) for k, v in ev["ref_reason"].value_counts().items()},
        "by_flag": {"xd": int(ev["xd"].sum()), "xb": int(ev["xb"].sum()), "xr": int(ev["xr"].sum())},
        "beyond_limit_examples": ev.loc[ev["ref_reason"] == "beyond_limit", ["symbol", "date", "prev_close", "ldcp"]]
                                   .head(12).astype(str).values.tolist(),
        "applied_with_ldcp_above_last_close": int((ev["ldcp"] > ev["prev_close"]).sum()),
        "unflagged_ldcp_mismatches": int(len(mis)),
        "unflagged_mismatches_after_a_missing_closing_file": int(sum(after_missing)),
        "days_with_over_20pct_of_symbols_mismatched": [str(d.date()) for d in cluster_days],
        "unflagged_mismatches_on_those_days": int(mis["date"].isin(cluster_days).sum()),
        "unflagged_mismatches_by_year": {int(k): int(v) for k, v in mis["date"].dt.year.value_counts().sort_index().items()},
        "payout_size_check_2024_11_on": payout_check(adj, payouts)}

    # cross-source agreement
    m = adj.merge(hist, on=["symbol", "date"], suffixes=("_c", "_h"))
    res["cross_source"] = {"matched_rows": int(len(m)),
                           "close_within_0_1pct_share": float(((m["close_h"] / m["close_c"] - 1).abs() <= 0.001).mean()),
                           "volume_equal_share": float((m["volume_h"] == m["volume_c"]).mean())}
    res["liquidity_by_year"] = liquidity_by_year(eq, days)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("limit_vs_ldcp",)}, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
