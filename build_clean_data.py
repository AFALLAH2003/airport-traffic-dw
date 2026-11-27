# -*- coding: utf-8 -*-
"""
build_clean_data.py  -  ONDA air-traffic Data Warehouse : clean data builder (tasks B1 + B2)

USAGE (Windows):
    python build_clean_data.py                      -> uses D:\\DW_project_copy
    python build_clean_data.py "D:\\other\\folder"   -> custom project folder

READS   <BASE>\\morocco_airports.csv, <BASE>\\onda_excel\\**, <BASE>\\hcp_raw\\*
WRITES  <BASE>\\clean\\*.csv  +  clean\\qc_report.txt  (nothing in the raw folders is modified)

DESIGN RULES (they answer the "problems to settle" list)
  A. Gaps    : every month is looked for in ALL columns of ALL reports (current-year column first, then
               the prior-year columns of later reports).  What is still missing (2020, 2021 Jan-Aug) is
               ESTIMATED from cumulative totals / HCP annual totals and flagged is_estimated = 1.
  B. Grain   : constellation schema -> separate fact tables (see FILES at the bottom) + a 'DOM' member in
               the zone dimension for national traffic.  Annual + top-routes facts are kept out of the cube.
  C. Quality : a missing value is NEVER replaced by 0 (empty = unknown).  One source file is chosen per
               (year, month, metric); partial periods (e.g. 7-28 Feb 2022) are never used as a month;
               every disagreement between sources is written to qc_conflicts.csv.
"""
import os, re, sys, math, unicodedata, datetime as dt
import numpy as np
import pandas as pd

BASE_DIR = sys.argv[1] if len(sys.argv) > 1 else r"D:\Data_Warhouse_Project"
OUT_DIR = os.path.join(BASE_DIR, "clean")
ENC = "utf-8-sig"
TOL = 0.005                    # relative tolerance for conflicts / reconciliations (0.5 %)
MIN_MONTHS_CLUSTER = 24        # airport needs >= 24 observed months to be clustered
MIN_AVG_PAX_CLUSTER = 1000     # ... and an average of >= 1000 passengers / month
FEATURE_START_YEAR = 2023      # clustering profile uses post-recovery years only
SOURCE_POLICY = "latest_revision"   # or "own_year"  (see pick_primary)
ESTIMATE_MISSING = True        # set False to keep gaps empty instead of estimating them
FIRST_YEAR = 2019

# ----------------------------------------------------------------------------- reference data
# code, canonical name, alias patterns (normalised, matched as whole words), city, ISO region
AIRPORTS = [
    ("CMN", "Casablanca Mohammed V", ["MOHAMMED V", "MOHAMED V", "MED V", "MOHAMMED 5"], "Casablanca", "MA-06"),
    ("RAK", "Marrakech Menara", ["MARRAKECH"], "Marrakech", "MA-07"),
    ("AGA", "Agadir Al Massira", ["AGADIR"], "Agadir", "MA-09"),
    ("TNG", "Tanger Ibn Battouta", ["TANGER", "TANGIER"], "Tanger", "MA-01"),
    ("FEZ", "Fès Saïss", ["FES", "FEZ", "SAISS"], "Fès", "MA-03"),
    ("RBA", "Rabat-Salé", ["RABAT"], "Salé", "MA-04"),
    ("NDR", "Nador Al Aroui", ["NADOR"], "Nador", "MA-02"),
    ("OUD", "Oujda Angads", ["OUJDA"], "Oujda", "MA-02"),
    ("ESU", "Essaouira Mogador", ["ESSAOUIRA"], "Essaouira", "MA-07"),
    ("OZZ", "Ouarzazate", ["OUARZAZATE"], "Ouarzazate", "MA-08"),
    ("EUN", "Laâyoune Hassan Ier", ["LAAYOUNE", "LAYOUNE"], "Laâyoune", "MA-11"),
    ("VIL", "Dakhla", ["DAKHLA"], "Dakhla", "MA-12"),
    ("TTU", "Tétouan Sania Ramel", ["TETOUAN"], "Tétouan", "MA-01"),
    ("AHU", "Al Hoceima Charif Al Idrissi", ["HOCEIMA", "AL HOCEIMA", "ALHOCEIMA"], "Al Hoceima", "MA-01"),
    ("ERH", "Errachidia Moulay Ali Cherif", ["ERRACHIDIA"], "Errachidia", "MA-08"),
    ("GLN", "Guelmim", ["GUELMIM", "GUELMIME"], "Guelmim", "MA-10"),
    ("TTA", "Tan-Tan", ["TAN TAN", "TANTAN"], "Tan-Tan", "MA-10"),
    ("OZG", "Zagora", ["ZAGORA"], "Zagora", "MA-08"),
    ("BEM", "Béni Mellal", ["BENI MELLAL"], "Béni Mellal", "MA-05"),
    ("UAR", "Bouarfa", ["BOUARFA"], "Bouarfa", "MA-02"),
    ("SMW", "Es-Smara", ["SMARA", "ES SMARA", "SEMARA"], "Smara", "MA-11"),
    ("SII", "Sidi Ifni", ["IFNI"], "Sidi Ifni", "MA-10"),
    ("BSM", "Benslimane (code interne)", ["BENSLIMANE"], "Benslimane", "MA-06"),
    ("OTH", "Autres aéroports (ligne agrégée ONDA)", ["AUTRES", "AUTTRES", "AUTRES AEROPORTS"], None, None),
]
REGION_NAMES = {
    "MA-01": "Tanger-Tétouan-Al Hoceïma", "MA-02": "Oriental", "MA-03": "Fès-Meknès",
    "MA-04": "Rabat-Salé-Kénitra", "MA-05": "Béni Mellal-Khénifra", "MA-06": "Casablanca-Settat",
    "MA-07": "Marrakech-Safi", "MA-08": "Drâa-Tafilalet", "MA-09": "Souss-Massa",
    "MA-10": "Guelmim-Oued Noun", "MA-11": "Laâyoune-Sakia El Hamra", "MA-12": "Dakhla-Oued Ed-Dahab",
}
ZONES = [  # code, label, group used in the project brief
    ("EUR", "Europe", "Europe"),
    ("MAG", "Maghreb", "Maghreb"),
    ("MOE", "Moyen et Extrême-Orient", "Moyen-Orient"),
    ("AFR", "Afrique (autres relations)", "Autres"),
    ("AMN", "Amérique du Nord", "Autres"),
    ("AMS", "Amérique du Sud", "Autres"),
    ("AUT", "Autres / non classé", "Autres"),
    ("DOM", "Domestique (sans objet)", "Domestique"),
]
MONTHS_FR = {"JANVIER": 1, "FEVRIER": 2, "MARS": 3, "AVRIL": 4, "MAI": 5, "JUIN": 6, "JUILLET": 7,
             "AOUT": 8, "SEPTEMBRE": 9, "OCTOBRE": 10, "NOVEMBRE": 11, "DECEMBRE": 12}
MONTH_NAME = {v: k.capitalize() for k, v in MONTHS_FR.items()}
MONTH_NAME[2] = "Février"; MONTH_NAME[8] = "Août"; MONTH_NAME[12] = "Décembre"

# ----------------------------------------------------------------------------- helpers
def ascii_upper(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()

def norm(s):
    return re.sub(r"[^A-Z0-9]+", " ", ascii_upper(s)).strip()

def num(x):
    if x is None or isinstance(x, (bool, np.bool_)):
        return math.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    if isinstance(x, str):
        t = x.replace("\xa0", "").replace(" ", "").replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return math.nan
    return math.nan

def month_of(text):
    u = ascii_upper(text)
    for name, n in MONTHS_FR.items():
        if re.search(r"\b" + name + r"\b", u):
            return n
    return None

def is_partial(text):
    return bool(re.search(r"\bAU\b", ascii_upper(text)))

def airport_code_of(label):
    n = norm(label)
    if not n:
        return None
    for code, _, pats, _, _ in AIRPORTS:
        for p in pats:
            if re.search(r"\b" + p + r"\b", n):
                return code
    compact = n.replace(" ", "")                    # 'ALHOCEIMA', 'BENIMELLAL', 'GUELMIME' ...
    for code, _, pats, _, _ in AIRPORTS:
        for p in pats:
            q = p.replace(" ", "")
            if len(q) >= 6 and q in compact:
                return code
    return None

def zone_of(label):
    n = norm(label)
    if "EUROPE" in n: return "EUR"
    if "MAGHREB" in n: return "MAG"
    if "MOYEN" in n: return "MOE"
    if "AFRIQUE" in n: return "AFR"
    if "AMERIQUE" in n and "NORD" in n: return "AMN"
    if "AMERIQUE" in n and ("SUD" in n or "LATINE" in n): return "AMS"
    return None

def find_title(df, maxrows=15):
    """first cell containing a year sequence such as 2023/2022/2019 or 2023-2024 -> (month, years, text)"""
    for i in range(min(maxrows, len(df))):
        for v in df.iloc[i].tolist():
            if isinstance(v, str):
                u = ascii_upper(v)
                m = re.search(r"(20\d\d(?:\s*[/\-]\s*20\d\d)+)", u)
                if m:
                    return month_of(u), [int(y) for y in re.findall(r"20\d\d", m.group(1))], v
    return None, [], None

def rel(a, b):
    return abs(a - b) / abs(b) if b not in (0, None) and not pd.isna(b) else np.nan

class Report:
    def __init__(self): self.lines = []
    def add(self, s=""): self.lines.append(str(s)); print(s)

# ----------------------------------------------------------------------------- parsers
def parse_trafic(df, fname):
    """'Trafic aérien par aéroport' sheet -> rows (airport x metric x year) with monthly value + cumul"""
    month, years, _ = find_title(df)
    if month is None or not years:
        raise ValueError("title with month and years not found")
    n = len(years)
    hdr = None
    for i in range(min(40, len(df))):
        if norm(df.iat[i, 0]) in ("AEROPORTS", "AEROPORT"):
            hdr = i; break
        names = [norm(v) for v in df.iloc[i, 1:].tolist() if isinstance(v, str)]
        if "PASSAGERS" in names and any(x == "MOUVEMENTS" or x.startswith("FRET") for x in names):
            hdr = i; break                                  # column A of the header row may be empty
    if hdr is None:
        raise ValueError("header row AEROPORTS not found")
    ncols = df.shape[1]
    starts = []
    for c in range(1, ncols):
        v = df.iat[hdr, c]
        if isinstance(v, str):
            k = norm(v)
            if k == "PASSAGERS": starts.append((c, "passengers"))
            elif k == "MOUVEMENTS": starts.append((c, "movements"))
            elif k.startswith("FRET"): starts.append((c, "cargo_t"))
    if not starts:
        raise ValueError("no PASSAGERS/MOUVEMENTS/FRET block")
    blocks = []
    for k, (c0, metric) in enumerate(starts):
        c1 = starts[k + 1][0] if k + 1 < len(starts) else ncols
        txt = [norm(df.iat[r, c]) for r in (hdr + 1, hdr + 2) if r < len(df)
               for c in range(c0, c1) if isinstance(df.iat[r, c], str)]
        blocks.append(dict(metric=metric, c0=c0, cum=any("CUMUL" in t for t in txt)))
    rows = []
    for r in range(hdr + 1, len(df)):
        lab = df.iat[r, 0]
        if not isinstance(lab, str) or not lab.strip():
            continue
        rec = {}
        for b in blocks:
            c0 = b["c0"]
            if c0 + n >= ncols + 1:
                continue
            vals = [num(df.iat[r, c0 + i]) for i in range(n)]
            rate = num(df.iat[r, c0 + n]) if c0 + n < ncols else math.nan
            cum = [num(df.iat[r, c0 + n + 1 + i]) if (b["cum"] and c0 + n + 1 + i < ncols) else math.nan
                   for i in range(n)]
            if all(math.isnan(v) for v in vals):
                continue
            rec[b["metric"]] = (vals, rate, cum)
        if rec:
            rows.append((lab.strip(), rec))
    # orientation: which column is the most recent year ?  (checked against the variation column)
    fwd = rv = 0
    for _, rec in rows:
        for vals, rate, _c in rec.values():
            if math.isnan(rate) or any(math.isnan(v) or v <= 0 for v in vals):
                continue
            if n == 2:
                fwd += abs(vals[0] / vals[1] - 1 - rate) < 0.003
                rv += abs(vals[1] / vals[0] - 1 - rate) < 0.003
            elif n == 3:
                fwd += abs(vals[0] / vals[2] - rate) < 0.003
                rv += abs(vals[2] / vals[0] - rate) < 0.003
    yrs = years[::-1] if rv > fwd else years
    out = []
    for lab, rec in rows:
        code = "TOTAL" if norm(lab).startswith("TOTAL") else airport_code_of(lab)
        for metric, (vals, rate, cum) in rec.items():
            for i in range(n):
                out.append(dict(file=fname, file_year=max(years), data_year=yrs[i], month=month,
                                airport_label=lab, airport_code=code, metric=metric,
                                value=vals[i], cumul=cum[i]))
    return out, dict(month=month, years=yrs, reversed=rv > fwd, blocks=[b["metric"] for b in blocks],
                     cumul=any(b["cum"] for b in blocks))

def parse_natinter(df, fname):
    """national / international split by airport. Header row holds dates (modern) or 'Mai 2022' texts (2022)."""
    tmonth, _, _ = find_title(df)
    hdr = next((i for i in range(min(40, len(df))) if norm(df.iat[i, 0]) == "AEROPORT"), None)
    if hdr is None:
        raise ValueError("header row AEROPORT not found")
    groups, skipped = [], 0
    for c in range(1, df.shape[1]):
        v = df.iat[hdr, c]
        if pd.isna(v):
            continue
        if isinstance(v, (dt.datetime, pd.Timestamp)):
            groups.append((c, v.year, v.month)); continue
        if isinstance(v, str):
            u = ascii_upper(v)
            if re.match(r"^(CUMUL|VARIATION|VAR\b|TAUX)", u):
                continue
            m = re.search(r"(20\d\d)", u)
            if m:
                if is_partial(u):
                    skipped += 1; continue
                mo = month_of(u) or tmonth
                if mo: groups.append((c, int(m.group(1)), mo))
    if not groups:
        raise ValueError("no monthly group (partial periods only: %d skipped)" % skipped)
    out = []
    for r in range(hdr + 1, len(df)):
        lab = df.iat[r, 0]
        if not isinstance(lab, str) or not lab.strip():
            continue
        code = "TOTAL" if norm(lab).startswith("TOTAL") else airport_code_of(lab)
        for c, y, mo in groups:
            v = [num(df.iat[r, c + k]) if c + k < df.shape[1] else math.nan for k in range(3)]
            if all(math.isnan(x) for x in v):
                continue
            out.append(dict(file=fname, file_year=max(g[1] for g in groups), data_year=y, month=mo,
                            airport_label=lab.strip(), airport_code=code, intl=v[0], nat=v[1], total=v[2]))
    return out, dict(groups=[(g[1], g[2]) for g in groups], skipped=skipped)

def walk_zone_rows(df, r0, lc, vcs):
    """state machine over rows: zone totals, airports under a zone, zones under an airport header"""
    out, cur_zone, cur_air = [], None, None
    for r in range(r0, len(df)):
        lab = df.iat[r, lc]
        if not isinstance(lab, str) or not lab.strip():
            continue
        vals = [num(df.iat[r, c]) if c < df.shape[1] else math.nan for c in vcs]
        has = any(not math.isnan(v) for v in vals)
        if norm(lab).startswith("TOTAL"):
            if has: out.append(("TOTAL", None, vals, lab.strip()))
            cur_zone = cur_air = None
            continue
        z, a = zone_of(lab), airport_code_of(lab)
        if a == "OTH":                      # 'Autres' : a zone in region sheets, never an airport there
            a = None
            z = z or "AUT"
        if z is not None:
            if has:
                if cur_air: out.append((z, cur_air, vals, lab.strip()))
                else: out.append((z, None, vals, lab.strip())); cur_zone = z
            else:
                cur_zone = z
        elif a is not None:
            if has: out.append((cur_zone or "ALL", a, vals, lab.strip()))
            else: cur_air, cur_zone = a, None
        elif has:
            out.append(("UNMAPPED", None, vals, lab.strip()))
    return out

def parse_region_modern(df, fname):
    month, _, _ = find_title(df)
    if month is None:
        raise ValueError("month not found")
    hdr = next((i for i in range(min(25, len(df)))
                if any(isinstance(v, str) and norm(v) == "PASSAGERS" for v in df.iloc[i].tolist())), None)
    if hdr is None:
        raise ValueError("header 'Passagers' not found")
    out = []
    for o in [c for c, v in enumerate(df.iloc[hdr].tolist()) if isinstance(v, str) and norm(v) == "PASSAGERS"]:
        yr = None
        for r in range(hdr + 1, min(hdr + 4, len(df))):
            a, b = (num(df.iat[r, o + 1]), num(df.iat[r, o + 2])) if o + 2 < df.shape[1] else (math.nan, math.nan)
            if 2000 < a < 2100 and 2000 < b < 2100:
                yr = (r, int(a), int(b)); break
        if yr is None:
            continue
        r, y1, y2 = yr
        for zone, air, vals, lab in walk_zone_rows(df, r + 1, o, [o + 1, o + 2]):
            for y, v in zip((y1, y2), vals):
                if not math.isnan(v):
                    out.append(dict(file=fname, file_year=max(y1, y2), data_year=y, month=month,
                                    zone_code=zone, airport_code=air, passengers=v, label=lab))
    return out, dict(month=month)

def parse_region_legacy(df, fname):
    tmonth, _, _ = find_title(df)
    hdr = next((i for i in range(min(25, len(df))) if norm(df.iat[i, 0]).startswith("AEROPORT SECTEUR")), None)
    if hdr is None:
        raise ValueError("header AEROPORT/SECTEUR not found")
    cols = []
    for c in range(1, df.shape[1]):
        v = df.iat[hdr, c]
        if isinstance(v, str):
            u = ascii_upper(v)
            m = re.search(r"(20\d\d)", u)
            if m and not re.search(r"TAUX|VAR", u) and not is_partial(u):
                mo = month_of(u) or tmonth
                if mo: cols.append((c, int(m.group(1)), mo))
    if not cols:
        raise ValueError("only partial periods")
    out = []
    for zone, air, vals, lab in walk_zone_rows(df, hdr + 1, 0, [c[0] for c in cols]):
        for (c, y, mo), v in zip(cols, vals):
            if not math.isnan(v):
                out.append(dict(file=fname, file_year=max(x[1] for x in cols), data_year=y, month=mo,
                                zone_code=zone, airport_code=air, passengers=v, label=lab))
    return out, {}

def classify(sname, df):
    sn = norm(sname)
    head = " ".join(norm(v) for v in df.iloc[:12].values.ravel() if isinstance(v, str))
    if sn == "TRAFIC AERIEN PAR AEROPORT" or "TABLEAU DE BORD STATISTIQUES DU TRAFIC COMMERCIAL" in head:
        return "trafic"
    if sn == "VENTILATION NAT INTER":
        return "natinter"
    if sn.startswith("VENTILATION PAR REGION"):
        return "region"
    if "VENTILATION DU TRAFIC AERIEN" in head and "NATIONAL" in head and "INTERNATIONAL" in head:
        return "natinter"
    if "PAR SECTEUR GEOGRAPHIQUE" in head or "AEROPORT SECTEUR" in head:
        return "region_legacy"
    return None

def scan_onda(base, rep):
    T, N, R, unmapped = [], [], [], []
    root = os.path.join(base, "onda_excel")
    stats = dict(files=0, used=0, skipped=0, errors=0)
    if not os.path.isdir(root):
        rep.add("!! folder not found: " + root); return T, N, R, unmapped, stats
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if f.startswith("~$") or not f.lower().endswith((".xlsx", ".xls")):
                continue
            path = os.path.join(dirpath, f)
            rel_path = os.path.relpath(path, base)
            stats["files"] += 1
            try:
                sheets = pd.read_excel(path, sheet_name=None, header=None)
            except Exception as e:
                rep.add("ERROR reading %s : %s" % (rel_path, e)); stats["errors"] += 1; continue
            used = False
            for sname, df in sheets.items():
                kind = classify(sname, df)
                if kind is None:
                    continue
                try:
                    if kind == "trafic":
                        rows, meta = parse_trafic(df, rel_path); T += rows
                        if meta["reversed"]:
                            rep.add("note: column order reversed vs title in %s [%s]" % (rel_path, sname))
                    elif kind == "natinter":
                        rows, _ = parse_natinter(df, rel_path); N += rows
                    elif kind == "region":
                        rows, _ = parse_region_modern(df, rel_path); R += rows
                    else:
                        rows, _ = parse_region_legacy(df, rel_path); R += rows
                    used = used or bool(rows)
                    for r_ in rows:
                        if r_.get("airport_code") is None and kind in ("trafic", "natinter"):
                            unmapped.append((r_["airport_label"], rel_path))
                        if r_.get("zone_code") == "UNMAPPED":
                            unmapped.append((r_["label"], rel_path))
                except Exception as e:
                    rep.add("skip  %s [%s] (%s): %s" % (rel_path, sname, kind, e))
            stats["used" if used else "skipped"] += 1
    return T, N, R, unmapped, stats

# ----------------------------------------------------------------------------- HCP (annual)
def scan_hcp(base, rep):
    rows = []
    root = os.path.join(base, "hcp_raw")
    if not os.path.isdir(root):
        rep.add("!! folder not found: " + root); return pd.DataFrame()
    for f in sorted(os.listdir(root)):
        if f.startswith("~$") or not f.lower().endswith((".xlsx", ".xls")):
            continue
        n = norm(f)
        try:
            df = pd.read_excel(os.path.join(root, f), header=None)
        except Exception as e:
            rep.add("ERROR HCP %s : %s" % (f, e)); continue
        hdr = next((i for i in range(min(15, len(df))) if norm(df.iat[i, 0]) == "PERIODES"), None)
        if hdr is None:
            rep.add("skip HCP %s : header Périodes not found" % f); continue
        ycols = {c: int(num(df.iat[hdr, c])) for c in range(1, df.shape[1]) if 1990 < num(df.iat[hdr, c]) < 2100}
        if "MOUVEMENTS" in n:
            for r in range(hdr + 1, len(df)):
                lab = df.iat[r, 0]
                if not isinstance(lab, str): continue
                code = "TOTAL" if norm(lab).startswith("TOTAL") else airport_code_of(lab)
                for c, y in ycols.items():
                    v = num(df.iat[r, c])
                    if not math.isnan(v):
                        rows.append(dict(airport_label=lab.strip(), airport_code=code, year=y, metric="movements", value=v, file=f))
        elif "VOYAGEURS" in n:
            cur = None
            for r in range(hdr + 1, len(df)):
                lab = df.iat[r, 0]
                if isinstance(lab, str) and lab.strip() and norm(lab) != "AEROPORT":
                    cur = lab.strip()
                cat = df.iat[r, 1] if df.shape[1] > 1 else None
                if cur is None or not isinstance(cat, str):
                    continue
                k = norm(cat)
                metric = {"ARRIVEES": "pax_arrivals", "DEPARTS": "pax_departures",
                          "TRANSIT": "pax_transit", "TOTAL": "pax_total"}.get(k)
                if metric is None: continue
                code = "TOTAL" if norm(cur).startswith("TOTAL") else airport_code_of(cur)
                for c, y in ycols.items():
                    v = num(df.iat[r, c])
                    if not math.isnan(v):
                        rows.append(dict(airport_label=cur, airport_code=code, year=y, metric=metric, value=v, file=f))
        else:
            rep.add("skip HCP %s : unknown file type" % f)
    return pd.DataFrame(rows)

# ----------------------------------------------------------------------------- source selection
def pick_primary(df, keys):
    """one source file per key: smallest (file_year - data_year), then not 'Copie de...', then name"""
    d = df.copy()
    d["gap"] = d["file_year"] - d["data_year"]
    # latest_revision : the report of the NEXT year(s) restates the previous year's figures (ONDA revises them),
    #                   so gap>=1 is preferred (smallest gap first); the own-year report is the last resort.
    d["rank"] = np.where(d["gap"] >= 1, d["gap"], 1000) if SOURCE_POLICY == "latest_revision" else d["gap"]
    d["copie"] = d["file"].str.upper().str.contains("COPIE").astype(int)
    cand = d.groupby(keys + ["file"], as_index=False).agg(rank=("rank", "first"), copie=("copie", "first"))
    cand = cand.sort_values(keys + ["rank", "copie", "file"])
    prim = cand.drop_duplicates(keys)[keys + ["file"]]
    return d.merge(prim, on=keys + ["file"], how="inner")

def season_of(m):
    return "Hiver" if m in (12, 1, 2) else "Printemps" if m in (3, 4, 5) else "Été" if m in (6, 7, 8) else "Automne"

def phase_of(y, m):
    k = y * 100 + m
    return "Avant COVID" if k < 202003 else "COVID (frontières fermées)" if k < 202202 else \
           "Reprise 2022" if k < 202301 else "Après reprise"

# ----------------------------------------------------------------------------- main
def main():
    np.seterr(all="ignore")
    os.makedirs(OUT_DIR, exist_ok=True)
    rep = Report()
    rep.add("=" * 78); rep.add("ONDA DW - clean data builder"); rep.add("base folder : " + BASE_DIR); rep.add("=" * 78)

    # ---- 0. airport reference (csv from ourairports) ------------------------------------------------
    csv_path = os.path.join(BASE_DIR, "morocco_airports.csv")
    ref = pd.read_csv(csv_path) if os.path.exists(csv_path) else pd.DataFrame(
        columns=["iata_code", "municipality", "iso_region", "latitude_deg", "longitude_deg", "type", "name", "ident"])
    if ref.empty: rep.add("!! morocco_airports.csv not found -> city/region come from the built-in table only")

    # ---- 1. scan ONDA reports -----------------------------------------------------------------------
    rep.add("\n[1] Scanning onda_excel ...  (source policy: %s)" % SOURCE_POLICY)
    T, N, R, unmapped, st = scan_onda(BASE_DIR, rep)
    rep.add("files seen: %(files)d | used: %(used)d | without usable monthly data: %(skipped)d | read errors: %(errors)d" % st)
    T, N, R = pd.DataFrame(T), pd.DataFrame(N), pd.DataFrame(R)
    if T.empty:
        rep.add("!! no monthly traffic table found - nothing to build"); return
    H = scan_hcp(BASE_DIR, rep)

    # ---- 2. choose ONE source per (year, month, metric) --------------------------------------------
    Tv = T[T["value"].notna() & (T["data_year"] >= FIRST_YEAR)]
    Tp = pick_primary(Tv, ["data_year", "month", "metric"])
    dupmask = Tp[Tp.airport_code.notna()].duplicated(["airport_code", "data_year", "month", "metric", "file"], keep=False)
    dups = Tp[Tp.airport_code.notna()][dupmask]
    dups[["file", "data_year", "month", "metric", "airport_code", "airport_label", "value"]].to_csv(
        os.path.join(OUT_DIR, "qc_duplicate_labels.csv"), index=False, encoding=ENC)
    Tp = Tp.drop_duplicates(["airport_code", "data_year", "month", "metric"], keep="first") \
        if Tp["airport_code"].isna().sum() == 0 else \
        pd.concat([Tp[Tp.airport_code.notna()].drop_duplicates(["airport_code", "data_year", "month", "metric"]),
                   Tp[Tp.airport_code.isna()]])
    A = Tp[Tp["airport_code"].notna() & (Tp["airport_code"] != "TOTAL")]
    TOT = Tp[Tp["airport_code"] == "TOTAL"]

    mon = A.pivot_table(index=["airport_code", "data_year", "month"], columns="metric", values="value", aggfunc="first")
    src = A.pivot_table(index=["airport_code", "data_year", "month"], columns="metric", values="file", aggfunc="first")
    src.columns = ["src_" + c for c in src.columns]
    mon = mon.join(src).reset_index()
    for c in ("passengers", "movements", "cargo_t"):
        if c not in mon: mon[c] = np.nan
        if "src_" + c not in mon: mon["src_" + c] = None

    # national / international split
    if not N.empty:
        Nv = N[(N["data_year"] >= FIRST_YEAR) & N["airport_code"].notna() & (N["airport_code"] != "TOTAL")]
        Np = pick_primary(Nv, ["data_year", "month"]).drop_duplicates(["airport_code", "data_year", "month"])
        Np = Np.rename(columns={"intl": "passengers_international", "nat": "passengers_national",
                                "total": "pax_split_total", "file": "src_split"})
        mon = mon.merge(Np[["airport_code", "data_year", "month", "passengers_international",
                            "passengers_national", "pax_split_total", "src_split"]],
                        on=["airport_code", "data_year", "month"], how="outer")
    else:
        for c in ("passengers_international", "passengers_national", "pax_split_total"): mon[c] = np.nan
        mon["src_split"] = None
    mon = mon.rename(columns={"data_year": "year", "passengers": "passengers_total", "cargo_t": "cargo_tonnes"})
    # passengers total missing in the traffic table but present in the split table -> use it (flagged)
    fill = mon["passengers_total"].isna() & mon["pax_split_total"].notna()
    mon.loc[fill, "src_passengers"] = mon.loc[fill, "src_split"]
    mon["flag_pax_from_split"] = fill.astype(int)
    mon.loc[fill, "passengers_total"] = mon.loc[fill, "pax_split_total"]
    mon["flag_split_mismatch"] = ((mon["pax_split_total"] - mon["passengers_total"]).abs()
                                  > TOL * mon["passengers_total"].abs()).astype(int)
    mon["flag_zero_passengers"] = (mon["passengers_total"] == 0).astype(int)
    mon["is_estimated"] = 0
    mon["estimation_method"] = None
    mon = mon[mon["month"].notna() & mon["year"].notna()].copy()

    # ---- 3. cumulative values -> used for control and to rebuild missing months --------------------
    cum = Tp[Tp["cumul"].notna()][["airport_code", "data_year", "month", "metric", "cumul", "file"]]

    # ---- 4. estimates for what is really missing ----------------------------------------------------
    est_rows = []
    if ESTIMATE_MISSING:
        def shape19(code, metric):
            s = mon[(mon.airport_code == code) & (mon.year == 2019)].set_index("month")[metric]
            return s.reindex(range(1, 13))
        net19 = {m: mon[(mon.year == 2019)].groupby("month")[m2].sum(min_count=1)
                 for m, m2 in (("passengers_total", "passengers_total"), ("movements", "movements"),
                               ("cargo_tonnes", "cargo_tonnes"))}
        def weights(code, metric, months):
            s = shape19(code, metric).reindex(months)
            if s.notna().all() and s.sum() > 0:
                return (s / s.sum()).to_dict()
            s = net19[metric].reindex(months)
            if s.notna().all() and s.sum() > 0:
                return (s / s.sum()).to_dict()
            return {m: 1 / len(months) for m in months}
        mmap = {"passengers": "passengers_total", "movements": "movements", "cargo_t": "cargo_tonnes"}
        # 4a. months before the first cumulative anchor of 2021 (cumul(anchor) - observed months)
        for metric, col in mmap.items():
            c = cum[(cum.data_year == 2021) & (cum.metric == metric) & (cum.airport_code != "TOTAL")]
            if c.empty: continue
            ma = int(c["month"].min())
            for code, g in c[c.month == ma].groupby("airport_code"):
                tot = g["cumul"].iloc[0]
                obs = mon[(mon.airport_code == code) & (mon.year == 2021) & (mon.month <= ma)]
                got = obs.dropna(subset=[col]).set_index("month")[col]
                miss = [m for m in range(1, ma + 1) if m not in got.index]
                resid = tot - got.sum()
                if not miss or resid <= 0: continue
                w = weights(code, col, miss)
                for m in miss:
                    est_rows.append((code, 2021, m, col, resid * w[m], "cumul_residual_x_2019_shape"))
        # 4b. 2020: HCP annual total spread with the 2019 shape
        if not H.empty:
            hm = {"pax_total": "passengers_total", "movements": "movements"}
            for metric, col in hm.items():
                h = H[(H.metric == metric) & (H.year == 2020) & H.airport_code.notna() & (H.airport_code != "TOTAL")]
                for code, g in h.groupby("airport_code"):
                    w = weights(code, col, list(range(1, 13)))
                    for m in range(1, 13):
                        est_rows.append((code, 2020, m, col, g["value"].iloc[0] * w[m], "hcp_annual_x_2019_shape"))
    if est_rows:
        E = pd.DataFrame(est_rows, columns=["airport_code", "year", "month", "col", "val", "method"])
        have = set(zip(mon.airport_code, mon.year, mon.month, ["passengers_total"] * len(mon)))
        new = {}
        for r in E.itertuples():
            existing = mon[(mon.airport_code == r.airport_code) & (mon.year == r.year) & (mon.month == r.month)]
            if len(existing) and pd.notna(existing[r.col].iloc[0]):
                continue                                   # never overwrite an observed value
            k = (r.airport_code, r.year, r.month)
            new.setdefault(k, {"method": set()})
            new[k][r.col] = r.val; new[k]["method"].add(r.method)
        add = []
        for (code, y, m), d in new.items():
            add.append(dict(airport_code=code, year=y, month=m,
                            passengers_total=d.get("passengers_total", np.nan), movements=d.get("movements", np.nan),
                            cargo_tonnes=d.get("cargo_tonnes", np.nan), is_estimated=1,
                            estimation_method="+".join(sorted(d["method"])),
                            src_passengers="ESTIMATE", src_movements="ESTIMATE", src_cargo="ESTIMATE"))
        mon = pd.concat([mon, pd.DataFrame(add)], ignore_index=True)
    mon = mon[mon.airport_code.isin([a[0] for a in AIRPORTS])]
    mon = mon.sort_values(["airport_code", "year", "month"]).reset_index(drop=True)
    mon["date_key"] = (mon["year"] * 100 + mon["month"]).astype(int)
    mon["year"] = mon["year"].astype(int); mon["month"] = mon["month"].astype(int)
    # estimated cells that were left NaN stay empty (never 0)
    last_key = int(mon.loc[mon.is_estimated == 0, "date_key"].max())

    # ---- 5. QC tables ---------------------------------------------------------------------------------
    qc = {}
    allv = Tv[Tv.airport_code.notna()]
    pr = Tp[["airport_code", "data_year", "month", "metric", "value", "file"]].rename(
        columns={"value": "value_primary", "file": "file_primary"})
    m = allv.merge(pr, on=["airport_code", "data_year", "month", "metric"])
    m = m[m.file != m.file_primary].copy()
    m["rel_diff"] = (m.value - m.value_primary).abs() / m.value_primary.replace(0, np.nan)
    conf = m[m.rel_diff > TOL][["airport_code", "data_year", "month", "metric", "value_primary", "file_primary",
                                "value", "file", "rel_diff"]].rename(columns={"value": "value_other", "file": "file_other"})
    conf.to_csv(os.path.join(OUT_DIR, "qc_conflicts.csv"), index=False, encoding=ENC)

    # cumulative control : sum of monthly values (months 1..m) vs cumulative printed in the report
    chk = []
    cp = cum[cum.metric == "passengers"]
    obs_only = mon[mon.is_estimated == 0]
    for r in cp.itertuples():
        if r.airport_code == "TOTAL":
            sub = obs_only[(obs_only.year == r.data_year) & (obs_only.month <= r.month)]
            ssum, n_m = sub.groupby("month")["passengers_total"].sum().sum(), sub.month.nunique()
            tcheck = TOT[(TOT.metric == "passengers") & (TOT.data_year == r.data_year) & (TOT.month <= r.month)]
            ssum = tcheck.groupby("month")["value"].first().sum(); n_m = tcheck.month.nunique()
        else:
            sub = obs_only[(obs_only.airport_code == r.airport_code) & (obs_only.year == r.data_year)
                           & (obs_only.month <= r.month)].dropna(subset=["passengers_total"])
            ssum, n_m = sub["passengers_total"].sum(), sub.month.nunique()
        chk.append(dict(airport_code=r.airport_code, year=r.data_year, upto_month=r.month, cumul_in_report=r.cumul,
                        sum_of_monthly=ssum, months_available=n_m, months_expected=r.month,
                        rel_diff=rel(ssum, r.cumul), file=r.file))
    chk = pd.DataFrame(chk)
    chk.to_csv(os.path.join(OUT_DIR, "qc_cumul_check.csv"), index=False, encoding=ENC)

    # ---- 6. dimensions -------------------------------------------------------------------------------
    codes_seen = sorted(set(mon.airport_code) | (set(H.airport_code.dropna()) - {"TOTAL"} if not H.empty else set()))
    dim = []
    for code, name, pats, city, iso in AIRPORTS:
        if code not in codes_seen: continue
        r = ref[ref.iata_code == code] if "iata_code" in ref else ref.iloc[0:0]
        rr = r.iloc[0] if len(r) else None
        iso_final = rr["iso_region"] if rr is not None and isinstance(rr["iso_region"], str) else (iso or "N/A")
        o = mon[(mon.airport_code == code) & (mon.is_estimated == 0) & mon.passengers_total.notna()]
        o = o[o.date_key >= FEATURE_START_YEAR * 100 + 1]
        months_obs = o.date_key.nunique()
        avgpax = o.passengers_total.mean() if months_obs else np.nan
        dim.append(dict(airport_code=code, airport_name=name,
                        city=rr["municipality"] if rr is not None and isinstance(rr["municipality"], str) else (city or "N/A"),
                        is_aggregate=int(code == "OTH"),
                        region_code=iso_final, region_name=REGION_NAMES.get(iso_final, "Non applicable" if iso_final == "N/A" else iso_final),
                        airport_type=rr["type"] if rr is not None else None,
                        latitude=rr["latitude_deg"] if rr is not None else np.nan,
                        longitude=rr["longitude_deg"] if rr is not None else np.nan,
                        csv_ident=rr["ident"] if rr is not None else None,
                        code_is_internal=int(code == "BSM"),
                        in_onda_reports=int(code in set(mon.airport_code)), in_hcp=int((not H.empty) and code in set(H.airport_code)),
                        months_observed_recent=months_obs,
                        avg_monthly_passengers_recent=avgpax,
                        include_in_clustering=int(code != "OTH" and months_obs >= MIN_MONTHS_CLUSTER and avgpax >= MIN_AVG_PAX_CLUSTER)))
        if iso and rr is not None and isinstance(rr["iso_region"], str) and rr["iso_region"] != iso:
            rep.add("note: region of %s differs between csv (%s) and built-in table (%s) -> csv kept" % (code, rr["iso_region"], iso))
    dim = pd.DataFrame(dim)
    dim.to_csv(os.path.join(OUT_DIR, "dim_aeroport.csv"), index=False, encoding=ENC)

    last_y, last_m = divmod(last_key, 100)
    months = [(y, mo) for y in range(FIRST_YEAR, last_y + 1) for mo in range(1, 13) if y * 100 + mo <= last_key]
    pd.DataFrame([dict(date_key=y * 100 + mo, date=dt.date(y, mo, 1).isoformat(), year=y, quarter=(mo - 1) // 3 + 1,
                       month_num=mo, month_name=MONTH_NAME[mo], year_month="%d-%02d" % (y, mo),
                       season=season_of(mo), covid_phase=phase_of(y, mo)) for y, mo in months]
                 ).to_csv(os.path.join(OUT_DIR, "dim_temps.csv"), index=False, encoding=ENC)
    pd.DataFrame([dict(type_code="INT", type_label="International"), dict(type_code="NAT", type_label="National")]
                 ).to_csv(os.path.join(OUT_DIR, "dim_type_trafic.csv"), index=False, encoding=ENC)
    pd.DataFrame([dict(zone_code=c, zone_label=l, zone_group=g) for c, l, g in ZONES]
                 ).to_csv(os.path.join(OUT_DIR, "dim_zone_origine.csv"), index=False, encoding=ENC)

    # ---- 7. fact tables ------------------------------------------------------------------------------
    keep = ["airport_code", "date_key", "year", "month", "passengers_total", "passengers_international",
            "passengers_national", "movements", "cargo_tonnes", "is_estimated", "estimation_method",
            "src_passengers", "src_movements", "src_cargo", "src_split", "flag_zero_passengers",
            "flag_split_mismatch", "flag_pax_from_split"]
    fm = mon[keep].copy()
    fm.to_csv(os.path.join(OUT_DIR, "fact_trafic_mensuel.csv"), index=False, encoding=ENC)

    ft = []
    for r in mon.itertuples():
        for tc, col in (("INT", "passengers_international"), ("NAT", "passengers_national")):
            v = getattr(r, col)
            if pd.notna(v):
                ft.append(dict(airport_code=r.airport_code, date_key=r.date_key, type_code=tc, passengers=v, src_split=r.src_split))
    pd.DataFrame(ft).to_csv(os.path.join(OUT_DIR, "fact_trafic_par_type.csv"), index=False, encoding=ENC)

    fz = pd.DataFrame()
    if not R.empty:
        Rv = R[(R.data_year >= FIRST_YEAR) & (R.zone_code != "UNMAPPED") & (R.zone_code != "ALL")]
        Rv = Rv.assign(scope=np.where(Rv.airport_code.isna(), "RESEAU", "AEROPORT"))
        Rp = pick_primary(Rv, ["data_year", "month", "scope", "zone_code"])   # best source per zone and scope
        Rp = Rp.drop_duplicates(["zone_code", "airport_code", "data_year", "month"]) if len(Rp) else Rp
        fz = Rp[Rp.zone_code != "TOTAL"].assign(date_key=lambda d: (d.data_year * 100 + d.month).astype(int),
                                               scope=lambda d: np.where(d.airport_code.isna(), "RESEAU", "AEROPORT"))
        fz = fz[["date_key", "zone_code", "airport_code", "scope", "passengers", "file"]].rename(
            columns={"passengers": "passengers_international", "file": "src_file"}).sort_values(["date_key", "zone_code"])
        fz.to_csv(os.path.join(OUT_DIR, "fact_passagers_zone.csv"), index=False, encoding=ENC)

    # annual (kept OUT of the cube): HCP + cumulative of December + sum of the monthly fact
    ann = []
    if not H.empty:
        hp = H[H.airport_code.notna() & (H.airport_code != "TOTAL")].pivot_table(
            index=["airport_code", "year"], columns="metric", values="value", aggfunc="first").reset_index()
        ann = hp
    else:
        ann = pd.DataFrame(columns=["airport_code", "year"])
    dec = cum[(cum.month == 12) & (cum.metric == "passengers") & (cum.airport_code != "TOTAL")][
        ["airport_code", "data_year", "cumul"]].rename(columns={"data_year": "year", "cumul": "pax_total_onda_cumul_dec"})
    msum = mon[mon.is_estimated == 0].groupby(["airport_code", "year"]).agg(
        pax_sum_monthly_observed=("passengers_total", "sum"), months_observed=("passengers_total", "count")).reset_index()
    ann = ann.merge(dec, on=["airport_code", "year"], how="outer").merge(msum, on=["airport_code", "year"], how="outer")
    ann["pct_monthly_vs_annual"] = ann["pax_sum_monthly_observed"] / ann["pax_total_onda_cumul_dec"].fillna(
        ann.get("pax_total", np.nan))
    ann = ann[ann.year >= FIRST_YEAR].sort_values(["airport_code", "year"])
    ann.to_csv(os.path.join(OUT_DIR, "fact_trafic_annuel.csv"), index=False, encoding=ENC)

    # ---- 8. ready-to-use files for the data-mining tasks (A5, B5, B6) ----------------------------------
    # 8a. network monthly series (ONDA 'TOTAL' row when present, otherwise sum of airports)
    ts = []
    tp = TOT[TOT.metric == "passengers"].groupby(["data_year", "month"])["value"].first()
    for y, mo in months:
        k = y * 100 + mo
        sub = mon[mon.date_key == k]
        est = int(sub.is_estimated.max()) if len(sub) else 0
        total_row = tp.get((y, mo), np.nan)
        s = sub["passengers_total"].sum(min_count=1)
        ts.append(dict(date_key=k, year=y, month=mo,
                       passengers_network=total_row if pd.notna(total_row) and not est else s,
                       passengers_sum_airports=s, movements_sum_airports=sub["movements"].sum(min_count=1),
                       cargo_tonnes_sum_airports=sub["cargo_tonnes"].sum(min_count=1),
                       n_airports=int(sub["passengers_total"].notna().sum()), is_estimated=est,
                       status="ESTIMATED" if est else ("OBSERVED" if len(sub) else "MISSING")))
    ts = pd.DataFrame(ts)
    ts.to_csv(os.path.join(OUT_DIR, "ts_reseau_mensuel.csv"), index=False, encoding=ENC)
    tv = ts[(ts.is_estimated == 0) & ts.passengers_network.notna() & ts.passengers_sum_airports.notna()].copy()
    tv["rel_diff"] = (tv.passengers_sum_airports - tv.passengers_network) / tv.passengers_network
    tv.to_csv(os.path.join(OUT_DIR, "qc_total_vs_sum.csv"), index=False, encoding=ENC)

    # 8b. complete airport x month panel with explicit status (for ARIMA / Prophet / Z-score prototypes)
    grid = pd.MultiIndex.from_product([sorted(dim.airport_code), [y * 100 + mo for y, mo in months]],
                                      names=["airport_code", "date_key"]).to_frame(index=False)
    panel = grid.merge(fm[["airport_code", "date_key", "passengers_total", "movements", "cargo_tonnes",
                           "is_estimated"]], on=["airport_code", "date_key"], how="left")
    panel["status"] = np.where(panel.passengers_total.isna() & panel.movements.isna(), "MISSING",
                               np.where(panel.is_estimated == 1, "ESTIMATED", "OBSERVED"))
    panel["year"] = panel.date_key // 100; panel["month"] = panel.date_key % 100
    panel.to_csv(os.path.join(OUT_DIR, "panel_aeroport_mois_complet.csv"), index=False, encoding=ENC)

    # 8c. one row per airport for K-Means (observed values only, post-recovery years)
    feats = []
    for code in dim.airport_code:
        o = mon[(mon.airport_code == code) & (mon.is_estimated == 0)]
        r = o[o.year >= FEATURE_START_YEAR]
        p = r.dropna(subset=["passengers_total"])
        if p.empty:
            feats.append(dict(airport_code=code)); continue
        mavg = p.groupby("month")["passengers_total"].mean()
        a19 = o[o.year == 2019].set_index("month")["passengers_total"]
        a25 = o[o.year == 2025].set_index("month")["passengers_total"]
        a24 = o[o.year == 2024].set_index("month")["passengers_total"]
        both = a25.index.intersection(a19.index)
        both2 = a25.index.intersection(a24.index)
        pm = r.dropna(subset=["passengers_total", "movements"])
        feats.append(dict(
            airport_code=code, months_used=len(p), avg_monthly_passengers=p.passengers_total.mean(),
            avg_monthly_movements=r.movements.mean(), avg_monthly_cargo_t=r.cargo_tonnes.mean(),
            share_international=(r.passengers_international.sum() / r.dropna(subset=["passengers_international"]).passengers_total.sum())
            if r.passengers_international.notna().any() else np.nan,
            seasonality_summer_index=mavg.reindex([7, 8]).mean() / mavg.mean() if mavg.reindex([7, 8]).notna().all() else np.nan,
            pax_per_movement=pm.passengers_total.sum() / pm.movements.sum() if len(pm) and pm.movements.sum() > 0 else np.nan,
            recovery_2025_vs_2019=a25[both].sum() / a19[both].sum() if len(both) >= 6 and a19[both].sum() > 0 else np.nan,
            growth_2025_vs_2024=a25[both2].sum() / a24[both2].sum() - 1 if len(both2) >= 6 and a24[both2].sum() > 0 else np.nan))
    feats = pd.DataFrame(feats).merge(dim[["airport_code", "airport_name", "region_name", "include_in_clustering"]], on="airport_code")
    feats.to_csv(os.path.join(OUT_DIR, "features_aeroports_kmeans.csv"), index=False, encoding=ENC)

    # ---- 9. reports ----------------------------------------------------------------------------------
    um = pd.DataFrame(unmapped, columns=["label", "file"]).drop_duplicates()
    um.to_csv(os.path.join(OUT_DIR, "qc_unmapped_labels.csv"), index=False, encoding=ENC)
    cov = ts.assign(k=ts.status).pivot_table(index="year", columns="k", values="month", aggfunc="count", fill_value=0)
    cov.to_csv(os.path.join(OUT_DIR, "qc_coverage_by_year.csv"), encoding=ENC)

    rep.add("\n[2] Monthly coverage of the NETWORK series (months per year)")
    rep.add(cov.to_string())
    miss = ts[ts.status == "MISSING"]
    rep.add("months still without any data : %s" % (", ".join("%d-%02d" % (r.year, r.month) for r in miss.itertuples()) or "none"))
    estm = ts[ts.status == "ESTIMATED"]
    rep.add("months ESTIMATED (flag is_estimated=1) : %s" % (", ".join("%d-%02d" % (r.year, r.month) for r in estm.itertuples()) or "none"))
    if len(fz):
        zr = fz[fz.scope == "RESEAU"].date_key.unique()
        zmiss = [("%d-%02d" % (y, mo)) for y, mo in months if y * 100 + mo not in set(zr)]
        rep.add("\nzone-of-origin data (network level) present for %d of %d months; missing: %s" %
                (len(months) - len(zmiss), len(months), ", ".join(zmiss) or "none"))
    sp = fm[fm.passengers_international.notna()].date_key.unique()
    smiss = [("%d-%02d" % (y, mo)) for y, mo in months if y * 100 + mo not in set(sp)]
    rep.add("national/international split present for %d of %d months; missing: %s" %
            (len(months) - len(smiss), len(months), ", ".join(smiss) or "none"))
    rep.add("\n[3] Zero / empty values in fact_trafic_mensuel (observed rows)")
    o = fm[fm.is_estimated == 0]
    rep.add("rows: %d | passengers = 0: %d | movements = 0: %d | cargo = 0: %d" %
            (len(o), (o.passengers_total == 0).sum(), (o.movements == 0).sum(), (o.cargo_tonnes == 0).sum()))
    rep.add("rows with EMPTY (unknown) passengers / movements / cargo: %d / %d / %d  (kept empty, never replaced by 0)" %
            (o.passengers_total.isna().sum(), o.movements.isna().sum(), o.cargo_tonnes.isna().sum()))
    rep.add("\n[4] Source conflicts above %.1f%% : %d rows (qc_conflicts.csv)" % (TOL * 100, len(conf)))
    if len(conf):
        rep.add(conf.groupby("metric").size().to_string())
    rep.add("\n[5] Passengers: traffic table vs national/international table")
    rep.add("rows with a mismatch above %.1f%% : %d of %d" % (TOL * 100, int(fm.flag_split_mismatch.sum()),
                                                            int(fm.passengers_international.notna().sum())))
    if len(chk):
        bad = chk[(chk.months_available == chk.months_expected) & (chk.rel_diff > TOL)]
        rep.add("\n[6] Cumulative control (sum of monthly vs cumulative printed in the report)")
        rep.add("checked: %d | complete-month checks failing > %.1f%%: %d | checks skipped (months missing): %d" %
                (len(chk), TOL * 100, len(bad), int((chk.months_available != chk.months_expected).sum())))
    if "tv" in dir() and len(tv):
        rep.add("\n[6b] ONDA 'TOTAL' row vs sum of airport rows (incl. 'Autres'): %d months differ by > %.1f%% (max %.2f%%) -> qc_total_vs_sum.csv"
                % (int((tv.rel_diff.abs() > TOL).sum()), TOL * 100, tv.rel_diff.abs().max() * 100))
    rep.add("\n[7] Monthly sum vs annual total (observed months only, network level)")
    tot_ann = ann.groupby("year").agg(monthly=("pax_sum_monthly_observed", "sum"),
                                      annual=("pax_total_onda_cumul_dec", "sum"), hcp=("pax_total", "sum") if "pax_total" in ann else ("year", "size"))
    rep.add(tot_ann.to_string())
    rep.add("\n[8] Airport labels that could not be mapped : %d  (qc_unmapped_labels.csv - add them to AIRPORTS)" % len(um))
    if len(um): rep.add(um.groupby("label").size().sort_values(ascending=False).head(15).to_string())
    rep.add("\n[9] Airports in dim_aeroport: %d | selected for clustering: %d" % (len(dim), int(dim.include_in_clustering.sum())))
    low = dim[dim.include_in_clustering == 0]
    if len(low): rep.add("excluded from clustering (too few months / too small): " + ", ".join(low.airport_name))
    rep.add("\nDONE -> " + OUT_DIR)
    with open(os.path.join(OUT_DIR, "qc_report.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(rep.lines))

if __name__ == "__main__":
    main()