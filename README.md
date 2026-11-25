# Moroccan Airports Air Traffic Data Warehouse (ONDA)

Data warehouse and analytics project covering commercial air traffic across Moroccan airports from 2019 to 2026 (passengers, aircraft movements, cargo, traffic types, geographical zones, and top international routes)[cite: 24, 29].

## Data Sources
- **ONDA**: Monthly and annual traffic reports (airport traffic, domestic vs. international breakdown, geographical zones, top routes, and 2022/2019 comparison files)[cite: 29].
- **HCP**: Annual official statistics on commercial passengers and aircraft movements (2019–2021, including the 2020 COVID-19 drop)[cite: 29].
- **OurAirports**: Airport reference metadata (`morocco_airports.csv` with ICAO/IATA codes, airport types, and coordinates)[cite: 29].

## Warehouse Structure
Prepared datasets are generated in `data_warehouse/` via `etl_prepare_dw.py` and defined for SQL Server in `sql_server_schema.sql`[cite: 29]:

- **Dimensions**: `Dim_Aeroport`, `Dim_Temps`, `Dim_Type_Trafic`, `Dim_Zone_Origine`[cite: 29]
- **Facts**: `Fact_Trafic_Mensuel`, `Fact_Trafic_Par_Type`, `Fact_Trafic_Par_Zone`, `Fact_Trafic_Zone_Global`, `Fact_Trafic_Annuel`, `Fact_Top_Routes`[cite: 29]

## Planned Stack & Workflow
1. **Data Collection & ETL**: Python (`pandas`) cleaning and harmonization (`etl_prepare_dw.py`), followed by SQL Server / SSIS loading and validation[cite: 25, 27, 29].
2. **OLAP & Data Mining**: SQL Server Analysis Services (SSAS / MDX) for multi-dimensional analysis, plus Python (`scikit-learn`, `statsmodels` / `Prophet`) for clustering, time-series forecasting, and anomaly detection.
3. **Reporting**: SQL Server Reporting Services (SSRS) dashboards and charts[cite: 25, 26].

## Current Status
- [x] Raw data collection and Python ETL preparation (`data_warehouse/*.csv`)[cite: 29]
- [x] Git repository setup (`Onda-Data-Warehouse`)[cite: 21]
- [ ] SQL Server schema creation and data load[cite: 25, 26, 27]
- [ ] SSAS cube, Python analytics models, and SSRS dashboard[cite: 25, 26, 27]