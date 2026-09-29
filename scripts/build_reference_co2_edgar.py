# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Build reference fossil CO2 emissions by sector from the EDGAR GHG booklet.

Reads the ``fossil_CO2_by_sector_country_su`` sheet (values in MtCO2/yr) of
the EDGAR booklet spreadsheet, selects the requested countries and year, maps
EDGAR sectors to model sectors and writes a table with columns ``sector`` and
``reference`` [MtCO2], summed over the countries.

Data: EDGAR (Emissions Database for Global Atmospheric Research), European
Commission Joint Research Centre, https://edgar.jrc.ec.europa.eu, CC BY 4.0.
"""

import logging
import os
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

import country_converter as coco
import pandas as pd
from helpers import configure_logging, create_country_list

logger = logging.getLogger(__name__)


XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
XLSX_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def read_xlsx_sheet(path, sheet_name):
    """
    Read one worksheet of an .xlsx file into a DataFrame, using the first row
    as header.

    Parses the workbook XML with the standard library so no Excel engine
    (e.g. openpyxl) is needed. Cells are returned as strings; formulas are
    read as their cached values.
    """
    with zipfile.ZipFile(path) as xlsx:
        workbook = ET.fromstring(xlsx.read("xl/workbook.xml"))
        sheets = {
            sheet.get("name"): sheet.get(XLSX_REL_ID)
            for sheet in workbook.iterfind("main:sheets/main:sheet", XLSX_NS)
        }
        if sheet_name not in sheets:
            raise ValueError(
                f"Sheet '{sheet_name}' not found in {path}; available: {list(sheets)}"
            )

        rels = ET.fromstring(xlsx.read("xl/_rels/workbook.xml.rels"))
        targets = {
            rel.get("Id"): rel.get("Target")
            for rel in rels.iterfind("rel:Relationship", XLSX_NS)
        }
        target = targets[sheets[sheet_name]]
        sheet_path = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )

        shared_strings = []
        if "xl/sharedStrings.xml" in xlsx.namelist():
            strings = ET.fromstring(xlsx.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(t.text or "" for t in si.iter(f"{{{XLSX_NS['main']}}}t"))
                for si in strings.iterfind("main:si", XLSX_NS)
            ]

        sheet = ET.fromstring(xlsx.read(sheet_path))

    rows = []
    for row in sheet.iterfind("main:sheetData/main:row", XLSX_NS):
        values = {}
        for cell in row.iterfind("main:c", XLSX_NS):
            column = re.match(r"[A-Z]+", cell.get("r")).group()
            cell_type = cell.get("t")
            if cell_type == "inlineStr":
                value = "".join(
                    t.text or "" for t in cell.iter(f"{{{XLSX_NS['main']}}}t")
                )
            else:
                v = cell.find("main:v", XLSX_NS)
                if v is None:
                    continue
                value = shared_strings[int(v.text)] if cell_type == "s" else v.text
            values[column] = value
        rows.append(values)

    if not rows:
        return pd.DataFrame()

    def column_index(letters):
        index = 0
        for letter in letters:
            index = index * 26 + ord(letter) - ord("A") + 1
        return index

    columns = sorted({c for row in rows for c in row}, key=column_index)
    table = pd.DataFrame(
        [[row.get(c) for c in columns] for row in rows], columns=columns
    )
    table.columns = table.iloc[0]
    return table.iloc[1:].reset_index(drop=True)


def read_edgar_by_sector(path, sheet_name):
    df = read_xlsx_sheet(path, sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Substance"] == "CO2"]
    year_columns = [c for c in df.columns if c.isdigit()]
    long = df.melt(
        id_vars=["Sector", "EDGAR Country Code"],
        value_vars=year_columns,
        var_name="year",
        value_name="value",
    )
    long["year"] = long["year"].astype(int)
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    return long


def build_reference(edgar, countries, year, sector_map):
    iso3 = coco.convert(countries, to="ISO3", not_found=None)
    iso3 = [iso3] if isinstance(iso3, str) else list(iso3)

    available = set(edgar["EDGAR Country Code"])
    missing = sorted(set(iso3) - available)
    if missing:
        logger.warning(f"Countries not found in EDGAR: {missing}")

    years = sorted(edgar["year"].unique())
    if year not in years:
        raise ValueError(
            f"Year {year} not in EDGAR data (available {years[0]}-{years[-1]})."
        )

    selected = edgar[edgar["EDGAR Country Code"].isin(iso3) & (edgar["year"] == year)]

    unmapped = sorted(set(selected["Sector"]) - set(sector_map))
    if unmapped:
        logger.info(f"EDGAR sectors not mapped to a model sector: {unmapped}")

    selected = selected[selected["Sector"].isin(sector_map)]
    reference = (
        selected.assign(sector=selected["Sector"].map(sector_map))
        .groupby("sector")["value"]
        .sum()
        .rename("reference")
    )
    return reference


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("build_reference_co2_edgar")

    configure_logging(snakemake)

    countries = create_country_list(snakemake.params["countries"])
    year = int(snakemake.params["year"])

    edgar = read_edgar_by_sector(snakemake.input["edgar"], snakemake.params["sheet"])
    reference = build_reference(edgar, countries, year, snakemake.params["sector_map"])

    os.makedirs(os.path.dirname(snakemake.output["reference"]), exist_ok=True)
    reference.to_csv(snakemake.output["reference"])
    logger.info(
        f"EDGAR CO2 reference for {countries} in {year} [MtCO2]:\n{reference.round(1)}"
    )
