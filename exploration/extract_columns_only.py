import os
import pandas as pd

BASE_DIR = r"D:\DW_project_copy"
OUT_FILE = os.path.join(BASE_DIR, "columns_summary.txt")

out = []

airports_path = os.path.join(BASE_DIR, "morocco_airports.csv")
if os.path.exists(airports_path):
    df_air = pd.read_csv(airports_path, nrows=2)
    out.append(f"[CSV] morocco_airports.csv -> {list(df_air.columns)}")

for folder in ["hcp_raw", "onda_excel"]:
    folder_path = os.path.join(BASE_DIR, folder)
    if not os.path.exists(folder_path):
        continue
    for root, _, files in os.walk(folder_path):
        for f in sorted(files):
            if f.startswith("~$") or not f.lower().endswith((".xlsx", ".xls")):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, BASE_DIR)
            try:
                xl = pd.ExcelFile(full_path)
                out.append(f"\nFILE: {rel_path}")
                for sheet in xl.sheet_names:

                    preview = pd.read_excel(full_path, sheet_name=sheet, header=None, nrows=10)
                    best_row = []
                    for _, row in preview.iterrows():
                        vals = [str(v).strip() for v in row if pd.notna(v) and str(v).strip() != ""]
                        if len(vals) > len(best_row):
                            best_row = vals
                    out.append(f"  - Sheet [{sheet}]: {best_row}")
            except Exception as e:
                out.append(f"\nFILE: {rel_path} -> ERROR: {e}")

with open(OUT_FILE, "w", encoding="utf-8") as fp:
    fp.write("\n".join(out))

print(f"Saved clean column summary to: {OUT_FILE}")