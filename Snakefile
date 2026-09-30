# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys

sys.path.append("./scripts")

from os.path import normpath, exists, isdir
from shutil import copyfile, move

from helpers import create_country_list

# Create a temporary backup of the validation results before Snakemake deletes it
if exists("results/health_status.csv"):
    copyfile("results/health_status.csv", "results/health_status.csv.tmp")


configfile: "config.yaml"


storage HTTP:
    provider="http",


validation_config = config["network_validation"]

network_path = validation_config["network_path"]
countries = validation_config["countries"]
years = validation_config["year"]

validation_name = validation_config["name"]

reference_statistics_dir = "resources/reference_statistics"
network_statistics_dir = "resources/network_statistics"
results_dir = "results"
logs_dir = "logs"

if validation_name:
    reference_statistics_dir += f"/{validation_name}"
    network_statistics_dir += f"/{validation_name}"
    results_dir += f"/{validation_name}"
    logs_dir += f"/{validation_name}"


rule clean:
    run:
        try:
            shell("snakemake -j 1 visualize_data --delete-all-output")
        except:
            pass


rule download_ember_data:
    input:
        ember_data=storage.HTTP(
            "https://storage.googleapis.com/emb-prod-bkt-publicdata/"
            "public-downloads/yearly_full_release_long_format.csv"
        ),
    output:
        ember_data="data/ember/yearly_full_release_long_format.csv",
    run:
        os.makedirs(
            os.path.dirname(output.ember_data),
            exist_ok=True,
        )
        copyfile(
            input.ember_data,
            output.ember_data,
        )


rule build_reference_demand_ember:
    input:
        demand_ember="data/ember/yearly_full_release_long_format.csv",
    output:
        demand_ember="resources/clean/ember_demand_data.csv",
    log:
        "logs/build_reference_demand_ember.log",
    script:
        "scripts/build_reference_demand_ember.py"


rule build_reference_installed_capacity_ember:
    input:
        cap_ember="data/ember/yearly_full_release_long_format.csv",
    output:
        cap_ember="resources/clean/ember_capacity_data.csv",
    log:
        "logs/build_reference_installed_capacity_ember.log",
    script:
        "scripts/build_reference_installed_capacity_ember.py"


rule build_reference_generation_ember:
    input:
        gen_ember="data/ember/yearly_full_release_long_format.csv",
    output:
        gen_ember="resources/clean/ember_generation_data.csv",
    log:
        "logs/build_reference_generation_ember.log",
    script:
        "scripts/build_reference_generation_ember.py"


rule build_reference_demand_ourworldindata:
    input:
        demand_owid="data/electricity_demand/owid-energy-data.csv",  # from https://nyc3.digitaloceanspaces.com/owid-public/data/energy/owid-energy-data.csv
    output:
        demand_owid="resources/clean/owid_demand_data.csv",
    log:
        "logs/build_reference_demand_ourworldindata.log",
    script:
        "scripts/build_reference_demand_ourworldindata.py"


rule build_reference_installed_capacity_irena:
    input:
        cap_irena="data/installed_capacity/ELECSTAT_20240808-144258.csv",  # IRENA capacity data from https://pxweb.irena.org/pxweb/en/IRENASTAT/IRENASTAT__Power%20Capacity%20and%20Generation/Country_ELECSTAT_2024_H2.px/
    output:
        cap_irena="resources/clean/irena_capacity_data.csv",
    log:
        "logs/build_reference_installed_capacity_irena.log",
    script:
        "scripts/build_reference_installed_capacity_irena.py"


rule retrieve_reference_generation_irena:
    input:
        generation_irena=storage.HTTP(
            "https://raw.githubusercontent.com/"
            "pypsa-meets-earth/temporary_storage/main/"
            "datasets/C-ELECGEN_20260713-113435.csv"
        ),
    output:
        generation_irena="data/electricity_generation/C-ELECGEN_20260713-113435.csv",
    run:
        os.makedirs(
            os.path.dirname(output.generation_irena),
            exist_ok=True,
        )
        copyfile(
            input.generation_irena,
            output.generation_irena,
        )


rule build_reference_generation_irena:
    input:
        # Source: https://pxweb.irena.org/pxweb/en/IRENASTAT/IRENASTAT__Power%20Capacity%20and%20Generation/Country_ELECGEN_2025_H2_v-PX%201.px/
        generation_irena="data/electricity_generation/C-ELECGEN_20260713-113435.csv",
    output:
        generation_irena="resources/clean/irena_generation_data.csv",
    log:
        "logs/build_reference_generation_irena.log",
    script:
        "scripts/build_reference_generation_irena.py"


rule build_network_geojson:
    input:
        buscodes="data/electricity_transmission/Input - Center points.csv",
        lineexist="data/electricity_transmission/GTD-v1.1_regional_existing.csv",
        lineplan="data/electricity_transmission/GTD-v1.1_regional_planned.csv",
        network_path=network_path,
    output:
        network_existing=f"{reference_statistics_dir}/network_exist.geojson",
        network_planned=f"{reference_statistics_dir}/network_planned.geojson",
        network_model=f"{network_statistics_dir}/network_model.geojson",
    log:
        f"{logs_dir}/build_network_geojson.log",
    params:
        countries=countries,
        shapefile=validation_config["shapefile"],
        validate_cross_border_capacity=validation_config[
            "validate_cross_border_capacity"
        ],
    script:
        "scripts/build_network_geojson.py"


rule build_reference_statistics:
    input:
        demand_ourworldindata="resources/clean/owid_demand_data.csv",
        demand_ember="resources/clean/ember_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        cap_ember="resources/clean/ember_capacity_data.csv",
        gen_ember="resources/clean/ember_generation_data.csv",
        gen_irena="resources/clean/irena_generation_data.csv",
    output:
        demand=f"{reference_statistics_dir}/demand.csv",
        installed_capacity=f"{reference_statistics_dir}/installed_capacity.csv",
        electricity_generation=(
            f"{reference_statistics_dir}/electricity_generation.csv"
        ),
    log:
        f"{logs_dir}/build_reference_statistics.log",
    params:
        datasets=config["datasets"],
        year=years,
        countries=countries,
    script:
        "scripts/build_reference_statistics.py"


rule build_network_statistics:
    input:
        network_path=network_path,
    output:
        demand=f"{network_statistics_dir}/demand.csv",
        installed_capacity=f"{network_statistics_dir}/installed_capacity.csv",
        optimal_capacity=f"{network_statistics_dir}/optimal_capacity.csv",
        electricity_generation=f"{network_statistics_dir}/electricity_generation.csv",
    log:
        f"{logs_dir}/build_network_statistics.log",
    params:
        network_path=network_path,
        year=years,
        countries=countries,
        shapefile=validation_config["shapefile"],
        validate_cross_border_capacity=validation_config[
            "validate_cross_border_capacity"
        ],
        network=validation_config,
    script:
        "scripts/build_network_statistics.py"


rule make_comparison:
    input:
        demand_network=f"{network_statistics_dir}/demand.csv",
        installed_capacity_network=f"{network_statistics_dir}/installed_capacity.csv",
        optimal_capacity_network=f"{network_statistics_dir}/optimal_capacity.csv",
        electricity_generation_network=(
            f"{network_statistics_dir}/electricity_generation.csv"
        ),
        network_geojson_network=f"{network_statistics_dir}/network_model.geojson",
        demand_reference=f"{reference_statistics_dir}/demand.csv",
        installed_capacity_reference=(
            f"{reference_statistics_dir}/installed_capacity.csv"
        ),
        electricity_generation_reference=(
            f"{reference_statistics_dir}/electricity_generation.csv"
        ),
        network_geojson_reference=f"{reference_statistics_dir}/network_exist.geojson",
    output:
        demand_comparison=f"{results_dir}/tables/demand.csv",
        installed_capacity_comparison=f"{results_dir}/tables/installed_capacity.csv",
        optimal_capacity_comparison=f"{results_dir}/tables/optimal_capacity.csv",
        electricity_generation_comparison=(
            f"{results_dir}/tables/electricity_generation.csv"
        ),
        network_comparison_geojson=f"{results_dir}/network_comparison.geojson",
    log:
        f"{logs_dir}/make_comparison.log",
    params:
        datasets=config["datasets"],
    script:
        "scripts/make_comparison.py"


rule visualize_data:
    input:
        demand_comparison=f"{results_dir}/tables/demand.csv",
        installed_capacity_comparison=f"{results_dir}/tables/installed_capacity.csv",
        optimal_capacity_comparison=f"{results_dir}/tables/optimal_capacity.csv",
        electricity_generation_comparison=(
            f"{results_dir}/tables/electricity_generation.csv"
        ),
        osm_lines=os.path.join(
            config["plot_osm_grid_network"]["grid_path"],
            "all_clean_lines.geojson",
        ),
        osm_substations=os.path.join(
            config["plot_osm_grid_network"]["grid_path"],
            "all_clean_substations.geojson",
        ),
    output:
        plot_demand=f"{results_dir}/figures/demand_comparison.png",
        plot_installed_capacity=(
            f"{results_dir}/figures/installed_capacity_comparison.png"
        ),
        plot_electricity_generation=(
            f"{results_dir}/figures/electricity_generation_comparison.png"
        ),
        plot_capacity_mix=f"{results_dir}/figures/capacity_mix_comparison.png",
        plot_capacity_grid=f"{results_dir}/figures/capacity_grid_comparison.png",
        plot_grid_network=f"{results_dir}/figures/grid_network.png",
        line_length_by_voltage=f"{results_dir}/tables/line_length_by_voltage.csv",
    log:
        f"{logs_dir}/visualize_data.log",
    params:
        line_voltages=config["plot_osm_grid_network"]["line_voltages"],
        voltage_colors=config["plot_osm_grid_network"]["voltage_colors"],
        plot_circuits=config["plot_osm_grid_network"]["plot_circuits"],
    script:
        "scripts/visualize_data.py"


sector_emissions_config = config.get("sector_emissions", {})
reference_source = sector_emissions_config.get("reference_source", "none")
edgar_config = sector_emissions_config.get("edgar", {})
csv_reference_config = sector_emissions_config.get("csv", {})
sector_emissions_year = sector_emissions_config.get("reference_year") or years[0]
edgar_file = "data/edgar/" + os.path.basename(edgar_config.get("url", "edgar.xlsx"))


rule retrieve_edgar_co2:
    input:
        edgar=storage.HTTP(edgar_config.get("url", "")),
    output:
        edgar=edgar_file,
    run:
        os.makedirs(os.path.dirname(output.edgar), exist_ok=True)
        copyfile(input.edgar, output.edgar)


rule build_reference_co2_edgar:
    input:
        edgar=edgar_file,
    output:
        reference=f"{reference_statistics_dir}/co2_emissions_by_sector.csv",
    log:
        f"{logs_dir}/build_reference_co2_edgar.log",
    params:
        countries=countries,
        year=sector_emissions_year,
        sheet=edgar_config.get("sheet", "fossil_CO2_by_sector_country_su"),
        sector_map=edgar_config.get("sector_map", {}),
    script:
        "scripts/build_reference_co2_edgar.py"


def sector_emissions_inputs(wildcards):
    inputs = {"network": network_path}
    if reference_source == "edgar":
        inputs["reference"] = f"{reference_statistics_dir}/co2_emissions_by_sector.csv"
    elif reference_source == "csv":
        inputs["reference"] = csv_reference_config["path"]
    elif reference_source not in ("none", "", None):
        raise ValueError(
            f"Unknown sector_emissions.reference_source '{reference_source}'. "
            "Use 'edgar', 'csv' or 'none'."
        )
    return inputs


def sector_emissions_reference_config():
    return {"edgar": edgar_config, "csv": csv_reference_config}.get(
        reference_source, {}
    )


rule plot_sector_emissions:
    input:
        unpack(sector_emissions_inputs),
    output:
        co2_table=f"{results_dir}/tables/co2_emissions_by_sector.csv",
        fuel_table=f"{results_dir}/tables/fuel_use_by_sector.csv",
        plot_co2=f"{results_dir}/figures/co2_emissions_by_sector.png",
        plot_fuel=f"{results_dir}/figures/fuel_use_by_sector.png",
    log:
        f"{logs_dir}/plot_sector_emissions.log",
    params:
        reference_year=sector_emissions_year,
        reference_label=sector_emissions_reference_config().get(
            "label", "Reference"
        ),
        reference_map=csv_reference_config.get("sector_map", {}),
        model_sector_groups=config["sector_emissions"].get(
            "model_sector_groups", {}
        ),
        fuels=config["sector_emissions"].get("fuels", ["coal", "oil", "gas"]),
        fuel_colors=config["sector_emissions"]["fuel_colors"],
        model_colors=config["sector_emissions"]["model_colors"],
    script:
        "scripts/plot_sector_emissions.py"


rule create_example_DE:
    output:
        "resources/example_DE.nc",
    log:
        "logs/create_example_DE.log",
    run:
        import pypsa

        n = pypsa.examples.scigrid_de()
        n.buses["country"] = "DE"
        n.export_to_netcdf(output[0])
        print(f"Created example network at {output[0]}")


rule build_health_status:
    input:
        demand_ourworldindata="resources/clean/owid_demand_data.csv",
        demand_ember="resources/clean/ember_demand_data.csv",
        cap_irena="resources/clean/irena_capacity_data.csv",
        cap_ember="resources/clean/ember_capacity_data.csv",
        gen_ember="resources/clean/ember_generation_data.csv",
        gen_irena="resources/clean/irena_generation_data.csv",
    output:
        health_status="results/health_status.csv",
    log:
        "logs/build_health_status.log",
    params:
        networks=config["network_validation"].get("networks", {}),
        year=config["network_validation"]["year"],
        datasets=config.get("datasets", {}),
        fallback_pypsa_earth_version=config["network_validation"].get(
            "fallback_pypsa_earth_version", ""
        ),
    script:
        "scripts/build_health_status.py"
