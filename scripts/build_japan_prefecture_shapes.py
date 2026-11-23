# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Build the prefecture boundaries of Japan used by the prefecture generation
validation (``data/japan/japan_prefectures_<year>.geojson``).

One-off data preparation, not part of the Snakemake workflow. The prepared
file is stored in the repository, so the large source data does not need to
be downloaded to run the validation.

Source: MLIT National Land Numerical Information, Administrative Areas (N03),
nationwide file, e.g. ``N03-20230101_GML.zip`` for the 2023 edition
(boundaries as of 1 January 2023):
https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2023.html
Attribution: 「国土数値情報（行政区域データ）」（国土交通省）を加工して作成.
License: MLIT National Land Numerical Information terms of use, based on the
Government of Japan Standard Terms of Use (Version 2.0), compatible with
CC BY 4.0: https://nlftp.mlit.go.jp/ksj/other/agreement_01.html

The municipalities are merged by prefecture code (first two digits of the
administrative area code ``N03_007``, JIS X 0401), English prefecture names
are added, and the boundaries are simplified to keep the file small.

Example::

    python scripts/build_japan_prefecture_shapes.py \\
        --input N03-2023/N03-23_230101.shp \\
        --output data/japan/japan_prefectures_2023.geojson
"""

import argparse
import logging
from pathlib import Path

import geopandas as gpd

logger = logging.getLogger(__name__)

# JIS X 0401 prefecture code -> English name
PREFECTURES = {
    "01": "Hokkaido",
    "02": "Aomori",
    "03": "Iwate",
    "04": "Miyagi",
    "05": "Akita",
    "06": "Yamagata",
    "07": "Fukushima",
    "08": "Ibaraki",
    "09": "Tochigi",
    "10": "Gunma",
    "11": "Saitama",
    "12": "Chiba",
    "13": "Tokyo",
    "14": "Kanagawa",
    "15": "Niigata",
    "16": "Toyama",
    "17": "Ishikawa",
    "18": "Fukui",
    "19": "Yamanashi",
    "20": "Nagano",
    "21": "Gifu",
    "22": "Shizuoka",
    "23": "Aichi",
    "24": "Mie",
    "25": "Shiga",
    "26": "Kyoto",
    "27": "Osaka",
    "28": "Hyogo",
    "29": "Nara",
    "30": "Wakayama",
    "31": "Tottori",
    "32": "Shimane",
    "33": "Okayama",
    "34": "Hiroshima",
    "35": "Yamaguchi",
    "36": "Tokushima",
    "37": "Kagawa",
    "38": "Ehime",
    "39": "Kochi",
    "40": "Fukuoka",
    "41": "Saga",
    "42": "Nagasaki",
    "43": "Kumamoto",
    "44": "Oita",
    "45": "Miyazaki",
    "46": "Kagoshima",
    "47": "Okinawa",
}


def build_prefecture_shapes(source, tolerance):
    """
    Return one (multi)polygon per prefecture in EPSG:4326.

    Parameters
    ----------
    source : str or Path
        N03 municipality boundaries (shapefile or GeoJSON) with ``N03_007``.
    tolerance : float
        Simplification tolerance in degrees (0 = no simplification).
    """
    municipalities = gpd.read_file(source, columns=["N03_007"])

    if municipalities["N03_007"].isna().any():
        logger.warning(
            "%d polygons without administrative area code are dropped",
            municipalities["N03_007"].isna().sum(),
        )
        municipalities = municipalities.dropna(subset=["N03_007"])

    municipalities["prefecture_code"] = municipalities["N03_007"].str[:2]

    unknown = set(municipalities["prefecture_code"]) - set(PREFECTURES)
    if unknown:
        raise ValueError(f"Unknown prefecture codes: {sorted(unknown)}")

    prefectures = (
        municipalities[["prefecture_code", "geometry"]]
        .dissolve(by="prefecture_code")
        .reset_index()
        .to_crs("EPSG:4326")
    )
    prefectures["prefecture"] = prefectures["prefecture_code"].map(PREFECTURES)

    if tolerance > 0:
        prefectures["geometry"] = prefectures.simplify(
            tolerance, preserve_topology=True
        ).make_valid()

    return prefectures[["prefecture_code", "prefecture", "geometry"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, help="N03 shapefile, e.g. N03-23_230101.shp"
    )
    parser.add_argument("--output", required=True, help="Output GeoJSON")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.001,
        help="Simplification tolerance in degrees (about 100 m), 0 to keep all points",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=4,
        help="Decimal places of the coordinates in the GeoJSON (4 = about 10 m)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    prefectures = build_prefecture_shapes(args.input, args.tolerance)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prefectures.to_file(output, driver="GeoJSON", COORDINATE_PRECISION=args.precision)

    logger.info(
        "Wrote %d prefectures to %s (%.1f MB)",
        len(prefectures),
        output,
        output.stat().st_size / 1e6,
    )


if __name__ == "__main__":
    main()
