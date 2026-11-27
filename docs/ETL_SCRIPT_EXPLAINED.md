# `build_clean_data.py` 

This document describes everything the script does, step by step, and why. It is the answer to tasks B1 (collect), B2 (clean and harmonise) and the first part of B3 (quality checks).

## 1. Why we needed a script

The raw data is not usable directly:

- The Excel reports come in at least five different layouts (2022 autumn, 2023, 2024, 2025, 2026). Column order, number of years per block, and the presence of cumulative columns all change.
- The same month appears in several reports. For example, March 2023 appears in the March 2023 report, and again as the previous-year column of the March 2024 report.
- Airport names are not written the same way (`MOHAMMED V`, `MED V`, `ALHOCEIMA`, `AL HOCEIMA`, `GUELMIM`, `GUELMIME`...).
- A first ETL replaced missing values with 0, so a real zero and a missing value looked the same. Gaps in the monthly series (2020, most of 2021, some months of 2024 and 2025) also made ARIMA and the seasonal OLAP analysis unreliable.
- Some files only cover a partial period (for example 7 to 28 February 2022, since borders reopened on 7 February), and mixing them with full months gave wrong numbers.

Doing this by hand for about 90 files would not be reproducible, so one script does it and writes everything in `clean/`.

## 2. How to run it

```
pip install -r requirements.txt
python build_clean_data.py
```

By default the project folder is the folder that contains the script. A different folder can be given as an argument: `python build_clean_data.py "D:\other\folder"`.

It reads `morocco_airports.csv`, `onda_excel/` (all sub-folders) and `hcp_raw/`, and writes only into `clean/`. The raw files are never modified. Running it again overwrites `clean/`. It takes a few minutes at most.

## 3. Overview of the pipeline

The numbers match the comments in the code.

| Step | What happens |
|---|---|
| 0 | Read the airport reference `morocco_airports.csv` |
| 1 | Scan all ONDA Excel files and extract three kinds of tables |
| 2 | For each (year, month, metric), choose one source report |
| 3 | Keep the cumulative figures |
| 4 | Estimate what is really missing |
| 5 | Quality-control tables |
| 6 | Dimensions |
| 7 | Fact tables |
| 8 | Files prepared for data mining |
| 9 | Report |

## 4. Step 1: reading the ONDA reports

Each Excel file is opened with all its sheets, and each sheet is classified by its name or by the text at the top:

| Kind | Where it comes from | What we extract |
|---|---|---|
| `trafic` | Sheet "Trafic aérien par aéroport" (2022 autumn to 2026 reports) | Passengers, movements, cargo per airport, for the month and for the cumulative, for 2 or 3 years |
| `natinter` | Sheet "Ventilation nat-inter", and the older 2022 files | International, national and total passengers per airport |
| `region` | Sheet "Ventilation par région", and the older 2022 files | International passengers per geographic zone (and per airport when the sheet gives it) |

Other sheets (top 5 routes, cargo-only files of 2022) are ignored. Files that only contain partial periods are skipped, and this is written in the report.

### 4.1 The traffic sheet (`parse_trafic`)

- **Month and years** are read from the title of the sheet, for example "Août et Cumul à fin Août 2023/2022/2019". The month name and the list of years tell us what each column means, so the same code works for all layouts.
- **Header row.** We look for the row that contains `PASSAGERS`, `MOUVEMENTS` and `FRET`. In some reports (December 2025) the first cell of that row is empty, so the row is also found by its block names.
- **Blocks.** Each block (passengers, movements, cargo) has one column per year, then a variation column, then, when the sub-header contains `CUMUL`, the same again for the cumulative. This layout is detected, not hard-coded. In the September 2022 report the blocks are in a different order (movements first), which is handled by reading the block names.
- **Column order check.** The title says the first year is the most recent, but this is checked with the variation column: with two years the variation must be `Y0 / Y1 - 1`, with three years the recovery rate must be `Y0 / Y2`. If the data matches the opposite order, the years are reversed and a note is printed. The check runs on all rows of the sheet.
- The row `TOTAL` is kept separately and used for control and for the network series.

### 4.2 The national / international sheet (`parse_natinter`)

The header holds a date (2019-03-01) in modern reports, or a text ("Mars 2022") in the old 2022 files. Each period uses three columns: international, national, total. Columns of cumulative and variation are skipped. A period written with "au" (for example "07 au 28 Fév 2022") is a partial period and is skipped.

### 4.3 The zone sheet (`parse_region_modern`, `parse_region_legacy`)

The sheet has a "Passagers" header and a row of years under it. The rows below mix zone rows and airport rows, so they are read with a small state machine (`walk_zone_rows`):

- a zone row with values is a network-level total for that zone;
- an airport row under a zone is the traffic of that airport for that zone;
- a zone row under an airport header is read the same way, the other way round;
- the label "Autres" in these sheets is the zone "Other", not an airport;
- rows that match nothing are written to the unmapped report.

### 4.4 HCP files (`scan_hcp`)

The HCP files give yearly values: movements per airport, and passengers split in arrivals, departures and transit (the airport name is only written on the first row of each group, so it is carried down). They are used for the 2020 estimates and for the yearly control table.

## 5. Airport name harmonisation

The table `AIRPORTS` at the top of the script has one line per airport: IATA code, clean name, a list of ways the name appears in the files, city, ISO region.

- A label is first normalised (accents removed, upper case, punctuation removed), then compared with the patterns as whole words.
- If nothing matches, a second comparison is done without spaces, so `ALHOCEIMA`, `BENIMELLAL` or `GUELMIME` are found. This was added after the first run, when 26 rows of Al Hoceima and 41 rows of Guelmim were lost because of their spelling.
- A label that still does not match goes to `qc_unmapped_labels.csv`, and the fix is to add one pattern to the table.
- City, ISO region, type and coordinates are taken from `morocco_airports.csv` through the IATA code. When the file has no value, the table in the script is used. If both disagree on the region, the CSV wins and a note is printed. The region name comes from the ISO code (`MA-09` is Souss-Massa).
- Two special codes: `OTH` is the line "Autres" that ONDA reports as an aggregate of other airports (kept so the totals match, but flagged and left out of clustering); `BSM` is Benslimane, which has no IATA code, so the code is internal.

## 6. Step 2: choosing one source for each month

The same (year, month) can come from several reports. Taking any of them, or mixing them, gives inconsistent series. The script chooses exactly one report for each (year, month, metric) with `pick_primary`.

- **Policy `latest_revision` (default).** The report of the next year repeats the previous year's figures, and ONDA corrects them. For example Mohammed V in March 2023 is 643,184 in the March 2023 report, and 736,770 in the March 2024 report. The cumulative printed in the December 2023 report for this airport (9.79 million) matches the corrected values, not the first ones. So the report with the smallest positive gap (`report year - data year`) is preferred, and the report of the same year is used when nothing else exists (2026, and the months of 2023 to 2025 that have no later report).
- **Policy `own_year`.** The old behaviour, the report of the same year first. It can be selected with `SOURCE_POLICY`.
- A file named "Copie de ..." loses a tie against the original.
- The choice is made for each metric. If the chosen report has no cargo block (the October and November 2022 reports), cargo comes from the next candidate. The source of each value is stored in the `src_*` columns.
- Every value from another report that differs by more than 0.5% from the chosen one is written to `qc_conflicts.csv`.
- If two rows of the same report map to the same airport, only the first is kept, and the duplicates are listed in `qc_duplicate_labels.csv`.

For the zone table the choice is made per zone and per scope (network or airport), so a report that lists only two zones does not hide the others.

## 7. Step 3 and 4: building the monthly table

- The chosen values are put in one row per airport and month. The national / international table is joined on the same key.
- If the traffic table has no total for a row but the split table has one, the total is taken from the split and the row gets `flag_pax_from_split = 1`.
- `flag_split_mismatch` marks rows where national + international differs from the total by more than 0.5%. `flag_zero_passengers` marks rows where the source says 0.
- **A missing value stays empty.** It is never replaced by 0. A 0 in the table means the report wrote 0.

### Estimates

Months with no data in any report are rebuilt, only when `ESTIMATE_MISSING = True`, and never over an observed value. Every estimated row has `is_estimated = 1` and an `estimation_method`.

- **2021, January to August.** The September 2022 report prints the cumulative of 2021 up to September for each airport. For an airport: `cumulative(Sep 2021) - sum of observed months up to Sep 2021` is the exact total of the missing months. It is split between the months with the shape of 2019 for the same airport (or the network shape if the airport has no 2019 data). Passengers, movements and cargo are done in the same way when the cumulative exists.
- **2020.** For each airport, the HCP annual total of 2020 (passengers and movements) is split with the shape of 2019.

The sum of the estimated months is correct, but the split between months follows 2019. In 2020 this hides the real crisis curve. This is why the estimated rows must not be used for anomaly detection.

## 8. Step 5: quality control

- **Conflicts** between reports (see section 6).
- **Cumulative check** (`qc_cumul_check.csv`). For every report, the cumulative printed up to month m is compared with the sum of our months 1 to m. It catches missing months and wrong sources. Checks with missing months are counted as skipped.
- **TOTAL against the sum of airports** (`qc_total_vs_sum.csv`), per month. It shows that no airport or aggregate is counted twice.
- **Monthly sum against yearly total** (report section 7).
- **Zero and empty values** counted separately (report section 3).

## 9. Steps 6 to 8: output files

- **Dimensions.** `dim_temps` has one row per month with the quarter, the season (winter December to February, spring March to May, summer June to August, autumn September to November) and a COVID phase (before March 2020, COVID until January 2022, recovery 2022, after). The COVID phase is only an analysis helper. `dim_zone_origine` includes `DOM` for national traffic. `dim_aeroport` also has `include_in_clustering`: at least 24 observed months since 2023 and an average of 1,000 passengers per month, and not the aggregate.
- **Facts.** `fact_trafic_mensuel`, `fact_trafic_par_type` (one row per airport, month and type, only where the split exists), `fact_passagers_zone`, and `fact_trafic_annuel`.
- **Mining files.**
  - `ts_reseau_mensuel`: the network passengers of each month. The `TOTAL` row of ONDA is used when it exists, and the sum of the airports for estimated months.
  - `panel_aeroport_mois_complet`: every airport for every month, with the status OBSERVED, ESTIMATED or MISSING.
  - `features_aeroports_kmeans`: computed on observed rows from 2023 on. Average monthly passengers, movements and cargo; share of international passengers; seasonality (average of July and August divided by the yearly monthly average); passengers per movement; recovery 2025 against 2019 (months present in both years); growth 2025 against 2024.

## 10. Settings at the top of the script

| Name | Default | Meaning |
|---|---|---|
| `TOL` | 0.005 | Tolerance for conflicts and checks |
| `MIN_MONTHS_CLUSTER` | 24 | Minimum observed months to be clustered |
| `MIN_AVG_PAX_CLUSTER` | 1000 | Minimum average passengers per month to be clustered |
| `FEATURE_START_YEAR` | 2023 | First year used for the clustering features |
| `SOURCE_POLICY` | `latest_revision` | Report choice, see section 6 |
| `ESTIMATE_MISSING` | `True` | Set `False` to keep gaps empty |
| `FIRST_YEAR` | 2019 | First year of the warehouse |
| `ENC` | `utf-8-sig` | Encoding of the CSV files (UTF-8 with BOM, opens well in Excel) |

## 11. How each problem of the project notes was handled

| Problem | What the script does |
|---|---|
| Monthly gaps (28 of 89 months) | Months are searched in all reports and in all year columns. This fills May to Jul 2024 (own reports), Jun and Jul 2025 (2026 reports), 2019, 2022 and Sep to Dec 2021. Only 2020 and Jan to Aug 2021 are estimated and flagged. |
| Gaps in summer months biasing seasonality | The summer months of 2024 and 2025 are found (see above), so the series has no summer hole. |
| 2020 crisis not visible monthly | Not solved with data. Estimated and flagged. The crisis is shown at yearly level with HCP. |
| Fact table not at the grain of the brief | Three fact tables with shared dimensions, and a `DOM` zone for national traffic. |
| Missing values replaced by 0 | A missing value stays empty. Zeros are counted separately. |
| Small airports with long inactive periods | They are kept in the facts, and excluded from clustering by two thresholds. |
| National / international table not matching the traffic table | One source per month, partial periods never used as months, and every remaining difference flagged. |
| Yearly total 3% above the monthly sum in 2023 | The first reports of 2023 were lower than the corrected figures. With the corrected values the gap is 0.5%. |

## 12. Limits

- Names that the table does not know are only reported, not guessed.
- The layouts were read from the files of 2019 to 2026. A new layout in a future report may need a small change in the parser. The report lists every file that was skipped and why.
- The estimates are a documented fallback, not data.
- Cargo emptiness is not interpreted. See `DATA_MAP.md`.
