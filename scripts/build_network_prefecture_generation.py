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

Works for electricity-only and sector-coupled networks:

- Generators and storage units are counted only on electricity buses. In
  sector-coupled networks, generators on fuel buses are fuel supply and
  solar thermal sits on heat buses.
- Power plants represented as Links (fuel bus -> electricity bus, see
  ``convert_conventional_generators_to_links`` in PyPSA-Earth) are counted
  with their electricity output ``-p1``.
"""

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pypsa
import yaml
from build_network_statistics import get_electricity_production_links

logger = logging.getLogger(__name__)

METRIC_CRS = "EPSG:6933"
GENERATION_COLUMNS = ["prefecture", "carrier", "model_GWh"]


def assign_buses_to_prefectures(network, prefectures):
    """
    Add a ``prefecture`` column to ``network.buses``.

    Returns the spatial match of the grid buses (bus, x, y, prefecture,
    distance to the prefecture in metres).
    """
    grid_buses = network.buses.query("carrier in ['AC', 'DC']")

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
    other = network.buses["prefecture"].isna()
    network.buses.loc[other, "prefecture"] = network.buses.loc[other, "location"].map(
        location_prefecture
    )

    bus_map = joined[["x", "y", "prefecture", "dist_m"]].rename_axis("bus")
    return bus_map.reset_index()


def annual_generation_by_unit(network, settings):
    """
    Return annual electricity generation per unit (MWh).

    Columns: ``bus``, ``carrier``, ``component``, ``MWh``.
    """
    weights = network.snapshot_weightings.generators

    electricity_buses = network.buses.index[
        network.buses.carrier.isin(settings["electricity_bus_carriers"])
    ]

    # generators on electricity buses
    generators = pd.DataFrame(
        {
            "bus": network.generators.bus,
            "carrier": network.generators.carrier,
            "component": "Generator",
            "MWh": network.generators_t.p.reindex(
                columns=network.generators.index, fill_value=0.0
            )
            .mul(weights, axis=0)
            .sum(),
        }
    )
    generators = generators[generators["bus"].isin(electricity_buses)]

    # storage units: only discharge counts as generation
    storage = pd.DataFrame(
        {
            "bus": network.storage_units.bus,
            "carrier": network.storage_units.carrier,
            "component": "StorageUnit",
            "MWh": network.storage_units_t.p.reindex(
                columns=network.storage_units.index, fill_value=0.0
            )
            .clip(lower=0)
            .mul(weights, axis=0)
            .sum(),
        }
    )
    storage = storage[storage["bus"].isin(electricity_buses)]

    # power plants represented as links: electricity output is -p1
    production_links = get_electricity_production_links(network)
    links = pd.DataFrame(
        {
            "bus": network.links.loc[production_links, "bus1"],
            "carrier": network.links.loc[production_links, "carrier"],
            "component": "Link",
            "MWh": (
                -network.links_t.p1.reindex(columns=production_links, fill_value=0.0)
            )
            .clip(lower=0)
            .mul(weights, axis=0)
            .sum(),
        }
    )

    units = pd.concat([generators, storage, links])
    units = units[~units["carrier"].isin(settings["not_generation"])]

    logger.info(
        "Units counted: %d generators, %d storage units, %d links",
        (units["component"] == "Generator").sum(),
        (units["component"] == "StorageUnit").sum(),
        (units["component"] == "Link").sum(),
    )
    return units


def build_network_prefecture_generation(network, prefectures, settings):
    """
    Return model generation per prefecture and category (GWh) and the bus map.

    All prefectures of ``prefectures`` and all categories of ``settings`` are
    included, with 0 where the model has no generation.
    """
    bus_map = assign_buses_to_prefectures(network, prefectures)

    units = annual_generation_by_unit(network, settings)
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
