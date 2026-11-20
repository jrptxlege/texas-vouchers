# TEFA data explorer

A Python (Streamlit + Plotly) foundation for visualizing the Texas Education Freedom
Accounts public data kept in the `TEFA Public Data` folder.

## Run it

Put this `tefa_viz` folder inside `TEFA Public Data` (the folder it reads by default), then:

```
pip install -r requirements.txt
streamlit run Home.py
```

On Windows you can also double-click `run_app.bat`. To read a different folder, set
`TEFA_DATA_DIR` or change the **Data folder** box in the sidebar.

The legislative map reads Texas Legislative Council plan downloads from
`EO Team/EO Data/Texas Shapefiles` (found automatically from the TEFA folder's location;
override with `TEFA_SHAPE_DIR` or the **Shapefile folder** box).

## Layout

```
Home.py                 headline numbers + application funnel (Nov dashboard)
pages/
  1_Participants.py     any breakdown (tier, income, grade, age, gender, race, ...), eligible vs funded,
                        funded ÷ eligible, and cross-release comparisons
  2_Districts.py        district counts and per-1,000-enrolled rates, ESC-region rollup
  3_Spending.py         school funding vs marketplace; schools, categories, vendors
  4_Vendors.py          participating-vendor directory (type, city, registrations over time)
  5_Special_Education_Funding.py   add-on by IEP code; district comparison
  6_Data_and_QA.py      dataset inventory, files with no loader, cross-file checks
  7_Legislative_Map.py  House/Senate choropleth with toggleable data layers, metro focus,
                        ranked districts, and the school districts inside each legislative district
tefa/
  config.py     data folder, release labels
  readers.py    format-tolerant readers (UTF-16 Tableau CSVs, "$1,234" strings, 1x1 KPI sheets, crosstabs)
  datasets.py   one loader per published table + the DATASETS registry
  districts.py  district-name matching across releases, joined to enrollment
  checks.py     cross-file reconciliation
  geo.py        finds the newest PLANH/PLANS shapefiles + Red-160 ISD reports; boundaries → cached
                GeoJSON; ISD → legislative-district crosswalk and allocate()
  layers.py     the map's data layers (LAYERS registry) and an optional member-names hook
  charts.py     shared chart builders and the color palette
  ui.py         sidebar, caching, source captions, "Show data" + CSV download under each chart
tests/test_tefa.py
```

## Conventions

* Breakdown tables share one tidy schema: `release | dimension | category | metric | value`
  (`metric` ∈ eligible, funded, share_funded, count). Any loader that emits it and is tagged
  `"breakdown"` appears automatically on the Participants page.
* Values are used as published. Suppressed cells (`*`, `<30`, blank) stay missing; nothing is imputed.
* Loss columns in `TEFA_Data-Copy.xlsx` use the superseded flat $8,198.69 rate and are not loaded.

## Adding a new release

1. Drop the files in the data folder (e.g. a new `Dec.26-Dashboard` subfolder).
2. Check **Data & QA → files not read by any loader**.
3. Add a release label in `config.py`, write loaders in `datasets.py` that emit the tidy
   schema, register them in `DATASETS`, and run `pytest -q`.

## Legislative map

* **Boundaries:** `PLANH2316.zip` (150 House districts) and `PLANS2168.zip` (31 Senate districts),
  simplified to ~150 m and cached in `.cache/`. Dropping in a newer TLC plan download is picked up
  automatically (newest plan zip per chamber; a `PLANC####.zip` adds a Congressional option).
* **Crosswalk:** `PLAN?####_r160_ISDsSY25-26.xls` lists every school district piece in each
  legislative district with 2020 Census total and under-18 population.
* **How ISD data reaches legislative districts:** TEFA data is published by school district, so
  each ISD's value is split across legislative districts by the share of the ISD's under-18
  population in each piece. That is an estimate — it assumes participants are spread like children
  are, so every House district inside Houston ISD gets the same per-child rate. Address-level or
  campus-level data would replace this. Charters have no boundaries and are not placed.
* **Exact layers (House and Senate):** the Nov dashboard publishes funded participants, waitlisted
  students, and award dollars for each House and Senate district
  (`Funded Participants by House/Senate Districts.xlsx`). These layers use those numbers directly — no
  apportionment — and are the default. 506 funded participants are published with no district and are
  shown as "published with no district". The same files supply member names for hovers.
* **Estimated layers:** July and Oct 1 funded participants, Oct prior-public participants, Nov top-30 ISDs, public
  enrollment, under-18 population, SPED code-41 add-on (weighted average). Each shows a total or a
  per-1,000-children rate, how much of the source total was placed, and names that didn't match.
* **Add a layer:** write `fn(base, plan) -> (DataFrame[district, value], diagnostics)` in
  `tefa/layers.py` (usually one call to `geo.allocate`) and append a `Layer` to `LAYERS`.
  Use `how="mean"` for amounts/rates instead of counts.
* **Member names:** taken from the Nov dashboard House/Senate tables. To override (or for the
  Congressional map), put a CSV named like `*legislators*.csv` (columns: chamber, district, and a
  name/member column) in the shapefile or data folder.
* **Basemap:** off by default — districts are drawn as plain shapes, which works offline and in
  exported images. The toggle switches to a street basemap (needs internet + WebGL).

## Known data issues (found by the checks)

* The Top-20 vendor export reports different amounts than `All Vendors (2).csv` for its
  first 10 vendors (e.g. Miaplaza $1.74M vs $1.17M; Amazon $12.67M vs $12.27M). The full
  vendor list sums to $47.7M against $51.3M marketplace spend.
* `All Schools.csv` sums to $294.7M against $297.2M school funding, and lists 2,059 schools vs the 2,058 tile.
* Funded + waiting list + opted out is 295 short of eligible applicants.
* The "Top 20" exports contain only 15 rows.
* July/Oct district lists attribute 200+ participants per 1,000 enrolled students to a few small
  districts (e.g. Northside ISD – Vernon), which suggests address attribution problems.
* The Nov race/ethnicity file has no header row and gives percents (0–100) of funded participants;
  it is loaded as shares, like gender. No counts are published for it.
* House/Senate district tables total 111,324 funded participants vs the 111,327 tile (within tolerance).
  `House/Senate Districts Details.xlsx` repeat the same numbers without the no-district row.
* `Oct1_TEFA-Funded-Participants - Data  Request.xlsx` has headers for race, sex, prior school, tier and
  disability by district, but those columns are empty; only funded counts are published, for 378 districts
  with 30+ participants (112,088). Another 4,486 are in smaller ISDs (116,574 reported). Loaded as
  `oct1_district` (Districts page, and a map layer).
* `Expenditure or Transactions  by Category.xlsx` has no loader yet (it repeats `Vendors/Category.xlsx`).
