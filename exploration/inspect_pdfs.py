import os

BASE_DIR = r"D:\DW_project_copy"
PDF_DIR = os.path.join(BASE_DIR, "onda_pdf")
OUT_FILE = os.path.join(BASE_DIR, "columns_summary.txt")

pdf_lines = ["\n" + "=" * 60, "SECTION: onda_pdf", "=" * 60]

try:
    import pypdf
    reader_type = "pypdf"
except ImportError:
    try:
        import fitz
        reader_type = "fitz"
    except ImportError:
        reader_type = None

if not os.path.exists(PDF_DIR):
    pdf_lines.append("Folder onda_pdf not found.")
elif reader_type is None:
    pdf_lines.append("No PDF library installed (install with: pip install pypdf)")
else:
    for root, _, files in os.walk(PDF_DIR):
        for f in sorted(files):
            if not f.lower().endswith(".pdf"):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, BASE_DIR)
            pdf_lines.append(f"\n[PDF] {rel_path}")
            try:
                if reader_type == "pypdf":
                    reader = pypdf.PdfReader(full_path)
                    pdf_lines.append(f"  Pages: {len(reader.pages)}")
                    for i, page in enumerate(reader.pages[:3]):
                        txt = " ".join((page.extract_text() or "").split())
                        pdf_lines.append(f"  Page {i+1} preview: {txt[:400]}")
                elif reader_type == "fitz":
                    doc = fitz.open(full_path)
                    pdf_lines.append(f"  Pages: {len(doc)}")
                    for i in range(min(3, len(doc))):
                        txt = " ".join((doc[i].get_text() or "").split())
                        pdf_lines.append(f"  Page {i+1} preview: {txt[:400]}")
            except Exception as e:
                pdf_lines.append(f"  ERROR reading PDF: {e}")

with open(OUT_FILE, "a", encoding="utf-8") as fp:
    fp.write("\n".join(pdf_lines) + "\n")

print(f"Appended onda_pdf summary to: {OUT_FILE}")