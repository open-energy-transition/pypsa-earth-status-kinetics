<!--
SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->

# Prefecture generation validation (Japan)

PyPSA-Earth-Status compares the annual electricity generation of a solved PyPSA network of Japan with the **METI Electric Power Survey Statistics**, per **prefecture** and per **source**. The workflow supports electricity-only and sector-coupled networks and any number of network nodes.

## Run the workflow

The validation runs only for Japan. It is enabled by default and included in `validate_all` whenever `"JP"` is in `network_validation.countries`; for networks without Japan it is skipped entirely:

```yaml
network_validation:
  network_path: "path/to/network.nc"
  year: [2023]
  countries: ['JP']

prefecture_generation_validation:
  enable: true  # set to false to skip it for Japan networks
  meti_generation: "data/japan/electricity_generation/METI_Generation_2023.xlsx"
  prefecture_shapes: "data/japan/administrative_boundaries/japan_prefectures_2023.geojson"
  settings: "config/japan_prefecture_generation.yaml"
```

It runs as part of the complete validation workflow:

```bash
snakemake -j 1 validate_all
```

or on its own:

```bash
snakemake -j 1 validate_prefecture_generation
```

The latest available METI annual sheet (`<year>_Annual`) is selected automatically, independently of `network_validation.year`. Both years are reported in the comparison tables and figure titles. Future planning horizons are compared against the latest available historical reference. The carrier mapping, the compared categories and the regions are maintained in `config/japan_prefecture_generation.yaml`.

## Reference data

The reference is the METI Electric Power Survey Statistics ([results archive](https://www.enecho.meti.go.jp/statistics/electric_power/ep002/results_archive.html)), monthly generation per prefecture and source.

METI publishes the statistics per **fiscal year** (April to March). To match the calendar year of the network snapshots, the workbook `data/japan/electricity_generation/METI_Generation_2023.xlsx` is compiled from two fiscal-year files:

- FY2022 file: January to March 2023
- FY2023 file: April to December 2023

It has one sheet per month (`2023.1` to `2023.12`, unit 1,000 kWh) and their sum in the sheet `2023_Annual`, which the workflow reads. For another year, build the workbook the same way and name the annual sheet `<year>_Annual`.

Source: 「電力調査統計」（資源エネルギー庁）(https://www.enecho.meti.go.jp/statistics/electric_power/ep002/results_archive.html)、PDL1.0 (https://www.digital.go.jp/resources/open_data/public_data_license_v1.0). Processed: monthly values of two fiscal-year files combined into a calendar year, biomass and waste separated from thermal, units converted to GWh. The content of the ANRE website is published under the Public Data License (Version 1.0), which is compatible with CC BY 4.0.

The prefecture boundaries `data/japan/administrative_boundaries/japan_prefectures_2023.geojson` are built from the MLIT National Land Numerical Information, Administrative Areas (N03), 2023 edition (boundaries as of 1 January 2023, [download page](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2023.html), nationwide file `N03-20230101_GML.zip`). The municipalities are merged by prefecture code and simplified with `scripts/build_japan_prefecture_shapes.py`:

```bash
python scripts/build_japan_prefecture_shapes.py --input N03-23_230101.shp --output data/japan/administrative_boundaries/japan_prefectures_2023.geojson
```

Source: 「国土数値情報（行政区域データ）」（国土交通省）(https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2023.html)（2026年11月19日取得）を加工して作成. Processed: municipalities merged to prefectures, English names added, boundaries simplified. The data is published under the [MLIT National Land Numerical Information terms of use](https://nlftp.mlit.go.jp/ksj/other/agreement_01.html), based on the Government of Japan Standard Terms of Use (Version 2.0) and compatible with CC BY 4.0.

## Method

1. **Bus to prefecture.** Every grid bus (`AC`/`DC`) is assigned to one prefecture by a spatial join with the prefecture boundaries. Buses slightly outside every prefecture (for example on the coast) are assigned to the nearest prefecture. Other buses (H2, battery, low voltage, ...) inherit the prefecture of their `location`.
2. **Model generation.** Annual generation is the dispatch summed over all snapshots, weighted with the snapshot weightings, so hourly and multi-hour networks are handled the same way.
    - Generators and storage units are counted only on electricity buses (`AC`, `DC`, `low voltage`). In sector-coupled networks, generators on fuel buses are fuel supply and solar thermal sits on heat buses; neither is electricity generation.
    - Storage units count discharge only (METI hydro includes pumped storage, so `PHS` is counted as hydro).
    - Power plants represented as Links in sector-coupled networks (fuel bus → electricity bus) are counted with their electricity output `-p1`, using `get_electricity_production_links` from `scripts/build_network_statistics.py`.
    - Carrier names are harmonized with `harmonize_electricity_carrier_names()` from `scripts/build_network_statistics.py`, as in the national electricity validation, so that e.g. rooftop PV, gas CHP and biomass CHP are included. `load shedding` and `H2 fuel cell` are not counted as generation.
3. **Reference.** METI "thermal" already includes biomass and waste. Both are subtracted from thermal, so thermal is **fossil thermal only**, and biomass and waste are compared as their own categories.
4. **Comparison.** Model and METI values are compared per prefecture and per region (8 standard regions of Japan).

Compared categories:

| PyPSA carriers (harmonized name) | Category |
| --- | --- |
| CCGT, OCGT, coal, lignite, oil, gas/coal/oil CHP (`gas`, `coal`, `oil`) | thermal |
| nuclear (`nuclear`) | nuclear |
| hydro, ror, PHS (`hydro`) | hydro |
| onwind, offwind-ac, offwind-dc, offwind-float (`onwind`, `offwind`, `offwind-float`) | wind |
| solar, rooftop PV, csp, solar-hsat (`pv`, `solar-hsat`) | solar |
| geothermal (`geothermal`) | geothermal |
| biomass EOP, solid biomass CHP (`biomass`) | biomass |
| waste CHP (`waste`) | waste |

## Output files

Files are written under `results/<validation_name>/`.

| Output | Description |
| --- | --- |
| `tables/prefecture_generation_reference.csv` | METI generation per prefecture and category (GWh). |
| `tables/prefecture_generation_model.csv` | Model generation per prefecture and category (GWh). |
| `tables/prefecture_generation_bus_map.csv` | Grid bus to prefecture assignment, with the distance to the prefecture for snapped buses. |
| `tables/prefecture_generation_comparison.csv` | Model versus METI per prefecture and category, with absolute and relative differences, shares of the national total and whether the prefecture has a bus. |
| `tables/region_generation_comparison.csv` | Model versus METI per region and category, with absolute and relative differences and shares of the national total. |
| `tables/prefecture_generation_validation_summary.csv` | National totals per category, and normalized absolute error and spatial distribution error per prefecture and per region. |
| `figures/prefecture_generation_national.png` | National totals per category. |
| `figures/prefecture_generation_by_carrier.png` | Model versus METI per prefecture, one panel per category. |
| `figures/prefecture_generation_total.png` | Model versus METI per prefecture, all categories together. |
| `figures/region_generation_by_carrier.png` | Model versus METI per region, one panel per category. |

## Interpreting the results

The network nodes do not follow prefecture borders. All generation of a node is counted in the prefecture where its bus is located, so generation can appear in a neighbouring prefecture, and prefectures without a bus show zero model generation (shaded grey in the prefecture figure).

The summary reports two indicators per category, per prefecture and per region:

- **Normalized absolute error**: the sum of the absolute differences divided by the METI total. It combines the error in the total generation with the error in its geographical distribution.
- **Spatial distribution error**: half the sum of the absolute differences between the model and METI shares of the national total (0% = same distribution, 100% = no overlap). It does not depend on the total generation, so it measures only where the generation is located.

If the spatial distribution error drops strongly from prefecture to region level, most of the prefecture differences come from the location of the network nodes (clustering) rather than from the model. A network with more nodes gives a more accurate prefecture comparison.

## Scope and limitations

- Japan only, annual values, one reference year per run.
- METI values cover the categories reported by METI. The small "others" column is not compared.
- Waste plants are not yet represented in the solved networks, so the model shows zero waste generation.
- Generation of a node that covers several prefectures is not split between them.
