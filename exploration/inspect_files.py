import os
import pandas as pd

BASE_DIR = r"D:\DW_project_copy"
REPORT_PATH = os.path.join(BASE_DIR, "files_structure_report.txt")

lines = []

def log(text=""):
    print(text)
    lines.append(str(text))

airports_file = os.path.join(BASE_DIR, "morocco_airports.csv")
log("=" * 80)
log("1. FILE: morocco_airports.csv")
log("=" * 80)
if os.path.exists(airports_file):
    df = pd.read_csv(airports_file)
    log(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    log(f"Columns: {list(df.columns)}")
    log("Sample (first 3 rows):")
    log(df.head(3).to_string(index=False))
else:
    log("File not found.")

def inspect_excel_folder(folder_name):
    folder_path = os.path.join(BASE_DIR, folder_name)
    log("\n" + "=" * 80)
    log(f"FOLDER: {folder_name}")
    log("=" * 80)
    if not os.path.exists(folder_path):
        log("Folder not found.")
        return

    for root, _, files in os.walk(folder_path):
        for file in sorted(files):
            if file.startswith("~$") or not file.lower().endswith((".xlsx", ".xls")):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, BASE_DIR)
            log(f"\n--- File: {rel_path} ---")
            try:
                xl = pd.ExcelFile(full_path)
                log(f"Sheets ({len(xl.sheet_names)}): {xl.sheet_names}")
                for sheet in xl.sheet_names:
                    preview = pd.read_excel(full_path, sheet_name=sheet, header=None, nrows=8)
                    log(f"  [Sheet: {sheet}]")
                    for idx, row in preview.iterrows():
                        non_empty = [f"C{c}:{str(val).strip()}" for c, val in enumerate(row) if pd.notna(val) and str(val).strip() != ""]
                        if non_empty:
                            log(f"    Row {idx}: " + " | ".join(non_empty[:10]))
            except Exception as e:
                log(f"  ERROR reading file: {e}")


inspect_excel_folder("hcp_raw")

inspect_excel_folder("onda_excel")

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\nDone! Report saved to: {REPORT_PATH}")