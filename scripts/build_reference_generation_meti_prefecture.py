# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Build the METI reference of annual electricity generation per prefecture
and source for Japan.

Reads the METI Electric Power Survey Statistics workbook (sheet
``<year>_Annual``), maps the METI columns to the validation categories and
writes one row per prefecture and category in GWh.

METI "thermal power plant" already includes biomass and waste. Both are
subtracted from thermal, so thermal is fossil only, and biomass and waste
are kept as their own categories.

Source: 「電力調査統計」（資源エネルギー庁）
https://www.enecho.meti.go.jp/statistics/electric_power/ep002/results_archive.html
License: Public Data License (Version 1.0), PDL1.0, compatible with CC BY 4.0:
https://www.digital.go.jp/resources/open_data/public_data_license_v1.0
"""

import argparse
import logging
import re
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

REFERENCE_COLUMNS = ["prefecture", "carrier", "reference_GWh", "reference_year"]


def build_reference_meti(workbook, settings, year=None):
    """
    Return METI annual generation per prefecture and category in GWh.

    Parameters
    ----------
    workbook : str or Path
        METI Excel file with a sheet ``<year>_Annual``. Unit: 1,000 kWh (= MWh).
    settings : dict
        Content of ``config/japan_prefecture_generation.yaml``.
    year : int or None
        Reference year. If None, use the latest available annual sheet.

    Returns
    -------
    pandas.DataFrame
        Columns ``prefecture``, ``carrier``, ``reference_GWh``, ``reference_year``.
    """
    with pd.ExcelFile(workbook) as excel:
        available_years = [
            int(match.group(1))
            for sheet_name in excel.sheet_names
            if (match := re.fullmatch(r"(\d{4})_Annual", sheet_name))
        ]

        if not available_years:
            raise ValueError(f"No annual METI reference sheets found in {workbook}")

        if year is None:
            year = max(available_years)

        if year not in available_years:
            raise ValueError(
                f"METI reference year {year} is unavailable. "
                f"Available years: {sorted(available_years)}"
            )

        sheet = f"{year}_Annual"
        meti = pd.read_excel(excel, sheet_name=sheet)

    logger.info("Selected METI reference year: %d", year)

    meti = meti.rename(columns={meti.columns[0]: "prefecture"})
    meti["prefecture"] = meti["prefecture"].astype(str).str.strip()

    # drop the national "total" row
    meti = meti[meti["prefecture"].str.lower() != "total"]

    meti_columns = settings["meti_columns"]
    missing = set(meti_columns) - set(meti.columns)
    if missing:
        raise ValueError(f"Columns missing in METI sheet '{sheet}': {sorted(missing)}")

    meti = meti.set_index("prefecture")[list(meti_columns)].rename(columns=meti_columns)
    meti = meti.astype(float) / 1e3  # MWh -> GWh

    # METI thermal includes biomass and waste -> keep fossil thermal only
    meti["thermal"] = meti["thermal"] - meti["biomass"] - meti["waste"]

    if (meti["thermal"] < -1e-6).any():
        negative = meti.index[meti["thermal"] < -1e-6].tolist()
        logger.warning(
            f"Negative fossil thermal after subtracting biomass/waste: {negative}"
        )

    categories = settings["categories"]
    reference = (
        meti.reindex(columns=categories, fill_value=0.0)
        .stack()
        .rename("reference_GWh")
        .rename_axis(["prefecture", "carrier"])
        .reset_index()
    )

    reference["reference_year"] = year
    return reference[REFERENCE_COLUMNS]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="METI Excel workbook")
    parser.add_argument(
        "--config", required=True, help="config/japan_prefecture_generation.yaml"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Reference year (default: latest available)",
    )
    parser.add_argument("--output", required=True, help="Output CSV")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with open(args.config) as handle:
        settings = yaml.safe_load(handle)

    reference = build_reference_meti(args.input, settings, args.year)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    reference.to_csv(output, index=False)

    logger.info(
        "METI %s reference: %d prefectures, %d rows",
        reference["reference_year"].iloc[0],
        reference["prefecture"].nunique(),
        len(reference),
    )
    logger.info(
        "METI totals per category [TWh]:\n%s",
        (reference.groupby("carrier")["reference_GWh"].sum() / 1e3)
        .reindex(settings["categories"])
        .round(1)
        .to_string(),
    )


if __name__ == "__main__":
    main()
