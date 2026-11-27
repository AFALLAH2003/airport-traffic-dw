# Data Warehouse: air traffic at Moroccan airports (ONDA)

Data warehouse project on SQL Server (SSIS for the ETL, SSAS for the cube, SSRS for the dashboard), with the data mining done in Python. The subject is the monthly traffic of Moroccan airports: passengers, aircraft movements and cargo.

Team: Bilal (tasks B1 to B6) and Oussama (tasks A1 to A6). Shared tasks C1 to C3.

## What is in this repository

```
.
├── README.md
├── requirements.txt
├── build_clean_data.py        ETL script that builds everything in clean/
├── morocco_airports.csv       airport reference (OurAirports)
├── hcp_raw/                   HCP yearly data (raw)
├── onda_excel/                ONDA monthly reports (raw)
├── onda_pdf/                  ONDA press releases (raw, not used by the script)
├── clean/                     output: dimensions, facts, mining files, quality reports
├── docs/
│   ├── DATA_MAP.md            what each file contains and which task uses it, what is missing
│   └── ETL_SCRIPT_EXPLAINED.md  detailed description of build_clean_data.py
└── exploration/               scripts and reports used to inspect the raw files (B1)
```

Folders for the next tasks will be added here: `sql/` (table creation scripts), `ssis/`, `ssas/`, `mining/` (Python, forecasts, clusters, anomalies), `ssrs/`, `report/`.

## Start here

1. Read [docs/DATA_MAP.md](docs/DATA_MAP.md): the data, the files in `clean/`, the task each one is for, and what is still missing.
2. Open `clean/qc_report.txt` for the quality summary of the last run.
3. To rebuild the data:

```
pip install -r requirements.txt
python build_clean_data.py
```

## Star schema (constellation)

Three fact tables share the same dimensions, because the sources do not have the same grain (explained in `docs/DATA_MAP.md`, section 3).

| Table | Type | Grain |
|---|---|---|
| `fact_trafic_mensuel` | Fact | airport x month |
| `fact_trafic_par_type` | Fact | airport x month x traffic type |
| `fact_passagers_zone` | Fact | month x origin zone (x airport when available) |
| `dim_aeroport` | Dimension | airport (name, city, region) |
| `dim_temps` | Dimension | month (quarter, year, season) |
| `dim_type_trafic` | Dimension | national / international |
| `dim_zone_origine` | Dimension | Europe, Maghreb, Middle/Far East, Africa, Americas, other, domestic |

## Data status

- Monthly data from January 2019 to October 2026.
- 2020 and January to August 2021 have no monthly report: they are estimated and flagged `is_estimated = 1`. Do not use them to detect abnormal months.
- National / international split and origin zone exist for 67 of the 94 months.
- Details and open decisions: `docs/DATA_MAP.md`, sections 6 and 7.

## Tasks

| Task | Who | Status |
|---|---|---|
| B1 Collect the data | Bilal | Done |
| B2 Clean and harmonise, airport reference table | Bilal | Done (`build_clean_data.py`, `dim_aeroport.csv`) |
| B3 ETL of the fact table with quality checks | Bilal | CSV files and quality reports ready, load with SSIS to do |
| B4 SSAS cube | Bilal | To do |
| B5 Clustering | Bilal | Input ready (`features_aeroports_kmeans.csv`) |
| B6 Abnormal periods | Bilal | Input ready (`ts_reseau_mensuel.csv`) |
| A1 Star schema diagram | Oussama | To do |
| A2 Create database and tables | Oussama | To do |
| A3 ETL of the dimensions | Oussama | Input ready (`dim_*.csv`) |
| A4 OLAP and MDX | Oussama | To do |
| A5 Forecast | Oussama | Input ready (`ts_reseau_mensuel.csv`) |
| A6 Dashboard | Oussama | To do |
| C1 to C3 Shared tasks | Both | To do |

## Data sources

- ONDA statistics (monthly reports, Excel).
- HCP (yearly data).
- OurAirports (`morocco_airports.csv`).
