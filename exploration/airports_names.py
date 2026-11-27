import os
import pandas as pd

BASE_DIR = r"D:\DW_project_copy"


for f in os.listdir(os.path.join(BASE_DIR, "hcp_raw")):
    if f.endswith(".xlsx") and not f.startswith("~$"):
        df = pd.read_excel(os.path.join(BASE_DIR, "hcp_raw", f), sheet_name="Données", header=None)
        print("HCP:", f, "->", [x for x in df[0].dropna().astype(str).str.strip().unique() if x not in ("Périodes", "Aéroport")])

airports_onda = set()
for root, _, files in os.walk(os.path.join(BASE_DIR, "onda_excel")):
    for f in files:
        if f.endswith((".xlsx", ".xls")) and not f.startswith("~$"):
            p = os.path.join(root, f)
            xl = pd.ExcelFile(p)
            for s in ["Ventilation nat-inter", "Trafic aérien par aéroport"]:
                if s in xl.sheet_names:
                    df = pd.read_excel(p, sheet_name=s, header=None)
                    for val in df[0].dropna().astype(str).str.strip():
                        if len(val) < 35 and not any(k in val.lower() for k in ["trafic", "ventilation", "aeroport", "total", "cumul", "passagers", "mouvements"]):
                            airports_onda.add(val)

print("\nONDA unique airport labels:", sorted(airports_onda))