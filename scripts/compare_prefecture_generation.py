# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: PyPSA-Earth and PyPSA-Eur Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Compare the annual electricity generation per prefecture and source of a
PyPSA network of Japan with the METI reference, per prefecture and per
region, and plot the results.

The "misplaced generation" in the summary is the sum of the absolute
differences divided by the METI total of a category. Comparing it per
prefecture and per region shows how much of the prefecture differences only
come from where the cluster buses are located.
"""

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)


def add_differences(table):
    """Add ``diff_GWh`` (model - reference) and ``diff_pct`` (% of reference)."""
    table["diff_GWh"] = table["model_GWh"] - table["reference_GWh"]
    table["diff_pct"] = (
        table["diff_GWh"]
        / table["reference_GWh"].where(table["reference_GWh"] > 0)
        * 100
    )
    return table


def compare_prefectures(model, reference, bus_map):
    """Return one row per prefecture and category with model and reference."""
    comparison = model.merge(reference, on=["prefecture", "carrier"], how="outer")
    comparison[["model_GWh", "reference_GWh"]] = comparison[
        ["model_GWh", "reference_GWh"]
    ].fillna(0.0)

    comparison = add_differences(comparison)
    comparison["has_bus"] = comparison["prefecture"].isin(bus_map["prefecture"])
    return comparison


def compare_regions(comparison, regions):
    """Return one row per region and category."""
    prefecture_to_region = {p: r for r, prefs in regions.items() for p in prefs}
    comparison["region"] = comparison["prefecture"].map(prefecture_to_region)

    without_region = sorted(comparison.loc[comparison["region"].isna(), "prefecture"])
    if without_region:
        logger.warning("Prefectures without region: %s", sorted(set(without_region)))

    region_comparison = (
        comparison.groupby(["region", "carrier"])[["model_GWh", "reference_GWh"]]
        .sum()
        .reset_index()
    )
    return add_differences(region_comparison)


def misplaced_share(table, category):
    """Sum of absolute differences in % of the reference total of a category."""
    rows = table[table["carrier"] == category]
    total = rows["reference_GWh"].sum()
    if total == 0:
        return np.nan
    return rows["diff_GWh"].abs().sum() / total * 100


def build_summary(comparison, region_comparison, categories):
    """Return national totals and misplaced generation per category."""
    summary = (
        comparison.groupby("carrier")[["model_GWh", "reference_GWh"]]
        .sum()
        .div(1e3)
        .rename(columns={"model_GWh": "model_TWh", "reference_GWh": "reference_TWh"})
        .reindex(categories)
    )
    summary["diff_pct"] = (
        summary["model_TWh"]
        / summary["reference_TWh"].where(summary["reference_TWh"] > 0)
        - 1
    ) * 100
    summary["misplaced_pct_prefecture"] = [
        misplaced_share(comparison, c) for c in categories
    ]
    summary["misplaced_pct_region"] = [
        misplaced_share(region_comparison, c) for c in categories
    ]
    return summary.rename_axis("carrier").reset_index()


def plot_national(summary, path):
    """Bar plot of national totals per category."""
    x = np.arange(len(summary))
    width = 0.4

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(x - width / 2, summary["model_TWh"], width, label="PyPSA")
    ax.bar(x + width / 2, summary["reference_TWh"], width, label="METI")

    ax.set_xticks(x)
    ax.set_xticklabels(summary["carrier"])
    ax.set_xlabel("Carrier")
    ax.set_ylabel("Annual Generation (TWh)")
    ax.set_title("Japan Electricity Generation: PyPSA vs METI")
    ax.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax.legend()

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_prefectures_by_carrier(comparison, categories, path):
    """Line plot per prefecture, one subplot per category."""
    fig, axes = plt.subplots(
        len(categories), 1, figsize=(18, 4 * len(categories)), sharex=True
    )

    for ax, carrier in zip(axes, categories):
        df = comparison[comparison["carrier"] == carrier].sort_values("prefecture")
        x = np.arange(len(df))

        ax.plot(x, df["model_GWh"], marker="o", linewidth=2, label="PyPSA")
        ax.plot(x, df["reference_GWh"], marker="s", linewidth=2, label="METI")

        # mark prefectures without any bus in the model
        for i, has_bus in enumerate(df["has_bus"]):
            if not has_bus:
                ax.axvspan(i - 0.5, i + 0.5, color="grey", alpha=0.2)

        ax.set_title(carrier)
        ax.set_ylabel("GWh")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(loc="upper right")

    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(df["prefecture"], rotation=90)
    axes[-1].set_xlabel("Prefecture (grey = no bus in the model)")

    fig.suptitle("Annual Generation by Prefecture and Carrier: PyPSA vs METI", y=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_prefecture_totals(comparison, path):
    """Line plot of total generation (all categories) per prefecture."""
    totals = (
        comparison.groupby("prefecture")[["model_GWh", "reference_GWh"]]
        .sum()
        .sort_index()
    )

    fig, ax = plt.subplots(figsize=(18, 6))
    ax.plot(totals.index, totals["model_GWh"], marker="o", linewidth=2, label="PyPSA")
    ax.plot(
        totals.index, totals["reference_GWh"], marker="s", linewidth=2, label="METI"
    )

    ax.tick_params(axis="x", rotation=90)
    ax.set_xlabel("Prefecture")
    ax.set_ylabel("Annual Generation (GWh)")
    ax.set_title(
        "PyPSA vs METI Annual Electricity Generation by Prefecture (all carriers)"
    )
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_regions_by_carrier(region_comparison, categories, region_order, path):
    """Line plot per region, one subplot per category."""
    fig, axes = plt.subplots(
        len(categories), 1, figsize=(12, 3.5 * len(categories)), sharex=True
    )

    for ax, carrier in zip(axes, categories):
        df = (
            region_comparison[region_comparison["carrier"] == carrier]
            .set_index("region")
            .reindex(region_order)
        )

        ax.plot(df.index, df["model_GWh"], marker="o", linewidth=2, label="PyPSA")
        ax.plot(df.index, df["reference_GWh"], marker="s", linewidth=2, label="METI")

        ax.set_title(carrier)
        ax.set_ylabel("GWh")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(loc="upper right")

    axes[-1].set_xlabel("Region")

    fig.suptitle("Annual Generation by Region and Carrier: PyPSA vs METI", y=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", required=True, help="Model generation per prefecture"
    )
    parser.add_argument(
        "--reference", required=True, help="METI reference per prefecture"
    )
    parser.add_argument("--bus-map", required=True, help="Bus -> prefecture map")
    parser.add_argument(
        "--config", required=True, help="config/japan_prefecture_generation.yaml"
    )
    parser.add_argument("--output", required=True, help="Comparison per prefecture")
    parser.add_argument("--region-output", required=True, help="Comparison per region")
    parser.add_argument("--summary-output", required=True, help="Summary per category")
    parser.add_argument("--plot-national", required=True)
    parser.add_argument("--plot-prefecture", required=True)
    parser.add_argument("--plot-prefecture-total", required=True)
    parser.add_argument("--plot-region", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with open(args.config) as handle:
        settings = yaml.safe_load(handle)
    categories = settings["categories"]
    regions = settings["regions"]

    model = pd.read_csv(args.model)
    reference = pd.read_csv(args.reference)
    bus_map = pd.read_csv(args.bus_map)

    comparison = compare_prefectures(model, reference, bus_map)
    region_comparison = compare_regions(comparison, regions)
    summary = build_summary(comparison, region_comparison, categories)

    for path in [
        args.output,
        args.region_output,
        args.summary_output,
        args.plot_national,
        args.plot_prefecture,
        args.plot_prefecture_total,
        args.plot_region,
    ]:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    comparison.round(2).to_csv(args.output, index=False)
    region_comparison.round(2).to_csv(args.region_output, index=False)
    summary.round(2).to_csv(args.summary_output, index=False)

    plot_national(summary, args.plot_national)
    plot_prefectures_by_carrier(comparison, categories, args.plot_prefecture)
    plot_prefecture_totals(comparison, args.plot_prefecture_total)
    plot_regions_by_carrier(
        region_comparison, categories, list(regions), args.plot_region
    )

    logger.info("Summary per category:\n%s", summary.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
