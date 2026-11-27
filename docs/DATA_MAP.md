# Data map

This document explains what data we have, where it comes from, what each file in `clean/` contains, and which task of the project uses it. It also lists what is still missing, so nobody is surprised later.

Task names (A1..A6, B1..B6, C1..C3) are the ones from the project brief. Bilal does the B tasks, Oussama does the A tasks.

## 1. Sources

| Source | Folder / file | What it contains | Granularity |
|---|---|---|---|
| ONDA monthly reports (Excel) | `onda_excel/` | Passengers, aircraft movements and cargo per airport. National / international split per airport. International passengers per geographic zone. | Monthly (with a cumulative column) |
| HCP | `hcp_raw/` | Aircraft movements and passengers (arrivals, departures, transit) per airport | Yearly, 2019 to 2021 |
| OurAirports | `morocco_airports.csv` | 45 Moroccan airports: IATA code, city, ISO region, coordinates, type | Static reference |
| ONDA press releases (PDF) | `onda_pdf/` | Yearly and half-year summaries 2021 and 2022 | Not used (see section 6) |

The brief suggests ourairports.com, but that site only has airport locations, not passenger counts. So the traffic numbers come from the official ONDA statistics and the airport reference (city, region, coordinates) comes from OurAirports.

The raw files are messy: the column layout changes from one year to another, the same month appears in several reports, and airport names are written in many ways (`MOHAMMED V`, `MED V`, `ALHOCEIMA`, `GUELMIME`...). Everything is cleaned by one script, `build_clean_data.py`, described in [ETL_SCRIPT_EXPLAINED.md](ETL_SCRIPT_EXPLAINED.md). Running it rebuilds the whole `clean/` folder.

## 2. Files in `clean/`

### Dimensions

| File | Rows | Key | Content |
|---|---|---|---|
| `dim_aeroport.csv` | 22 | `airport_code` | Airport name, city, region (ISO code and name), type, coordinates, `include_in_clustering`, `is_aggregate` |
| `dim_temps.csv` | 94 | `date_key` (YYYYMM) | Date, year, quarter, month, season, COVID phase. From 2019-01 to 2026-10 |
| `dim_type_trafic.csv` | 2 | `type_code` | `INT` international, `NAT` national |
| `dim_zone_origine.csv` | 8 | `zone_code` | Europe, Maghreb, Middle/Far East, Africa, North America, South America, Other, and `DOM` (domestic, used for national traffic) |

### Fact tables

We use three fact tables, not one (a constellation schema). The reason is that the sources do not have the same grain: see section 3.

| File | Grain | Measures | Key columns |
|---|---|---|---|
| `fact_trafic_mensuel.csv` | airport x month | `passengers_total`, `passengers_international`, `passengers_national`, `movements`, `cargo_tonnes` | `airport_code`, `date_key` |
| `fact_trafic_par_type.csv` | airport x month x traffic type | `passengers` | `airport_code`, `date_key`, `type_code` |
| `fact_passagers_zone.csv` | month x zone (network level) or airport x month x zone | `passengers_international` | `date_key`, `zone_code`, `airport_code` (empty at network level), `scope` |

Quality columns in `fact_trafic_mensuel.csv`:

- `is_estimated` is 1 when the row was rebuilt by us and not read from a report. `estimation_method` says how.
- `src_passengers`, `src_movements`, `src_cargo`, `src_split` give the source file of each value.
- `flag_zero_passengers`, `flag_split_mismatch` (national + international differs from the total by more than 0.5%), `flag_pax_from_split`.

### Annual table (kept out of the cube)

| File | Content |
|---|---|
| `fact_trafic_annuel.csv` | Per airport and year: HCP totals, the December cumulative of ONDA, the sum of our monthly values, and the ratio between them. Used only to check the monthly data. |

### Files prepared for data mining

| File | Content |
|---|---|
| `ts_reseau_mensuel.csv` | One row per month (2019-01 to 2026-10) for the whole network, with a `status` column (OBSERVED / ESTIMATED / MISSING) |
| `panel_aeroport_mois_complet.csv` | Full airport x month grid with a `status`, so time series can be built per airport |
| `features_aeroports_kmeans.csv` | One row per airport: average traffic, share of international traffic, seasonality, passengers per movement, recovery 2025 vs 2019, growth 2025 vs 2024 |

### Quality control files

`qc_report.txt` is the one to read first. The other files are the detail behind it.

| File | What it shows |
|---|---|
| `qc_report.txt` | Summary of the run: coverage, zeros, conflicts, checks |
| `qc_coverage_by_year.csv` | Number of observed / estimated months per year |
| `qc_conflicts.csv` | Values that differ by more than 0.5% between two reports |
| `qc_cumul_check.csv` | Sum of the monthly values compared with the cumulative figure printed in the report |
| `qc_total_vs_sum.csv` | ONDA's TOTAL row compared with the sum of the airport rows |
| `qc_duplicate_labels.csv` | Two labels in one report mapped to the same airport |
| `qc_unmapped_labels.csv` | Airport names the script did not recognise (currently empty) |

## 3. Why three fact tables

The brief asks for one fact table with the grain airport x month x traffic type x origin zone. The data does not allow it:

- Passengers by origin zone exist only for international traffic, and mostly as network totals.
- Movements and cargo exist only per airport and month, with no split by type or zone.
- The national / international split exists per airport, but without the zone.

A single table at the finest grain would be almost empty, or would force invented values. So each fact table keeps the real grain of its source, and they share the same dimensions. The domestic member `DOM` in the zone dimension is there so national traffic has a valid zone key. `fact_trafic_annuel` and the top routes are not linked cleanly to the time and airport dimensions, so they stay out of the SSAS cube (the top routes table is not built at all).

## 4. Which task uses which file

| Task | Person | Files |
|---|---|---|
| A1 Star schema | Oussama | Section 3 of this document, the column lists above |
| A2 Create the database and tables | Oussama | Column names of all `dim_*` and `fact_*` files |
| A3 ETL of the dimensions | Oussama | `dim_aeroport`, `dim_temps`, `dim_type_trafic`, `dim_zone_origine` |
| A4 OLAP / MDX | Oussama | The cube built in B4 |
| A5 Forecast | Oussama | `ts_reseau_mensuel`, `panel_aeroport_mois_complet` |
| A6 Dashboard | Oussama | The warehouse tables and the results of A5, B5, B6 |
| B1 Collect the data | Bilal | `onda_excel/`, `hcp_raw/`, `morocco_airports.csv` |
| B2 Clean and harmonise | Bilal | `build_clean_data.py`, `dim_aeroport` (reference table of airports and regions) |
| B3 ETL of the fact table with quality checks | Bilal | `fact_trafic_mensuel`, `fact_trafic_par_type`, `fact_passagers_zone`, all `qc_*` files |
| B4 SSAS cube | Bilal | All dimensions and the three fact tables (not the annual table) |
| B5 Clustering | Bilal | `features_aeroports_kmeans` (only rows with `include_in_clustering = 1`) |
| B6 Abnormal periods | Bilal | `ts_reseau_mensuel` and `panel_aeroport_mois_complet`, observed rows only |
| C2 Load mining results into SQL Server | both | Output tables of A5, B5, B6 |

## 5. Coverage

The period is 2019-01 to 2026-10, which is 94 months. At network level:

| Year | Observed months | Estimated months |
|---|---|---|
| 2019 | 12 | 0 |
| 2020 | 0 | 12 |
| 2021 | 4 (Sep to Dec) | 8 (Jan to Aug) |
| 2022 | 12 | 0 |
| 2023 | 12 | 0 |
| 2024 | 12 | 0 |
| 2025 | 12 | 0 |
| 2026 | 10 (Jan to Oct) | 0 |

The first version of the ETL found gaps in 2024 and 2025 (May to Jul 2024, Jun and Jul 2025). They are not real gaps: the reports for May to Jul 2024 exist in `onda_excel/`, and June and July 2025 are in the 2026 reports, which repeat the 2025 figures as the previous-year column. The same idea gives 2019, 2022 and Sep to Dec 2021 in full.

Check against annual totals (passengers, observed months only):

| Year | Sum of our monthly values | Annual total in the ONDA report |
|---|---|---|
| 2019 | 25,075,677 | 25,074,913 |
| 2022 | 20,599,033 | 20,599,173 |
| 2023 | 26,956,340 | 27,091,248 (-0.5%) |
| 2024 | 32,652,602 | 32,710,023 (-0.2%) |
| 2025 | 36,353,756 | 36,359,003 |

ONDA's TOTAL row and the sum of the airport rows differ by at most 0.02% in every month, so nothing is counted twice.

## 6. What is still missing or weak

1. **2020 and January to August 2021 have no monthly data.** No monthly ONDA report was found for these months. They are estimated and flagged `is_estimated = 1` (336 rows in total):
   - 2021: the cumulative figure at September 2021 (printed in the September 2022 report) minus the observed months, spread with the 2019 monthly shape of each airport. The total is exact, the split between months is an assumption.
   - 2020: the HCP annual total of each airport spread with the 2019 monthly shape. Here even the shape is an assumption, so these rows do not show the real crisis curve.
   - Only passengers and movements are estimated for 2020. Cargo and the national / international split are left empty.
   - Consequence: the abnormal months of 2020 (B6) must not be detected on estimated rows. The 2020 crisis can only be shown at yearly level, with `fact_trafic_annuel` (HCP: 25.0 million passengers in 2019, 7.1 million in 2020).
2. **National / international split and origin zone** are missing for 2020, 2021, January and February 2022, and September 2022 (67 of 94 months are covered). February 2022 is only available as a partial period (7 to 28 Feb), which cannot be used as a month.
3. **Cargo is empty for many rows** (555 of 1,468 observed rows). It is full for the large airports and almost always empty for the small ones (Errachidia, Guelmim, Tan-Tan, Zagora, Benslimane...). It probably means "no cargo", but the files do not say it, so we keep it empty and never replace it with 0. See open decisions.
4. **Real zeros.** 22 rows have zero passengers (small airports with long inactive periods) and 87 rows have zero cargo. They are kept as zeros because the report writes a 0.
5. **Small differences between reports.** ONDA corrects its figures in the following year's report. 199 values differ by more than 0.5% between two reports (`qc_conflicts.csv`). Most of them are Mohammed V in 2023, where the first report is 4 to 19% lower than the corrected one. We use the corrected value (see the source policy in the script documentation).
6. **Cumulative check.** 41 of 1,415 cumulative checks still differ by more than 0.5%. They are mostly small airports, where a few passengers are a large percentage.
7. **Rows where national + international differs from the total:** 38 of 1,072 (`flag_split_mismatch`), 10 of them for Benslimane, which has almost no traffic.
8. **Special rows.** `OTH` is the line "Autres" (other airports) that ONDA reports as one aggregate. It is kept in the facts so the totals match, flagged `is_aggregate = 1` in the dimension, and excluded from clustering. `BSM` (Benslimane) has no IATA code, so it has an internal code.
9. **Not used.** The PDFs (their numbers are already in the Excel files and in the HCP files), the old 2022 files that only cover partial periods, and the top 5 routes (not needed for the tasks).
10. **Airports excluded from clustering** (fewer than 24 recent months or fewer than 1,000 passengers per month): Bouarfa, Es-Smara, Benslimane, and the aggregate `OTH`. They stay in the dimension and in the facts.

## 7. Decisions the team still has to take

1. Cargo: if an empty cargo cell means "no cargo", we can treat it as 0 only inside the clustering features and keep it empty in the warehouse.
2. Estimated months: keep them in the cube with the flag (as an attribute of the time dimension or of the fact), or filter them out for the OLAP analysis. For forecasting (A5) we suggest training from 2022 on, or marking 2020 and 2021 as outliers in Prophet.
3. Thresholds for clustering (24 months, 1,000 passengers): they can be changed at the top of the script.
