# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Build the annual electricity generation per prefecture and source of a
PyPSA network of Japan.

Every grid bus (AC/DC) is assigned to one prefecture by a spatial join with
the prefecture boundaries (buses slightly outside every prefecture, e.g. on
the coast, get the nearest one). Other buses inherit the prefecture of their
``location``. All generation at a bus is counted for its prefecture, so the
result gets more accurate the more nodes the network has.

Works for electricity-only and sector-coupled networks. The generation per
asset comes from ``get_electricity_generation_by_asset()`` in
``build_network_statistics.py``, the same accounting as the national
electricity validation; this script only adds the assignment to prefectures
and the METI categories.
"""

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pypsa
import yaml
from build_network_statistics import (
    get_electricity_generation_by_asset,
    harmonize_electricity_carrier_names,
)

logger = logging.getLogger(__name__)

METRIC_CRS = "EPSG:6933"
COUNTRY = "JP"  # only Japanese buses are assigned to prefectures and counted
GENERATION_COLUMNS = ["prefecture", "carrier", "model_GWh"]


def assign_buses_to_prefectures(network, prefectures):
    """
    Add a ``prefecture`` column to ``network.buses`` for the buses in Japan.

    Only buses with ``country == "JP"`` are assigned, so in a multi-country
    network, buses of other countries are not matched to a Japanese prefecture.

    Returns the spatial match of the grid buses (bus, x, y, prefecture,
    distance to the prefecture in metres).
    """
    in_japan = network.buses["country"] == COUNTRY
    grid_buses = network.buses[in_japan & network.buses["carrier"].isin(["AC", "DC"])]
    if grid_buses.empty:
        raise ValueError(f"The network has no AC/DC buses with country '{COUNTRY}'")

    bus_points = gpd.GeoDataFrame(
        grid_buses[["x", "y"]],
        geometry=gpd.points_from_xy(grid_buses.x, grid_buses.y),
        crs="EPSG:4326",
    )

    # bus inside a prefecture -> that prefecture (distance 0)
    # bus just outside (coast) -> nearest prefecture
    joined = gpd.sjoin_nearest(
        bus_points.to_crs(METRIC_CRS),
        prefectures[["prefecture", "geometry"]].to_crs(METRIC_CRS),
        how="left",
        distance_col="dist_m",
    )
    joined = joined[~joined.index.duplicated()]  # bus exactly on a border

    network.buses["prefecture"] = network.buses.index.map(joined["prefecture"])

    # other buses (H2, battery, low voltage ...) get the prefecture of their location
    location_prefecture = network.buses.loc[grid_buses.index, "prefecture"]
    other = network.buses["prefecture"].isna() & in_japan
    network.buses.loc[other, "prefecture"] = network.buses.loc[other, "location"].map(
        location_prefecture
    )

    bus_map = joined[["x", "y", "prefecture", "dist_m"]].rename_axis("bus")
    return bus_map.reset_index()


def build_network_prefecture_generation(network, prefectures, settings):
    """
    Return model generation per prefecture and category (GWh) and the bus map.

    All prefectures of ``prefectures`` and all categories of ``settings`` are
    included, with 0 where the model has no generation.
    """
    bus_map = assign_buses_to_prefectures(network, prefectures)

    # annual generation per asset (MWh), shared with build_network_statistics.py
    units = get_electricity_generation_by_asset(network).rename(
        columns={"generation": "MWh"}
    )
    # same carrier names as the national electricity validation
    units["carrier"] = harmonize_electricity_carrier_names(units["carrier"])
    units = units[~units["carrier"].isin(settings["not_generation"])]

    logger.info(
        "Units counted: %d generators, %d storage units, %d links",
        (units["component"] == "Generator").sum(),
        (units["component"] == "StorageUnit").sum(),
        (units["component"] == "Link").sum(),
    )

    # only generation on buses in Japan is compared with METI
    outside_japan = units["bus"].map(network.buses["country"]) != COUNTRY
    if outside_japan.any():
        logger.info(
            "%d units outside Japan are not counted (%.1f TWh)",
            outside_japan.sum(),
            units.loc[outside_japan, "MWh"].sum() / 1e6,
        )
    units = units[~outside_japan]

    units["prefecture"] = units["bus"].map(network.buses["prefecture"])
    no_prefecture = units["prefecture"].isna()
    if no_prefecture.any():
        logger.warning(
            "%d units without prefecture (%.1f TWh) are not counted",
            no_prefecture.sum(),
            units.loc[no_prefecture, "MWh"].sum() / 1e6,
        )

    unmapped = set(units["carrier"]) - set(settings["carrier_mapping"])
    if unmapped:
        logger.warning(
            "Carriers not mapped to a category, not counted: %s (%.1f TWh)",
            sorted(unmapped),
            units.loc[units["carrier"].isin(unmapped), "MWh"].sum() / 1e6,
        )

    units["category"] = units["carrier"].map(settings["carrier_mapping"])

    generation = (
        units.groupby(["prefecture", "category"])["MWh"]
        .sum()
        .div(1e3)  # MWh -> GWh
        .unstack(fill_value=0.0)
        .reindex(
            index=sorted(prefectures["prefecture"]),
            columns=settings["categories"],
            fill_value=0.0,
        )
        .stack()
        .rename("model_GWh")
        .rename_axis(["prefecture", "carrier"])
        .reset_index()
    )

    return generation[GENERATION_COLUMNS], bus_map


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", required=True, help="PyPSA network (.nc)")
    parser.add_argument(
        "--shapes", required=True, help="Prefecture boundaries (geojson)"
    )
    parser.add_argument(
        "--config", required=True, help="config/japan_prefecture_generation.yaml"
    )
    parser.add_argument(
        "--output", required=True, help="Output CSV: generation per prefecture"
    )
    parser.add_argument(
        "--bus-output", required=True, help="Output CSV: bus -> prefecture"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with open(args.config) as handle:
        settings = yaml.safe_load(handle)

    network = pypsa.Network(args.network)
    prefectures = gpd.read_file(args.shapes)
    if "prefecture" not in prefectures.columns:
        raise ValueError(f"No 'prefecture' column in {args.shapes}")

    generation, bus_map = build_network_prefecture_generation(
        network, prefectures, settings
    )

    for path, table in [(args.output, generation), (args.bus_output, bus_map)]:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(path, index=False)

    without_bus = sorted(set(prefectures["prefecture"]) - set(bus_map["prefecture"]))
    logger.info(
        "%d grid buses assigned; %d snapped to the nearest prefecture",
        len(bus_map),
        (bus_map["dist_m"] > 0).sum(),
    )
    logger.info("Prefectures without bus (%d): %s", len(without_bus), without_bus)
    logger.info(
        "Model totals per category [TWh]:\n%s",
        (generation.groupby("carrier")["model_GWh"].sum() / 1e3)
        .reindex(settings["categories"])
        .round(1)
        .to_string(),
    )


if __name__ == "__main__":
    main()
