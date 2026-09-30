# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Plot CO2 emissions and fossil fuel use by sector for a solved sector-coupled
network, optionally compared against reference emissions (e.g. IEA).

Sectors are read from the ``sector`` column of Loads and Links, which
``prepare_sector_network`` sets on sector-coupled networks. Components without
a sector are reported as ``unassigned``.
"""

import logging
import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pypsa
from helpers import configure_logging

logger = logging.getLogger(__name__)

def statistic_by_sector(n, statistic, **kwargs):
    """
    Evaluate an ``n.statistics`` method for Loads and Links and sum it per
    ``sector``. Rows with an empty sector are reported as ``unassigned``, as is
    everything in networks built before sector tagging (no ``sector`` column).
    """
    method = getattr(n.statistics, statistic)
    try:
        result = method(comps=["Load", "Link"], groupby="sector", **kwargs)
    except KeyError:
        logger.warning(
            f"Loads or Links have no 'sector' column; reporting all as 'unassigned'."
        )
        result = method(comps=["Load", "Link"], groupby=False, **kwargs)
        return pd.Series({'unassigned': result.sum()}) if not result.empty else result

    if result.empty:
        return pd.Series(dtype=float)

    sectors = result.index.get_level_values("sector").fillna("")
    return result.groupby(sectors.where(sectors != "", "unassigned")).sum()


def fuel_use_by_sector(n, fuels):
    """
    Fuel withdrawn from the buses of each fuel carrier, per sector [TWh].
    """
    bus_carriers = set(n.buses.carrier.unique())
    frames = {}
    for fuel in fuels:
        if fuel not in bus_carriers:
            logger.warning(f"No buses with carrier '{fuel}' in the network; skipping.")
            continue
        frames[fuel] = statistic_by_sector(n, "withdrawal", bus_carrier=fuel)

    fuel_use = pd.DataFrame(frames).fillna(0.0) / 1e6
    fuel_use.index.name = "sector"
    return fuel_use


def load_reference(path, year, reference_map):
    """
    Read reference emissions [MtCO2] per model sector.

    Accepts either a table already in model sectors (columns ``sector`` and
    ``reference``, as written by ``build_reference_co2_edgar``) or a raw CSV
    with a sector label column followed by ``Value`` and ``Year`` columns (IEA
    download format), whose labels are mapped with ``reference_map``.
    """
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()

    if {"sector", "reference"}.issubset(df.columns):
        return df.set_index("sector")["reference"]

    label_column = df.columns[0]

    df = df[df["Year"] == year]
    if df.empty:
        logger.warning(f"No reference emissions for {year} in {path}.")
        return pd.Series(dtype=float, name="reference")

    unmapped = sorted(set(df[label_column]) - set(reference_map))
    if unmapped:
        logger.info(f"Reference categories not mapped to a sector: {unmapped}")

    reference = df.set_index(label_column)["Value"]
    reference = reference[reference.index.isin(reference_map)]
    reference = reference.rename(index=reference_map)
    return reference.groupby(level=0).sum().rename("reference")


def build_emissions_table(model, reference):
    table = pd.concat([model, reference], axis=1)
    if "reference" not in table:
        table["reference"] = float("nan")
    table.index.name = "sector"
    table["difference"] = table["model"] - table["reference"]
    table["relative_difference"] = table["difference"] / table["reference"]
    return table.sort_values("model", ascending=False)


def plot_emissions(table, year, output_path, model_colors, reference_label="Reference"):
    fig, ax = plt.subplots(figsize=(9, 5))
    has_reference = table["reference"].notna().any()

    if has_reference:
        table[["reference", "model"]].rename(
            columns={"reference": f"{reference_label} ({year})", "model": "Model"}
        ).plot.bar(ax=ax, color=[model_colors[k] for k in ["reference", "model"]], zorder=3)
        ax.legend(frameon=False)
        ax.set_title("CO2 emissions by sector: reference vs. model")
    else:
        table["model"].plot.bar(ax=ax, color=model_colors["model"], zorder=3)
        ax.set_title("CO2 emissions by sector (model)")

    ax.set_ylabel("CO2 emissions [MtCO2]")
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlabel("")
    ax.axhline(0, color="black", linewidth=0.8)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_fuel_use(fuel_use, output_path, fuel_colors):
    fig, ax = plt.subplots(figsize=(9, 5))

    if fuel_use.empty or not fuel_use.to_numpy().any():
        ax.text(0.5, 0.5, "No fuel use data available", ha="center", va="center")
        ax.set_axis_off()
    else:
        order = fuel_use.sum(axis=1).sort_values(ascending=False).index
        fuel_use.loc[order].plot.bar(
            ax=ax,
            stacked=True,
            color=[fuel_colors.get(f) for f in fuel_use.columns],
            edgecolor="white",
            linewidth=0.5,
            zorder=3,
        )
        ax.set_ylabel("Fuel use [TWh]")
        ax.set_title("Fossil fuel use by sector")
        ax.legend(title="Fuel", frameon=False)
        ax.grid(axis="y", alpha=0.3, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlabel("")
        ax.axhline(0, color="black", linewidth=0.8)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    if "snakemake" not in globals():
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        from helpers import mock_snakemake

        snakemake = mock_snakemake("plot_sector_emissions")

    configure_logging(snakemake)

    year = int(snakemake.params["reference_year"])
    n = pypsa.Network(snakemake.input["network"])

    energy_balance = statistic_by_sector(n, "energy_balance", bus_carrier="co2")
    energy_balance = (energy_balance / 1e6).rename("model")
    
    if "reference" in snakemake.input.keys():
        reference = load_reference(
            snakemake.input["reference"], year, snakemake.params["reference_map"]
        )
    else:
        reference = pd.Series(dtype=float, name="reference")

    model = energy_balance.rename(index=snakemake.params["model_sector_groups"]).groupby(level=0).sum()
    
    emissions = build_emissions_table(model, reference)
    fuel_use = fuel_use_by_sector(n, snakemake.params["fuels"])

    for output in snakemake.output:
        os.makedirs(os.path.dirname(output), exist_ok=True)

    emissions.to_csv(snakemake.output["co2_table"])
    fuel_use.to_csv(snakemake.output["fuel_table"])
    plot_emissions(
        emissions,
        year,
        snakemake.output["plot_co2"],
        snakemake.params["model_colors"],
        reference_label=snakemake.params["reference_label"],
    )
    plot_fuel_use(fuel_use, snakemake.output["plot_fuel"], snakemake.params["fuel_colors"])

    logger.info(f"CO2 emissions by sector [MtCO2]:\n{emissions.round(1)}")
    logger.info(f"Fuel use by sector [TWh]:\n{fuel_use.round(1)}")
