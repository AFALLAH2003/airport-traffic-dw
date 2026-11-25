"""
ETL Pipeline - Projet Data Warehouse: P1 - Trafic aérien des aéroports du Maroc (ONDA)
Stack cible : T2 - SQL Server (ETL/ELT + SSAS + SSRS)

Ce script lit les sources brutes :
  - morocco_airports.csv (OurAirports)
  - onda_raw/*.xls, *.xlsx (ONDA : Dossiers de communication & fichiers 2022)
  - hcp_raw/*.xlsx (HCP : données annuelles 2019-2021 incluant la crise COVID-19 2020)
  - onda_pdf/*.pdf (Communiqués ONDA 2021-2022 : bilan annuel 2020-2021 par zone & aéroport)

Et génère le modèle en étoile / constellation propre et harmonisé dans data_warehouse/ :
  Dimensions :
    - Dim_Aeroport.csv
    - Dim_Temps.csv
    - Dim_Type_Trafic.csv
    - Dim_Zone_Origine.csv
  Tables de faits :
    - Fact_Trafic_Mensuel.csv       (grain: Mois x Aéroport -> passagers, mouvements, fret_tonnes)
    - Fact_Trafic_Par_Type.csv      (grain: Mois x Aéroport x Type_Trafic -> passagers)
    - Fact_Trafic_Par_Zone.csv      (grain: Mois x Aéroport x Zone_Origine -> passagers internationaux)
    - Fact_Trafic_Zone_Global.csv   (grain: Mois x Zone_Origine -> passagers internationaux Maroc)
    - Fact_Trafic_Annuel.csv        (grain: Année x Aéroport -> série annuelle 2019-2025 incl. 2020)
    - Fact_Trafic_Zone_Annuel.csv   (grain: Année x Zone_Origine -> série annuelle 2019-2025 incl. 2020-2021 depuis PDF ONDA)
    - Fact_Top_Routes.csv           (grain: Mois x Scope x Rang -> top 5 routes internationales)
  Schéma SQL Server :
    - sql_server_schema.sql
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
ONDA_RAW_DIR = BASE_DIR / "onda_raw"
HCP_RAW_DIR = BASE_DIR / "hcp_raw"
OURAIRPORTS_CSV = BASE_DIR / "morocco_airports.csv"
OUTPUT_DIR = BASE_DIR / "data_warehouse"

FRENCH_MONTHS: Dict[str, int] = {
    "janvier": 1,
    "fevrier": 2,
    "fev": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "dec": 12,
}

MONTH_NAMES_FR: Dict[int, str] = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}

ISO_REGION_TO_NAME: Dict[str, str] = {
    "MA-01": "Tanger-Tétouan-Al Hoceïma",
    "MA-02": "Oriental",
    "MA-03": "Fès-Meknès",
    "MA-04": "Rabat-Salé-Kénitra",
    "MA-05": "Béni Mellal-Khénifra",
    "MA-06": "Casablanca-Settat",
    "MA-07": "Marrakech-Safi",
    "MA-08": "Drâa-Tafilalet",
    "MA-09": "Souss-Massa",
    "MA-10": "Guelmim-Oued Noun",
    "MA-11": "Laâyoune-Sakia El Hamra",
    "MA-12": "Dakhla-Oued Ed-Dahab",
}


# Référentiel maître des 22 aéroports commerciaux ONDA
# Chaque entrée : (nom_standard, code_iata, code_icao, ville, iso_region, type_defaut, lat_defaut, lon_defaut, nom_complet_defaut)
ONDA_AIRPORTS_MASTER: List[Tuple[str, str, str, str, str, str, float, float, str]] = [
    ("MOHAMMED V", "CMN", "GMMN", "Casablanca", "MA-06", "large_airport", 33.3675, -7.58997, "Mohammed V International Airport"),
    ("MARRAKECH", "RAK", "GMMX", "Marrakech", "MA-07", "large_airport", 31.604807, -8.035788, "Marrakesh Menara Airport"),
    ("AGADIR", "AGA", "GMAD", "Agadir", "MA-09", "large_airport", 30.322478, -9.412003, "Al Massira Airport"),
    ("TANGER", "TNG", "GMTT", "Tanger", "MA-01", "large_airport", 35.731741, -5.921459, "Tangier Ibn Battuta Airport"),
    ("FES-SAISS", "FEZ", "GMFF", "Fès", "MA-03", "large_airport", 33.927299, -4.97796, "Fes Saïss International Airport"),
    ("RABAT-SALE", "RBA", "GMME", "Rabat-Salé", "MA-04", "large_airport", 34.051498, -6.75152, "Rabat-Salé Airport"),
    ("NADOR", "NDR", "GMMW", "Nador", "MA-02", "large_airport", 34.9888, -3.02821, "Nador Al Aaroui International Airport"),
    ("OUJDA", "OUD", "GMFO", "Oujda", "MA-02", "large_airport", 34.789558, -1.926041, "Oujda Angads Airport"),
    ("TETOUAN", "TTU", "GMTN", "Tétouan", "MA-01", "large_airport", 35.594299, -5.32002, "Sania Ramel Airport"),
    ("LAAYOUNE", "EUN", "GMML", "Laâyoune", "MA-11", "medium_airport", 27.1517, -13.2192, "Hassan I Airport"),
    ("DAKHLA", "VIL", "GMMH", "Dakhla", "MA-12", "medium_airport", 23.7183, -15.9320, "Dakhla Airport"),
    ("ESSAOUIRA", "ESU", "GMMI", "Essaouira", "MA-07", "medium_airport", 31.397499, -9.68167, "Essaouira-Mogador Airport"),
    ("OUARZAZATE", "OZZ", "GMMZ", "Ouarzazate", "MA-08", "large_airport", 30.9391, -6.90943, "Ouarzazate International Airport"),
    ("AL-HOCEIMA", "AHU", "GMTA", "Al Hoceïma", "MA-01", "medium_airport", 35.177101, -3.83952, "Cherif Al Idrissi Airport"),
    ("ERRACHIDIA", "ERH", "GMFK", "Errachidia", "MA-08", "medium_airport", 31.9475, -4.39833, "Moulay Ali Cherif Airport"),
    ("GUELMIM", "GLN", "GMAG", "Guelmim", "MA-10", "small_airport", 29.026699, -10.0503, "Guelmim Airport"),
    ("TAN-TAN", "TTA", "GMAT", "Tan-Tan", "MA-10", "medium_airport", 28.447563, -11.161749, "Tan Tan Airport"),
    ("ZAGORA", "OZG", "GMAZ", "Zagora", "MA-08", "large_airport", 30.265788, -5.860808, "Zagora Airport"),
    ("BENSLIMANE", "GMD", "GMMB", "Benslimane", "MA-06", "small_airport", 33.655399, -7.22145, "Ben Slimane Airport"),
    ("BENI MELLAL", "BEM", "GMMD", "Béni Mellal", "MA-05", "large_airport", 32.401895, -6.315905, "Beni Mellal Airport"),
    ("BOUARFA", "UAR", "GMFB", "Bouarfa", "MA-02", "medium_airport", 32.514306, -1.983056, "Bouarfa Airport"),
    ("ES-SMARA", "SMW", "GMMA", "Es-Smara", "MA-11", "small_airport", 26.7318, -11.6847, "Smara Airport"),
]

# Synonymes de noms d'aéroports rencontrés dans ONDA et HCP
AIRPORT_ALIASES: Dict[str, str] = {
    "MOHAMMED V": "MOHAMMED V",
    "MED V": "MOHAMMED V",
    "CMN": "MOHAMMED V",
    "MARRAKECH": "MARRAKECH",
    "MARRAKECH-MENARA": "MARRAKECH",
    "RAK": "MARRAKECH",
    "AGADIR": "AGADIR",
    "AGADIR-INEZGANE": "AGADIR",
    "AGA": "AGADIR",
    "TANGER": "TANGER",
    "TANGER-BOUKHALEF": "TANGER",
    "TNG": "TANGER",
    "FES": "FES-SAISS",
    "FES-SAISS": "FES-SAISS",
    "FES SAISS": "FES-SAISS",
    "FEZ": "FES-SAISS",
    "RABAT SALE": "RABAT-SALE",
    "RABAT-SALE": "RABAT-SALE",
    "RBT": "RABAT-SALE",
    "RBA": "RABAT-SALE",
    "NADOR": "NADOR",
    "NDR": "NADOR",
    "OUJDA": "OUJDA",
    "OUD": "OUJDA",
    "TETOUAN": "TETOUAN",
    "TTU": "TETOUAN",
    "LAAYOUNE": "LAAYOUNE",
    "EUN": "LAAYOUNE",
    "DAKHLA": "DAKHLA",
    "VIL": "DAKHLA",
    "ESSAOUIRA": "ESSAOUIRA",
    "ESU": "ESSAOUIRA",
    "OUARZAZATE": "OUARZAZATE",
    "OZZ": "OUARZAZATE",
    "AL-HOCEIMA": "AL-HOCEIMA",
    "ALHOCEIMA": "AL-HOCEIMA",
    "AL HOCEIMA": "AL-HOCEIMA",
    "AHU": "AL-HOCEIMA",
    "ERRACHIDIA": "ERRACHIDIA",
    "ERH": "ERRACHIDIA",
    "GUELMIM": "GUELMIM",
    "GUELMIME": "GUELMIM",
    "GLN": "GUELMIM",
    "TAN-TAN": "TAN-TAN",
    "TANTAN": "TAN-TAN",
    "TTA": "TAN-TAN",
    "ZAGORA": "ZAGORA",
    "OZG": "ZAGORA",
    "BENSLIMANE": "BENSLIMANE",
    "BEN SLIMANE": "BENSLIMANE",
    "GMD": "BENSLIMANE",
    "BENI MELLAL": "BENI MELLAL",
    "BENI-MELLAL": "BENI MELLAL",
    "BEM": "BENI MELLAL",
    "BOUARFA": "BOUARFA",
    "UAR": "BOUARFA",
    "ES-SMARA": "ES-SMARA",
    "ESSMARA": "ES-SMARA",
    "SMARA": "ES-SMARA",
    "SMW": "ES-SMARA",
}

ZONE_MASTER: List[Tuple[int, str, str, int]] = [
    (1, "EUR", "Europe", 1),
    (2, "MEO", "Moyen et Extrême-Orient", 1),
    (3, "AFR", "Afrique", 1),
    (4, "NAM", "Amérique du Nord", 1),
    (5, "MAG", "Pays du Maghreb", 1),
    (6, "SAM", "Amérique du Sud", 1),
    (7, "AUT", "Autres", 0),
]

ZONE_ALIASES: Dict[str, int] = {
    "EUROPE": 1,
    "MOYEN ET EXTREME ORIENT": 2,
    "AFRIQUE": 3,
    "AFRIQUE (AUTRES RELATIONS)": 3,
    "AMERIQUE DU NORD": 4,
    "PAYS DU MAGHREB": 5,
    "AUTRES PAYS DU MAGHREB": 5,
    "AMERIQUE DU SUD": 6,
    "AUTRES": 7,
    "AUTTRES": 7,
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def norm_key(val: object) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    s = strip_accents(str(val)).upper().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def canonical_airport(val: object) -> Optional[str]:
    k = norm_key(val)
    if not k or k in {"TOTAL", "TOTAL GENERAL", "AUTRES", "AEROPORT", "AEROPORTS"}:
        return None
    return AIRPORT_ALIASES.get(k)


def to_number(val: object) -> Optional[float]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (int, float, np.integer, np.floating)):
        if np.isnan(val):
            return None
        return float(val)
    s = str(val).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s in {"", "-", "nan", "None"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_french_month(text: str) -> Optional[int]:
    k = norm_key(text).lower()
    for name, m in FRENCH_MONTHS.items():
        if re.search(rf"\b{name}\b", k):
            return m
    return None


def parse_year_from_cell(val: object) -> Optional[int]:
    if isinstance(val, (dt.datetime, dt.date, pd.Timestamp)):
        return int(val.year)
    num = to_number(val)
    if num is not None and 2015 <= num <= 2030 and abs(num - round(num)) < 1e-6:
        return int(round(num))
    if isinstance(val, str):
        m = re.search(r"(20[12]\d)", val)
        if m:
            return int(m.group(1))
    return None


def parse_year_month_from_header(val: object, default_month: Optional[int] = None) -> Optional[Tuple[int, int]]:
    if isinstance(val, (dt.datetime, dt.date, pd.Timestamp)):
        return (int(val.year), int(val.month))
    s = str(val) if val is not None else ""
    m = parse_french_month(s)
    y = parse_year_from_cell(s)
    if y and m:
        return (y, m)
    if y and default_month and not ("cumul" in norm_key(s).lower() or "annee" in norm_key(s).lower()):
        return (y, default_month)
    return None


def season_fr(month: int) -> str:
    if month in (12, 1, 2):
        return "Hiver"
    if month in (3, 4, 5):
        return "Printemps"
    if month in (6, 7, 8):
        return "Été"
    return "Automne"


def build_dim_aeroport() -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Construit Dim_Aeroport en combinant le référentiel ONDA et morocco_airports.csv."""
    oa = pd.read_csv(OURAIRPORTS_CSV)
    oa_by_ident = {str(r["ident"]).strip(): r for _, r in oa.iterrows()}

    rows = []
    airport_id_map: Dict[str, int] = {}
    for idx, (nom_std, iata, icao, ville, iso_reg, type_def, lat_def, lon_def, full_def) in enumerate(
        ONDA_AIRPORTS_MASTER, start=1
    ):
        oa_row = oa_by_ident.get(icao)
        if oa_row is None and icao == "GMAG":
            oa_row = oa_by_ident.get("MA-GLN")

        nom_complet = str(oa_row["name"]) if oa_row is not None and pd.notna(oa_row["name"]) else full_def
        type_aero = str(oa_row["type"]) if oa_row is not None and pd.notna(oa_row["type"]) else type_def
        lat = float(oa_row["latitude_deg"]) if oa_row is not None and pd.notna(oa_row["latitude_deg"]) else lat_def
        lon = float(oa_row["longitude_deg"]) if oa_row is not None and pd.notna(oa_row["longitude_deg"]) else lon_def

        rows.append(
            {
                "id_aeroport": idx,
                "code_iata": iata,
                "code_icao": icao,
                "nom_aeroport": nom_std,
                "nom_complet": nom_complet,
                "ville": ville,
                "region": ISO_REGION_TO_NAME[iso_reg],
                "iso_region": iso_reg,
                "type_aeroport": type_aero,
                "latitude_deg": round(lat, 6),
                "longitude_deg": round(lon, 6),
            }
        )
        airport_id_map[nom_std] = idx

    return pd.DataFrame(rows), airport_id_map


def build_dim_type_trafic() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"id_type_trafic": 1, "code_type": "NAT", "libelle_type": "National"},
            {"id_type_trafic": 2, "code_type": "INTER", "libelle_type": "International"},
        ]
    )


def build_dim_zone_origine() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id_zone": zid,
                "code_zone": code,
                "nom_zone": nom,
                "est_zone_detaillee": det,
            }
            for zid, code, nom, det in ZONE_MASTER
        ]
    )


def detect_dossier_report_ym(xl: pd.ExcelFile) -> Tuple[int, int]:
    """Détecte (année, mois) du rapport Dossier ONDA à partir du titre / entêtes."""
    df = pd.read_excel(xl, sheet_name="Trafic aérien par aéroport", header=None)
    # Chercher la ligne de sous-titre contenant le mois et les années (ex: "Août et Cumul à fin Août 2023/2022/2019")
    for r in range(min(10, len(df))):
        val = df.iloc[r, 0]
        if pd.notna(val):
            s = str(val)
            m = parse_french_month(s)
            years = [int(y) for y in re.findall(r"(20[12]\d)", s)]
            if m and years:
                return (max(years), m)
    # Secours : regarder la ligne des mois / années dans les entêtes
    hdr_row = find_row_containing(df, "PASSAGERS")
    if hdr_row is not None and hdr_row + 2 < len(df):
        m = parse_french_month(str(df.iloc[hdr_row + 1, 1]))
        y = parse_year_from_cell(df.iloc[hdr_row + 2, 1])
        if y and m:
            return (y, m)
    raise ValueError("Impossible de détecter (année, mois) du dossier.")


def find_row_containing(
    df: pd.DataFrame, keyword: str, col: Optional[int] = None, exact: bool = False, min_col: int = 0
) -> Optional[int]:
    kw = norm_key(keyword)
    for r in range(len(df)):
        if col is not None:
            cell = norm_key(df.iloc[r, col])
            if (cell == kw) if exact else (kw in cell):
                return r
        else:
            for c in range(min_col, df.shape[1]):
                cell = norm_key(df.iloc[r, c])
                if (cell == kw) if exact else (kw in cell):
                    return r
    return None


def parse_dossier_trafic_aeroport(
    xl: pd.ExcelFile, report_ym: Tuple[int, int]
) -> Tuple[List[dict], List[dict]]:
    """
    Extrait :
      - les données mensuelles (Passagers, Mouvements, Fret) par (Année, Mois, Aéroport)
      - les données CUMUL annuel lorsque report_month == 12 (Décembre -> Année complète)
    """
    df = pd.read_excel(xl, sheet_name="Trafic aérien par aéroport", header=None)
    rep_y, rep_m = report_ym
    prio = rep_y * 100 + rep_m

    hdr_row = find_row_containing(df, "PASSAGERS")
    if hdr_row is None:
        return [], []

    row_metric = df.iloc[hdr_row]
    row_period = df.iloc[hdr_row + 1]
    row_year = df.iloc[hdr_row + 2]

    # Associer chaque colonne à (metric, is_cumul, year)
    current_metric: Optional[str] = None
    current_is_cumul = False
    col_specs: List[Tuple[int, str, bool, int]] = []

    for c in range(1, df.shape[1]):
        m_cell = norm_key(row_metric.iloc[c])
        if "PASSAGER" in m_cell:
            current_metric = "passagers"
        elif "MOUVEMENT" in m_cell:
            current_metric = "mouvements"
        elif "FRET" in m_cell:
            current_metric = "fret_tonnes"

        p_cell = norm_key(row_period.iloc[c])
        if p_cell:
            if "TAUX" in p_cell or "VAR" in p_cell:
                current_is_cumul = False
                continue
            current_is_cumul = "CUMUL" in p_cell

        if "TAUX" in p_cell or "VAR" in p_cell:
            continue

        yr = parse_year_from_cell(row_year.iloc[c])
        if current_metric and yr is not None:
            # Vérifier si la cellule de row_year est une date cumul ou une année mensuelle
            is_cum = current_is_cumul or isinstance(row_year.iloc[c], (dt.datetime, dt.date, pd.Timestamp))
            col_specs.append((c, current_metric, is_cum, yr))

    monthly_rows: List[dict] = []
    annual_rows: List[dict] = []

    for r in range(hdr_row + 3, len(df)):
        aero = canonical_airport(df.iloc[r, 0])
        if aero is None:
            continue

        by_year_monthly: Dict[int, Dict[str, Optional[float]]] = {}
        by_year_annual: Dict[int, Dict[str, Optional[float]]] = {}

        for c, metric, is_cum, yr in col_specs:
            val = to_number(df.iloc[r, c])
            if not is_cum:
                by_year_monthly.setdefault(yr, {})[metric] = val
            elif rep_m == 12:
                by_year_annual.setdefault(yr, {})[metric] = val

        for yr, metrics in by_year_monthly.items():
            monthly_rows.append(
                {
                    "annee": yr,
                    "mois": rep_m,
                    "aeroport": aero,
                    "passagers": metrics.get("passagers"),
                    "mouvements": metrics.get("mouvements"),
                    "fret_tonnes": metrics.get("fret_tonnes"),
                    "priority": prio,
                }
            )

        for yr, metrics in by_year_annual.items():
            annual_rows.append(
                {
                    "annee": yr,
                    "aeroport": aero,
                    "passagers": metrics.get("passagers"),
                    "mouvements": metrics.get("mouvements"),
                    "fret_tonnes": metrics.get("fret_tonnes"),
                    "priority": prio,
                    "source": f"ONDA_DEC_{rep_y}",
                }
            )

    return monthly_rows, annual_rows


def parse_dossier_ventilation_nat_inter(
    xl: pd.ExcelFile, report_ym: Tuple[int, int]
) -> List[dict]:
    """Extrait Ventilation nat-inter (Passagers National & International) d'un Dossier ONDA."""
    df = pd.read_excel(xl, sheet_name="Ventilation nat-inter", header=None)
    rep_y, rep_m = report_ym
    prio = rep_y * 100 + rep_m

    sub_row = find_row_containing(df, "INTERNATIONAL", exact=True, min_col=1)
    if sub_row is None or sub_row < 1:
        return []

    period_row = df.iloc[sub_row - 1]
    type_row = df.iloc[sub_row]

    # Trouver les blocs mensuels (exclure Cumul, Année, Variation, Taux)
    block_year: Optional[int] = None
    block_valid = False
    col_specs: List[Tuple[int, int, str]] = []  # (col_idx, year, type_code)

    for c in range(1, df.shape[1]):
        p_val = period_row.iloc[c]
        if pd.notna(p_val):
            p_str = norm_key(p_val)
            if any(k in p_str for k in ("CUMUL", "ANNEE", "VARIATION", "TAUX", "VAR ")):
                block_valid = False
                block_year = None
            else:
                yr = parse_year_from_cell(p_val)
                if yr is not None:
                    block_year = yr
                    block_valid = True
                else:
                    block_valid = False

        if block_valid and block_year is not None:
            t_str = norm_key(type_row.iloc[c])
            if t_str == "INTERNATIONAL":
                col_specs.append((c, block_year, "INTER"))
            elif t_str == "NATIONAL":
                col_specs.append((c, block_year, "NAT"))

    rows: List[dict] = []
    for r in range(sub_row + 1, len(df)):
        aero = canonical_airport(df.iloc[r, 0])
        if aero is None:
            continue
        for c, yr, tcode in col_specs:
            val = to_number(df.iloc[r, c])
            rows.append(
                {
                    "annee": yr,
                    "mois": rep_m,
                    "aeroport": aero,
                    "type_code": tcode,
                    "passagers": val if val is not None else 0.0,
                    "priority": prio,
                }
            )
    return rows


def parse_region_block(
    df: pd.DataFrame,
    start_col: int,
    end_col: int,
    rep_m: int,
    prio: int,
) -> Tuple[List[dict], List[dict]]:
    """Parse une table verticale Ventilation par région dans une plage de colonnes [start_col, end_col)."""
    global_rows: List[dict] = []
    airport_rows: List[dict] = []

    r = 0
    while r < len(df):
        # Détecter l'entête de section "Trafic Global" ou "Trafic CMN", "Trafic RAK", etc.
        section_name = None
        for c in range(start_col, min(end_col, df.shape[1])):
            val = norm_key(df.iloc[r, c])
            if val.startswith("TRAFIC ") and "AERIEN" not in val:
                section_name = val
                break

        if section_name is None:
            r += 1
            continue

        # Chercher la ligne des années dans les 3 lignes suivantes (première colonne avec années après "Passagers")
        year_cols: List[Tuple[int, int]] = []  # (col_idx, year)
        # La ligne r+1 contient souvent "Passagers | <Mois> | Var | Cumul..."
        # La ligne r+2 contient les années ex: 2024 | 2023.0 | 2024 | 2023.0
        if r + 2 < len(df):
            period_hdr = df.iloc[r + 1]
            year_hdr = df.iloc[r + 2]
            # Identifier uniquement les colonnes du bloc mensuel (avant "CUMUL" ou "ANNEE")
            for c in range(start_col + 1, min(end_col, df.shape[1])):
                p_str = norm_key(period_hdr.iloc[c])
                if any(k in p_str for k in ("CUMUL", "ANNEE")):
                    break
                if any(k in p_str for k in ("TAUX", "VAR")):
                    continue
                yr = parse_year_from_cell(year_hdr.iloc[c])
                if yr is not None:
                    year_cols.append((c, yr))

        if not year_cols:
            r += 1
            continue

        is_global = section_name == "TRAFIC GLOBAL"
        aero = None
        if not is_global:
            code_part = section_name.replace("TRAFIC ", "").strip()
            aero = canonical_airport(code_part)

        rr = r + 3
        while rr < len(df):
            label = norm_key(df.iloc[rr, start_col])
            if not label:
                break
            if "TOTAL" in label:
                rr += 1
                break
            zid = ZONE_ALIASES.get(label)
            if zid is not None:
                for c, yr in year_cols:
                    val = to_number(df.iloc[rr, c])
                    rec = {
                        "annee": yr,
                        "mois": rep_m,
                        "id_zone": zid,
                        "passagers": val if val is not None else 0.0,
                        "priority": prio,
                    }
                    if is_global:
                        global_rows.append(rec)
                    elif aero is not None:
                        airport_rows.append({**rec, "aeroport": aero})
            rr += 1

        r = rr

    return global_rows, airport_rows


def parse_dossier_ventilation_region(
    xl: pd.ExcelFile, report_ym: Tuple[int, int]
) -> Tuple[List[dict], List[dict], List[dict]]:
    df = pd.read_excel(xl, sheet_name="Ventilation par région", header=None)
    rep_y, rep_m = report_ym
    prio = rep_y * 100 + rep_m

    # Certains fichiers (ex: Janvier 2024) ont 2 tableaux côte à côte (col 0..3 et col 5..8)
    global_all: List[dict] = []
    airport_all: List[dict] = []
    annual_zone_all: List[dict] = []

    if df.shape[1] >= 8 and norm_key(df.iloc[3, 6] if len(df) > 3 else "").startswith("TRAFIC"):
        g1, a1 = parse_region_block(df, 0, 4, rep_m, prio)
        g2, a2 = parse_region_block(df, 5, df.shape[1], rep_m, prio)
        global_all.extend(g1 + g2)
        airport_all.extend(a1 + a2)
    else:
        # Vérifier si la colonne 5 contient "Trafic Global"
        has_second_block = False
        if df.shape[1] >= 8:
            for rr in range(min(10, len(df))):
                if "PASSAGERS" == norm_key(df.iloc[rr, 5]):
                    has_second_block = True
                    break
        if has_second_block:
            g1, a1 = parse_region_block(df, 0, 4, rep_m, prio)
            g2, a2 = parse_region_block(df, 5, df.shape[1], rep_m, prio)
            global_all.extend(g1 + g2)
            airport_all.extend(a1 + a2)
        else:
            g1, a1 = parse_region_block(df, 0, df.shape[1], rep_m, prio)
            global_all.extend(g1)
            airport_all.extend(a1)

    # Extraire les totaux annuels par zone depuis les dossiers de Décembre (Cumul Décembre / Année)
    if rep_m == 12:
        r_tg = find_row_containing(df, "TRAFIC GLOBAL")
        if r_tg is not None and r_tg + 2 < len(df):
            period_hdr = df.iloc[r_tg + 1]
            year_hdr = df.iloc[r_tg + 2]
            in_annual = False
            ann_cols: List[Tuple[int, int]] = []
            for c in range(1, df.shape[1]):
                p_str = norm_key(period_hdr.iloc[c])
                if any(k in p_str for k in ("CUMUL", "ANNEE")) and "VAR" not in p_str:
                    in_annual = True
                elif any(k in p_str for k in ("TAUX", "VAR")):
                    in_annual = False
                    continue
                if in_annual:
                    yr = parse_year_from_cell(year_hdr.iloc[c])
                    if yr is not None:
                        ann_cols.append((c, yr))
            rr = r_tg + 3
            while rr < len(df):
                label = norm_key(df.iloc[rr, 0])
                if not label or "TOTAL" in label:
                    break
                zid = ZONE_ALIASES.get(label)
                if zid is not None:
                    for c, yr in ann_cols:
                        val = to_number(df.iloc[rr, c])
                        annual_zone_all.append(
                            {
                                "annee": yr,
                                "id_zone": zid,
                                "passagers": val if val is not None else 0.0,
                                "source": f"ONDA_DEC_{rep_y}",
                                "priority": prio,
                            }
                        )
                rr += 1

    return global_all, airport_all, annual_zone_all


def parse_dossier_top_routes(xl: pd.ExcelFile, report_ym: Tuple[int, int]) -> List[dict]:
    df = pd.read_excel(xl, sheet_name="Top 5 des routes", header=None)
    rep_y, rep_m = report_ym
    prio = rep_y * 100 + rep_m
    rows: List[dict] = []

    r = 0
    while r < len(df):
        title = norm_key(df.iloc[r, 0])
        if title.startswith("TOP 5"):
            scope = "GLOBAL"
            m_scope = re.search(r"\bA\s+(CMN|RAK|AGA|TNG|FEZ|RBA|NDR|OUD)\b", title)
            if m_scope:
                scope = m_scope.group(1)

            # Trouver la ligne d'entête ROUTES AERIENNES
            hdr = r + 1
            while hdr < len(df) and "ROUTES" not in norm_key(df.iloc[hdr, 0]):
                hdr += 1
            if hdr >= len(df):
                break

            # Vérifier l'échelle de Part % via TOTAL INTERNATIONAL si présent
            scale = 1.0
            rr = hdr + 1
            temp_routes = []
            rank = 0
            while rr < len(df):
                route_val = df.iloc[rr, 0]
                if pd.isna(route_val) or not str(route_val).strip():
                    break
                rk = norm_key(route_val)
                if "TOTAL" in rk:
                    tot_pct = to_number(df.iloc[rr, 2])
                    if tot_pct is not None and abs(tot_pct - 1.0) < 0.05:
                        scale = 100.0
                    rr += 1
                    break
                pax = to_number(df.iloc[rr, 1])
                pct = to_number(df.iloc[rr, 2])
                rank += 1
                temp_routes.append((rank, str(route_val).strip(), pax, pct))
                rr += 1

            # Si TOTAL n'a pas clarifié, vérifier si toutes les parts < 0.25 (donc ratio 0..1)
            if scale == 1.0 and temp_routes:
                pcts = [p for _, _, _, p in temp_routes if p is not None]
                if pcts and max(pcts) < 0.35:
                    scale = 100.0

            for rk_idx, route_name, pax, pct in temp_routes:
                rows.append(
                    {
                        "annee": rep_y,
                        "mois": rep_m,
                        "scope_aeroport": scope,
                        "rang": rk_idx,
                        "route": route_name,
                        "passagers": int(round(pax)) if pax is not None else None,
                        "part_pct": round(pct * scale, 4) if pct is not None else None,
                        "priority": prio,
                    }
                )
            r = rr
        else:
            r += 1
    return rows


def parse_2022_standalone_files(onda_dir: Path) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Extrait les fichiers mensuels individuels de 2022 (Février..Juillet 2022/2019) :
      - Ventilation nat-inter (2022 & 2019)
      - Ventilation par région (2022 & 2019) -> global & par aéroport
    """
    nat_inter_rows: List[dict] = []
    reg_global_rows: List[dict] = []
    reg_airport_rows: List[dict] = []

    files = sorted(list(onda_dir.glob("*.xls")) + list(onda_dir.glob("*.xlsx")))
    for f in files:
        fname_norm = norm_key(f.name).lower()
        # Ignorer les fichiers cumulés multi-mois ("07 fev au 31 juillet", "7 fev au 30 avril", "vf")
        if any(k in fname_norm for k in ("au 31", "au 30", "07 fev", "7 fev")):
            continue

        xl = pd.ExcelFile(f)
        if "Trafic aérien par aéroport" in xl.sheet_names:
            continue

        s = xl.sheet_names[0]
        df = pd.read_excel(xl, sheet_name=s, header=None)

        # Vérifier le texte d'entête de la feuille pour ignorer les fichiers multi-mois (ex: "7 fev au 30 avril", "7 fev au 31 juillet")
        header_blob = " ".join(
            norm_key(v)
            for v in df.iloc[: min(12, len(df))].values.flatten()
            if pd.notna(v)
        )
        if any(k in header_blob for k in ("AU 30", "AU 31", "CUMUL")):
            continue

        # 1) Fichiers Ventilation nat-inter mensuels (2019 & 2022)
        if "ventilation" in fname_norm or "trafic aerien global" in fname_norm:
            sub_row = find_row_containing(df, "INTERNATIONAL", exact=True, min_col=1)
            if sub_row is None or sub_row < 1:
                continue
            period_row = df.iloc[sub_row - 1]
            type_row = df.iloc[sub_row]

            # Détecter le mois depuis le titre ou les entêtes
            month = None
            for r_chk in range(sub_row):
                m_chk = parse_french_month(str(df.iloc[r_chk, 0]))
                if m_chk:
                    month = m_chk
                    break
            if month is None:
                month = parse_french_month(f.name)
            if month is None:
                continue

            block_year = None
            col_specs = []
            for c in range(1, df.shape[1]):
                p_val = period_row.iloc[c]
                if pd.notna(p_val):
                    yr = parse_year_from_cell(p_val)
                    if yr is not None:
                        block_year = yr
                if block_year is not None:
                    t_str = norm_key(type_row.iloc[c])
                    if t_str == "INTERNATIONAL":
                        col_specs.append((c, block_year, "INTER"))
                    elif t_str == "NATIONAL":
                        col_specs.append((c, block_year, "NAT"))

            # Priorité plus basse que les Dossiers 2023 (ex: 202200 + month) pour 2019, mais unique pour 2022
            prio = 202200 + month
            for r in range(sub_row + 1, len(df)):
                aero = canonical_airport(df.iloc[r, 0])
                if aero is None:
                    continue
                for c, yr, tcode in col_specs:
                    if yr != 2022:
                        continue
                    val = to_number(df.iloc[r, c])
                    nat_inter_rows.append(
                        {
                            "annee": yr,
                            "mois": month,
                            "aeroport": aero,
                            "type_code": tcode,
                            "passagers": val if val is not None else 0.0,
                            "priority": prio,
                        }
                    )

        # 2) Fichiers Trafic aérien international par secteur géographique et par aéroport (2019 & 2022)
        elif "secteur" in fname_norm:
            hdr_row = find_row_containing(df, "AEROPORT/SECTEUR")
            if hdr_row is None:
                continue
            title_month = parse_french_month(str(df.iloc[1, 0]) if len(df) > 1 else f.name) or parse_french_month(f.name)
            if title_month is None:
                continue

            year_cols = []
            for c in range(1, df.shape[1]):
                yr = parse_year_from_cell(df.iloc[hdr_row, c])
                if yr is not None:
                    year_cols.append((c, yr))
            if not year_cols:
                continue

            # Correctif anomalie source ONDA (Mai 2022) : les entêtes "Mai 2019" et "Mai 2022" sont inversés dans le fichier secteur
            if title_month == 5 and len(year_cols) == 2:
                eur_row = find_row_containing(df, "EUROPE", col=0)
                if eur_row is not None:
                    v0 = to_number(df.iloc[eur_row, year_cols[0][0]]) or 0
                    v1 = to_number(df.iloc[eur_row, year_cols[1][0]]) or 0
                    if v0 > v1 and year_cols[0][1] == 2019 and year_cols[1][1] == 2022:
                        year_cols = [(year_cols[0][0], 2022), (year_cols[1][0], 2019)]

            prio = 202200 + title_month
            current_zone_id: Optional[int] = None
            for r in range(hdr_row + 1, len(df)):
                label = norm_key(df.iloc[r, 0])
                if not label:
                    continue
                if "TOTAL" in label:
                    break
                if label in ZONE_ALIASES:
                    current_zone_id = ZONE_ALIASES[label]
                    for c, yr in year_cols:
                        if yr != 2022:
                            continue
                        val = to_number(df.iloc[r, c])
                        reg_global_rows.append(
                            {
                                "annee": yr,
                                "mois": title_month,
                                "id_zone": current_zone_id,
                                "passagers": val if val is not None else 0.0,
                                "priority": prio,
                            }
                        )
                elif current_zone_id is not None:
                    aero = canonical_airport(label)
                    if aero is not None:
                        for c, yr in year_cols:
                            if yr != 2022:
                                continue
                            val = to_number(df.iloc[r, c])
                            if val is not None:
                                reg_airport_rows.append(
                                    {
                                        "annee": yr,
                                        "mois": title_month,
                                        "aeroport": aero,
                                        "id_zone": current_zone_id,
                                        "passagers": val,
                                        "priority": prio,
                                    }
                                )

    return nat_inter_rows, reg_global_rows, reg_airport_rows


def parse_hcp_and_2020_annual() -> List[dict]:
    """
    Extrait les données annuelles 2019-2021 depuis hcp_raw/ et complète 2020
    (Guelmim & Zagora) depuis le bilan officiel ONDA 2021 (CP+trafic+année+2021+VF.pdf).
    """
    pax_file = next(HCP_RAW_DIR.glob("Nombre de voyageurs*.xlsx"))
    mov_file = next(HCP_RAW_DIR.glob("Mouvements des avions*.xlsx"))

    df_pax = pd.read_excel(pax_file, sheet_name="Données", header=None)
    df_mov = pd.read_excel(mov_file, sheet_name="Données", header=None)

    # Passagers annuels (lignes Total par aéroport)
    years_pax = [int(round(to_number(df_pax.iloc[0, c]))) for c in range(2, df_pax.shape[1])]
    pax_map: Dict[Tuple[int, str], float] = {}
    current_aero = None
    for r in range(2, len(df_pax)):
        if pd.notna(df_pax.iloc[r, 0]):
            current_aero = canonical_airport(df_pax.iloc[r, 0])
        dest = norm_key(df_pax.iloc[r, 1])
        if current_aero and dest == "TOTAL":
            for idx_c, yr in enumerate(years_pax):
                val = to_number(df_pax.iloc[r, 2 + idx_c])
                if val is not None:
                    pax_map[(yr, current_aero)] = val

    # Mouvements annuels
    years_mov = [int(round(to_number(df_mov.iloc[0, c]))) for c in range(1, df_mov.shape[1])]
    mov_map: Dict[Tuple[int, str], float] = {}
    for r in range(2, len(df_mov)):
        aero = canonical_airport(df_mov.iloc[r, 0])
        if aero:
            for idx_c, yr in enumerate(years_mov):
                val = to_number(df_mov.iloc[r, 1 + idx_c])
                if val is not None:
                    mov_map[(yr, aero)] = val

    # Complément officiel ONDA CP+trafic+année+2021+VF.pdf pour 2020 (aéroports absents ou NaN dans HCP)
    onda_2020_extra_pax = {
        "GUELMIM": 3991.0,
        "ZAGORA": 3367.0,
    }
    for aero, val in onda_2020_extra_pax.items():
        pax_map.setdefault((2020, aero), val)

    rows = []
    all_keys = sorted(set(pax_map.keys()) | set(mov_map.keys()))
    for yr, aero in all_keys:
        rows.append(
            {
                "annee": yr,
                "aeroport": aero,
                "passagers": pax_map.get((yr, aero)),
                "mouvements": mov_map.get((yr, aero)),
                "fret_tonnes": None,
                "priority": 202100 if yr in (2019, 2021) else 202012,
                "source": "HCP_ONDA_2020" if yr == 2020 else "HCP",
            }
        )
    return rows


def parse_onda_pdf_2021_zones() -> List[dict]:
    """
    Données officielles extraites du communiqué ONDA 'onda_pdf/CP+trafic+année+2021+VF.pdf' (page 3) :
    Répartition du trafic aérien commercial par faisceau géographique pour 2019, 2020 et 2021.
    """
    pdf_data = {
        # (id_zone, annee): passagers
        (1, 2021): 6994861, (1, 2020): 4907693, (1, 2019): 17477008,  # EUROPE
        (2, 2021): 491099,  (2, 2020): 367649,  (2, 2019): 1741102,   # MOYEN ET EXTREME ORIENT
        (3, 2021): 433638,  (3, 2020): 384457,  (3, 2019): 1368098,   # AFRIQUE
        (4, 2021): 286480,  (4, 2020): 157077,  (4, 2019): 615258,    # AMERIQUE DU NORD
        (5, 2021): 150254,  (5, 2020): 180247,  (5, 2019): 729595,    # PAYS DU MAGHREB
        (6, 2021): 55,      (6, 2020): 24535,   (6, 2019): 137672,    # AMERIQUE DU SUD
    }
    return [
        {
            "annee": yr,
            "id_zone": zid,
            "passagers": pax,
            "source": "ONDA_PDF_2021",
            "priority": 202112,
        }
        for (zid, yr), pax in pdf_data.items()
    ]


def deduplicate_by_priority(df: pd.DataFrame, key_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df.sort_values("priority", ascending=False)
        .drop_duplicates(subset=key_cols, keep="first")
        .drop(columns=["priority"])
        .reset_index(drop=True)
    )


def build_dim_temps(available_ym: set[Tuple[int, int]]) -> pd.DataFrame:
    start = dt.date(2019, 1, 1)
    end = dt.date(2026, 5, 1)
    rows = []
    cur = start
    while cur <= end:
        y, m = cur.year, cur.month
        id_temps = y * 100 + m
        trimestre = (m - 1) // 3 + 1
        semestre = 1 if m <= 6 else 2
        est_covid = 1 if (202003 <= id_temps <= 202202) else 0
        rows.append(
            {
                "id_temps": id_temps,
                "date_debut_mois": cur.strftime("%Y-%m-%d"),
                "annee": y,
                "mois": m,
                "nom_mois": MONTH_NAMES_FR[m],
                "trimestre": trimestre,
                "nom_trimestre": f"T{trimestre}",
                "semestre": semestre,
                "saison": season_fr(m),
                "est_periode_covid": est_covid,
                "donnees_mensuelles_disponibles": 1 if (y, m) in available_ym else 0,
            }
        )
        # Mois suivant
        if m == 12:
            cur = dt.date(y + 1, 1, 1)
        else:
            cur = dt.date(y, m + 1, 1)
    return pd.DataFrame(rows)


def write_sql_server_schema(path: Path) -> None:
    sql = """-- ============================================================================
-- Schéma SQL Server - Entrepôt de Données : P1 - Trafic aérien ONDA (Maroc)
-- Compatible SQL Server (T-SQL) + SSAS (Multidimensionnel / Tabulaire) + SSRS
-- ============================================================================

IF DB_ID('DW_Trafic_Aerien_ONDA') IS NULL
    CREATE DATABASE DW_Trafic_Aerien_ONDA;
GO
USE DW_Trafic_Aerien_ONDA;
GO

-- 1. Dimensions
CREATE TABLE dbo.Dim_Aeroport (
    id_aeroport   INT           NOT NULL PRIMARY KEY,
    code_iata     VARCHAR(10)   NOT NULL,
    code_icao     VARCHAR(10)   NOT NULL,
    nom_aeroport  NVARCHAR(100) NOT NULL,
    nom_complet   NVARCHAR(150) NOT NULL,
    ville         NVARCHAR(100) NOT NULL,
    region        NVARCHAR(100) NOT NULL,
    iso_region    VARCHAR(10)   NOT NULL,
    type_aeroport VARCHAR(30)   NOT NULL,
    latitude_deg  DECIMAL(10,6) NOT NULL,
    longitude_deg DECIMAL(10,6) NOT NULL
);

CREATE TABLE dbo.Dim_Temps (
    id_temps                       INT          NOT NULL PRIMARY KEY, -- YYYYMM
    date_debut_mois                DATE         NOT NULL,
    annee                          SMALLINT     NOT NULL,
    mois                           TINYINT      NOT NULL,
    nom_mois                       NVARCHAR(20) NOT NULL,
    trimestre                      TINYINT      NOT NULL,
    nom_trimestre                  VARCHAR(5)   NOT NULL,
    semestre                       TINYINT      NOT NULL,
    saison                         NVARCHAR(20) NOT NULL,
    est_periode_covid              BIT          NOT NULL,
    donnees_mensuelles_disponibles BIT          NOT NULL
);

CREATE TABLE dbo.Dim_Type_Trafic (
    id_type_trafic INT          NOT NULL PRIMARY KEY,
    code_type      VARCHAR(10)  NOT NULL,
    libelle_type   NVARCHAR(30) NOT NULL
);

CREATE TABLE dbo.Dim_Zone_Origine (
    id_zone            INT          NOT NULL PRIMARY KEY,
    code_zone          VARCHAR(10)  NOT NULL,
    nom_zone           NVARCHAR(60) NOT NULL,
    est_zone_detaillee BIT          NOT NULL
);

-- 2. Tables de faits
CREATE TABLE dbo.Fact_Trafic_Mensuel (
    id_temps    INT            NOT NULL,
    id_aeroport INT            NOT NULL,
    passagers   INT            NULL,
    mouvements  INT            NULL,
    fret_tonnes DECIMAL(12,3)  NULL,
    CONSTRAINT PK_Fact_Trafic_Mensuel PRIMARY KEY (id_temps, id_aeroport),
    CONSTRAINT FK_Mensuel_Temps       FOREIGN KEY (id_temps)    REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_Mensuel_Aeroport    FOREIGN KEY (id_aeroport) REFERENCES dbo.Dim_Aeroport(id_aeroport)
);

CREATE TABLE dbo.Fact_Trafic_Par_Type (
    id_temps       INT NOT NULL,
    id_aeroport    INT NOT NULL,
    id_type_trafic INT NOT NULL,
    passagers      INT NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Par_Type PRIMARY KEY (id_temps, id_aeroport, id_type_trafic),
    CONSTRAINT FK_Type_Temps           FOREIGN KEY (id_temps)       REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_Type_Aeroport        FOREIGN KEY (id_aeroport)    REFERENCES dbo.Dim_Aeroport(id_aeroport),
    CONSTRAINT FK_Type_TypeTrafic      FOREIGN KEY (id_type_trafic) REFERENCES dbo.Dim_Type_Trafic(id_type_trafic)
);

CREATE TABLE dbo.Fact_Trafic_Par_Zone (
    id_temps    INT NOT NULL,
    id_aeroport INT NOT NULL,
    id_zone     INT NOT NULL,
    passagers   INT NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Par_Zone PRIMARY KEY (id_temps, id_aeroport, id_zone),
    CONSTRAINT FK_Zone_Temps           FOREIGN KEY (id_temps)    REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_Zone_Aeroport        FOREIGN KEY (id_aeroport) REFERENCES dbo.Dim_Aeroport(id_aeroport),
    CONSTRAINT FK_Zone_Origine         FOREIGN KEY (id_zone)     REFERENCES dbo.Dim_Zone_Origine(id_zone)
);

CREATE TABLE dbo.Fact_Trafic_Zone_Global (
    id_temps  INT NOT NULL,
    id_zone   INT NOT NULL,
    passagers INT NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Zone_Global PRIMARY KEY (id_temps, id_zone),
    CONSTRAINT FK_ZoneGlobal_Temps        FOREIGN KEY (id_temps) REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_ZoneGlobal_Zone         FOREIGN KEY (id_zone)  REFERENCES dbo.Dim_Zone_Origine(id_zone)
);

CREATE TABLE dbo.Fact_Trafic_Annuel (
    annee       SMALLINT      NOT NULL,
    id_aeroport INT           NOT NULL,
    passagers   INT           NULL,
    mouvements  INT           NULL,
    fret_tonnes DECIMAL(12,3) NULL,
    source      VARCHAR(30)   NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Annuel PRIMARY KEY (annee, id_aeroport),
    CONSTRAINT FK_Annuel_Aeroport    FOREIGN KEY (id_aeroport) REFERENCES dbo.Dim_Aeroport(id_aeroport)
);

CREATE TABLE dbo.Fact_Trafic_Zone_Annuel (
    annee     SMALLINT    NOT NULL,
    id_zone   INT         NOT NULL,
    passagers INT         NOT NULL,
    source    VARCHAR(30) NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Zone_Annuel PRIMARY KEY (annee, id_zone),
    CONSTRAINT FK_ZoneAnnuel_Zone         FOREIGN KEY (id_zone) REFERENCES dbo.Dim_Zone_Origine(id_zone)
);

CREATE TABLE dbo.Fact_Top_Routes (
    id_temps       INT            NOT NULL,
    scope_aeroport VARCHAR(10)    NOT NULL,
    rang           TINYINT        NOT NULL,
    route          NVARCHAR(100)  NOT NULL,
    passagers      INT            NULL,
    part_pct       DECIMAL(8,4)   NULL,
    CONSTRAINT PK_Fact_Top_Routes PRIMARY KEY (id_temps, scope_aeroport, rang),
    CONSTRAINT FK_Routes_Temps    FOREIGN KEY (id_temps) REFERENCES dbo.Dim_Temps(id_temps)
);
GO
"""
    path.write_text(sql, encoding="utf-8")


def run_etl() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    dim_aeroport, airport_id_map = build_dim_aeroport()
    dim_type = build_dim_type_trafic()
    dim_zone = build_dim_zone_origine()

    monthly_rows: List[dict] = []
    annual_rows: List[dict] = []
    nat_inter_rows: List[dict] = []
    reg_global_rows: List[dict] = []
    reg_airport_rows: List[dict] = []
    reg_annual_rows: List[dict] = []
    top_routes_rows: List[dict] = []

    dossier_files = sorted(
        list(ONDA_RAW_DIR.glob("*.xls")) + list(ONDA_RAW_DIR.glob("*.xlsx"))
    )

    dossier_count = 0
    for f in dossier_files:
        xl = pd.ExcelFile(f)
        if "Trafic aérien par aéroport" not in xl.sheet_names:
            continue
        dossier_count += 1
        rep_ym = detect_dossier_report_ym(xl)
        m_rows, a_rows = parse_dossier_trafic_aeroport(xl, rep_ym)
        monthly_rows.extend(m_rows)
        annual_rows.extend(a_rows)

        if "Ventilation nat-inter" in xl.sheet_names:
            nat_inter_rows.extend(parse_dossier_ventilation_nat_inter(xl, rep_ym))
        if "Ventilation par région" in xl.sheet_names:
            g_rows, ap_rows, az_rows = parse_dossier_ventilation_region(xl, rep_ym)
            reg_global_rows.extend(g_rows)
            reg_airport_rows.extend(ap_rows)
            reg_annual_rows.extend(az_rows)
        if "Top 5 des routes" in xl.sheet_names:
            top_routes_rows.extend(parse_dossier_top_routes(xl, rep_ym))

    # Ajouter les fichiers 2022 individuels (Ventilation nat-inter & par région pour Fév-Juil 2022)
    ni_2022, rg_2022, ra_2022 = parse_2022_standalone_files(ONDA_RAW_DIR)
    nat_inter_rows.extend(ni_2022)
    reg_global_rows.extend(rg_2022)
    reg_airport_rows.extend(ra_2022)

    # Ajouter les données annuelles HCP + PDF ONDA 2020-2021
    annual_rows.extend(parse_hcp_and_2020_annual())
    reg_annual_rows.extend(parse_onda_pdf_2021_zones())

    # 1) Fact_Trafic_Mensuel
    df_monthly = deduplicate_by_priority(
        pd.DataFrame(monthly_rows), ["annee", "mois", "aeroport"]
    )
    df_monthly["id_temps"] = df_monthly["annee"] * 100 + df_monthly["mois"]
    df_monthly["id_aeroport"] = df_monthly["aeroport"].map(airport_id_map)
    df_monthly["passagers"] = df_monthly["passagers"].fillna(0).round().astype("Int64")
    df_monthly["mouvements"] = df_monthly["mouvements"].fillna(0).round().astype("Int64")
    df_monthly["fret_tonnes"] = df_monthly["fret_tonnes"].fillna(0.0).round(3)
    fact_mensuel = (
        df_monthly[["id_temps", "id_aeroport", "passagers", "mouvements", "fret_tonnes"]]
        .sort_values(["id_temps", "id_aeroport"])
        .reset_index(drop=True)
    )

    available_ym = set(zip(df_monthly["annee"].astype(int), df_monthly["mois"].astype(int)))
    dim_temps = build_dim_temps(available_ym)

    # 2) Fact_Trafic_Par_Type
    type_id_map = {"NAT": 1, "INTER": 2}
    df_type = deduplicate_by_priority(
        pd.DataFrame(nat_inter_rows), ["annee", "mois", "aeroport", "type_code"]
    )
    df_type["id_temps"] = df_type["annee"] * 100 + df_type["mois"]
    df_type["id_aeroport"] = df_type["aeroport"].map(airport_id_map)
    df_type["id_type_trafic"] = df_type["type_code"].map(type_id_map)
    df_type["passagers"] = df_type["passagers"].fillna(0).round().astype("Int64")
    fact_par_type = (
        df_type[["id_temps", "id_aeroport", "id_type_trafic", "passagers"]]
        .sort_values(["id_temps", "id_aeroport", "id_type_trafic"])
        .reset_index(drop=True)
    )

    # 3) Fact_Trafic_Par_Zone
    df_reg_ap = deduplicate_by_priority(
        pd.DataFrame(reg_airport_rows), ["annee", "mois", "aeroport", "id_zone"]
    )
    df_reg_ap["id_temps"] = df_reg_ap["annee"] * 100 + df_reg_ap["mois"]
    df_reg_ap["id_aeroport"] = df_reg_ap["aeroport"].map(airport_id_map)
    df_reg_ap["passagers"] = df_reg_ap["passagers"].fillna(0).round().astype("Int64")
    fact_par_zone = (
        df_reg_ap[["id_temps", "id_aeroport", "id_zone", "passagers"]]
        .sort_values(["id_temps", "id_aeroport", "id_zone"])
        .reset_index(drop=True)
    )

    # 4) Fact_Trafic_Zone_Global
    df_reg_gl = deduplicate_by_priority(
        pd.DataFrame(reg_global_rows), ["annee", "mois", "id_zone"]
    )
    df_reg_gl["id_temps"] = df_reg_gl["annee"] * 100 + df_reg_gl["mois"]
    df_reg_gl["passagers"] = df_reg_gl["passagers"].fillna(0).round().astype("Int64")
    fact_zone_global = (
        df_reg_gl[["id_temps", "id_zone", "passagers"]]
        .sort_values(["id_temps", "id_zone"])
        .reset_index(drop=True)
    )

    # 5) Fact_Trafic_Annuel
    df_annual = deduplicate_by_priority(
        pd.DataFrame(annual_rows), ["annee", "aeroport"]
    )
    df_annual["id_aeroport"] = df_annual["aeroport"].map(airport_id_map)
    df_annual["passagers"] = df_annual["passagers"].round().astype("Int64")
    df_annual["mouvements"] = df_annual["mouvements"].round().astype("Int64")
    df_annual["fret_tonnes"] = pd.to_numeric(df_annual["fret_tonnes"], errors="coerce").round(3)
    fact_annuel = (
        df_annual[["annee", "id_aeroport", "passagers", "mouvements", "fret_tonnes", "source"]]
        .sort_values(["annee", "id_aeroport"])
        .reset_index(drop=True)
    )

    # 6) Fact_Trafic_Zone_Annuel
    df_zone_ann = deduplicate_by_priority(
        pd.DataFrame(reg_annual_rows), ["annee", "id_zone"]
    )
    df_zone_ann["passagers"] = df_zone_ann["passagers"].fillna(0).round().astype("Int64")
    fact_zone_annuel = (
        df_zone_ann[["annee", "id_zone", "passagers", "source"]]
        .sort_values(["annee", "id_zone"])
        .reset_index(drop=True)
    )

    # 7) Fact_Top_Routes
    df_routes = deduplicate_by_priority(
        pd.DataFrame(top_routes_rows), ["annee", "mois", "scope_aeroport", "rang"]
    )
    df_routes["id_temps"] = df_routes["annee"] * 100 + df_routes["mois"]
    df_routes["passagers"] = df_routes["passagers"].astype("Int64")
    fact_top_routes = (
        df_routes[["id_temps", "scope_aeroport", "rang", "route", "passagers", "part_pct"]]
        .sort_values(["id_temps", "scope_aeroport", "rang"])
        .reset_index(drop=True)
    )

    # Sauvegarde en UTF-8 (avec BOM UTF-8-sig pour compatibilité SQL Server / Excel)
    outputs = {
        "Dim_Aeroport.csv": dim_aeroport,
        "Dim_Temps.csv": dim_temps,
        "Dim_Type_Trafic.csv": dim_type,
        "Dim_Zone_Origine.csv": dim_zone,
        "Fact_Trafic_Mensuel.csv": fact_mensuel,
        "Fact_Trafic_Par_Type.csv": fact_par_type,
        "Fact_Trafic_Par_Zone.csv": fact_par_zone,
        "Fact_Trafic_Zone_Global.csv": fact_zone_global,
        "Fact_Trafic_Annuel.csv": fact_annuel,
        "Fact_Trafic_Zone_Annuel.csv": fact_zone_annuel,
        "Fact_Top_Routes.csv": fact_top_routes,
    }
    for fname, table in outputs.items():
        table.to_csv(OUTPUT_DIR / fname, index=False, encoding="utf-8-sig")

    write_sql_server_schema(OUTPUT_DIR / "sql_server_schema.sql")

    print(f"Dossiers ONDA traités : {dossier_count}")
    for fname, table in outputs.items():
        print(f"  -> {fname:30s} : {len(table):6d} lignes | colonnes={list(table.columns)}")


if __name__ == "__main__":
    run_etl()
