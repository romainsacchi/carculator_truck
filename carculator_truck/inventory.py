from . import DATA_DIR
import sys
import glob
from .background_systems import BackgroundSystemModel
from .export import ExportInventory
from inspect import currentframe, getframeinfo
from pathlib import Path
from scipy import sparse
import csv
import itertools
import numexpr as ne
import numpy as np
import xarray as xr

REMIND_FILES_DIR = DATA_DIR / "IAM"


def get_dict_input():
    """
    Load a dictionary with tuple ("name of activity", "location", "unit", "reference product") as key, row/column
    indices as values.

    :return: dictionary with `label:index` pairs.
    :rtype: dict

    """
    filename = "dict_inputs_A_matrix.csv"
    filepath = DATA_DIR / filename
    if not filepath.is_file():
        raise FileNotFoundError(
            "The dictionary of activity labels could not be found."
        )
    csv_dict = {}
    count = 0
    with open(filepath) as f:
        input_dict = csv.reader(f, delimiter=";")
        for row in input_dict:
            if "(" in row[1]:
                new_str = row[1].replace("(", "")
                new_str = new_str.replace(")", "")
                new_str = [s.strip() for s in new_str.split(",") if s]
                t = ()
                for s in new_str:
                    if "low population" in s:
                        s = "low population density, long-term"
                        t += (s,)
                        break
                    else:
                        t += (s.replace("'", ""),)
                csv_dict[(row[0], t, row[2])] = count
            else:
                csv_dict[(row[0], row[1], row[2], row[3])] = count
            count += 1

    return csv_dict


class InventoryCalculation:
    """
    Build and solve the inventory for results characterization and inventory export

    Vehicles to be analyzed can be filtered by passing a `scope` dictionary.
    Some assumptions in the background system can also be adjusted by passing a `background_configuration` dictionary.

    .. code-block:: python

        scope = {
                        'powertrain':['BEV', 'FCEV', 'ICEV-p'],
                    }
        bc = {'country':'CH', # considers electricity network losses for Switzerland
              'custom electricity mix' : [[1,0,0,0,0,0,0,0,0,0], # in this case, 100% hydropower for the first year
                                          [0,1,0,0,0,0,0,0,0,0],
                                          [0,0,1,0,0,0,0,0,0,0],
                                          [0,0,0,1,0,0,0,0,0,0],
                                         ], # in this case, 100% nuclear for the second year
              'fuel blend':{
                  'cng':{ #specify fuel bland for compressed gas
                        'primary fuel':{
                            'type':'biogas - sewage sludge',
                            'share':[0.9, 0.8, 0.7, 0.6] # shares per year. Must total 1 for each year.
                            },
                        'secondary fuel':{
                            'type':'syngas',
                            'share': [0.1, 0.2, 0.3, 0.4]
                            }
                        },
                 'diesel':{
                        'primary fuel':{
                            'type':'synthetic diesel',
                            'share':[0.9, 0.8, 0.7, 0.6]
                            },
                        'secondary fuel':{
                            'type':'biodiesel - cooking oil',
                            'share': [0.1, 0.2, 0.3, 0.4]
                            }
                        },
                'hydrogen':{
                        'primary fuel':{'type':'electrolysis', 'share':[1, 0, 0, 0]},
                        'secondary fuel':{'type':'smr - natural gas', 'share':[0, 1, 1, 1]}
                        }
                    },
              'energy storage': {
                  'electric': {
                      'type':'NMC',
                      'origin': 'NO'
                  },
                  'hydrogen': {
                      'type':'carbon fiber'
                  }
              }
             }

        InventoryCalculation(CarModel.array,
                            background_configuration=background_configuration,
                            scope=scope,
                            scenario="RCP26")

    The `custom electricity mix` key in the background_configuration dictionary defines an electricity mix to apply,
    under the form of one or several array(s), depending on the number of years to analyze,
    that should total 1, of which the indices correspond to:

        - [0]: hydro-power
        - [1]: nuclear
        - [2]: natural gas
        - [3]: solar power
        - [4]: wind power
        - [5]: biomass
        - [6]: coal
        - [7]: oil
        - [8]: geothermal
        - [9]: waste incineration

    If none is given, the electricity mix corresponding to the country specified in `country` will be selected.
    If no country is specified, Europe applies.

    The `primary` and `secondary` fuel keys contain an array with shares of alternative fuel for each year, to create a custom blend.
    If none is provided, a blend provided by the Integrated Assessment model REMIND is used, which will depend on the REMIND energy scenario selected.

    Here is a list of available fuel pathways:


    Hydrogen technologies
    --------------------
    "electrolysis"
    "smr - natural gas"
    "smr - natural gas with CCS"
    "smr - biogas"
    "smr - biogas with CCS"
    "coal gasification"
    "wood gasification"
    "wood gasification with CCS"
    "wood gasification with EF"
    "wood gasification with EF with CCS"
    "atr - natural gas"
    "atr - natural gas with CCS"
    "atr - biogas"
    "atr - biogas with CCS"

    Natural gas technologies
    ------------------------
    cng
    biogas - sewage sludge
    biogas - biowaste
    syngas

    Diesel technologies
    -------------------
    diesel
    biodiesel - algae
    biodiesel - cooking oil
    synthetic diesel


    :ivar array: array from the CarModel class
    :vartype array: CarModel.array
    :ivar fuel_blend: a dictionary that contains fuel blend shares per type of fuel.
    :ivar scope: dictionary that contains filters for narrowing the analysis
    :ivar background_configuration: dictionary that contains choices for background system
    :ivar scenario: REMIND energy scenario to use ("SSP2-Baseline": business-as-usual,
                                                    "SSP2-PkBudg1100": limits cumulative GHG emissions to 1,100 gigatons by 2100,
                                                    "static": no forward-looking modification of the background inventories).
                    "SSP2-Baseline" selected by default.


    .. code-block:: python

    """

    def __init__(
        self,
        tm,
        scope=None,
        background_configuration=None,
        scenario="SSP2-Base",
        method="recipe",
        method_type="midpoint",
    ):

        if scope is None:
            scope = {"size": tm.array.coords["size"].values.tolist(),
                     "powertrain": tm.array.coords["powertrain"].values.tolist(),
                     "year": tm.array.coords["year"].values.tolist()}
        else:
            scope["size"] = scope.get("size", tm.array.coords["size"].values.tolist())
            scope["powertrain"] = scope.get(
                "powertrain", tm.array.coords["powertrain"].values.tolist()
            )
            scope["year"] = scope.get("year", tm.array.coords["year"].values.tolist())

        self.scope = scope
        self.scenario = scenario

        array = tm.array.sel(
            powertrain=self.scope["powertrain"],
            year=self.scope["year"],
            size=self.scope["size"],
        )

        self.compliant_vehicles = array.sel(parameter="total cargo mass") > 100

        self.array = array.stack(desired=["size", "powertrain", "year"])

        self.iterations = len(tm.array.value.values)

        self.number_of_cars = (
            len(self.scope["size"])
            * len(self.scope["powertrain"])
            * len(self.scope["year"])
        )

        self.array_inputs = {
            x: i for i, x in enumerate(list(self.array.parameter.values), 0)
        }
        self.array_powertrains = {
            x: i for i, x in enumerate(list(self.array.powertrain.values), 0)
        }

        self.background_configuration = background_configuration or {}

        if "energy storage" not in self.background_configuration:
            self.background_configuration["energy storage"] = {
                "electric": {"type": "NMC", "origin": "CN"}
            }
        else:
            if "electric" not in self.background_configuration["energy storage"]:
                self.background_configuration["energy storage"]["electric"] = {
                    "type": "NMC",
                    "origin": "CN",
                }
            else:
                if (
                    "origin"
                    not in self.background_configuration["energy storage"]["electric"]
                ):
                    self.background_configuration["energy storage"]["electric"][
                        "origin"
                    ] = "CN"
                if (
                    "type"
                    not in self.background_configuration["energy storage"]["electric"]
                ):
                    self.background_configuration["energy storage"]["electric"][
                        "type"
                    ] = "NMC"

        self.inputs = get_dict_input()
        self.bs = BackgroundSystemModel()
        self.country = tm.country
        self.add_additional_activities()
        self.rev_inputs = self.get_rev_dict_input()
        self.A = self.get_A_matrix()
        self.mix = self.define_electricity_mix_for_fuel_prep()

        self.fuel_blends = tm.fuel_blend
        self.create_fuel_markets()

        self.index_cng = [self.inputs[i] for i in self.inputs if "ICEV-g" in i[0]]
        self.index_combustion_wo_cng = [
            self.inputs[i]
            for i in self.inputs
            if any(ele in i[0] for ele in ["ICEV-d", "PHEV-d", "HEV-d"])
        ]
        self.index_diesel = [self.inputs[i] for i in self.inputs if "ICEV-d" in i[0]]
        self.index_all_diesel = [
            self.inputs[i]
            for i in self.inputs
            if any(ele in i[0] for ele in ["ICEV-d", "HEV-d", "PHEV-d"])
        ]

        self.index_hybrid = [
            self.inputs[i] for i in self.inputs if any(ele in i[0] for ele in ["HEV-d"])
        ]
        self.index_plugin_hybrid = [
            self.inputs[i] for i in self.inputs if "PHEV" in i[0]
        ]
        self.index_fuel_cell = [self.inputs[i] for i in self.inputs if "FCEV" in i[0]]

        self.map_non_fuel_emissions = {
            (
                "Methane, fossil",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Methane direct emissions, suburban",
            (
                "Methane, fossil",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Methane direct emissions, rural",
            (
                "Ammonia",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Ammonia direct emissions, suburban",
            (
                "NMVOC, non-methane volatile organic compounds, unspecified origin",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "NMVOC direct emissions, urban",
            (
                "Dinitrogen monoxide",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Dinitrogen oxide direct emissions, rural",
            (
                "Nitrogen oxides",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Nitrogen oxides direct emissions, urban",
            (
                "Ammonia",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Ammonia direct emissions, urban",
            (
                "Particulates, < 2.5 um",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Particulate matters direct emissions, suburban",
            (
                "Carbon monoxide, fossil",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Carbon monoxide direct emissions, urban",
            (
                "Nitrogen oxides",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Nitrogen oxides direct emissions, rural",
            (
                "NMVOC, non-methane volatile organic compounds, unspecified origin",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "NMVOC direct emissions, suburban",
            (
                "Benzene",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Benzene direct emissions, suburban",
            (
                "Ammonia",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Ammonia direct emissions, rural",
            (
                "NMVOC, non-methane volatile organic compounds, unspecified origin",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "NMVOC direct emissions, rural",
            (
                "Particulates, < 2.5 um",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Particulate matters direct emissions, urban",
            (
                "Dinitrogen monoxide",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Dinitrogen oxide direct emissions, suburban",
            (
                "Carbon monoxide, fossil",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Carbon monoxide direct emissions, rural",
            (
                "Methane, fossil",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Methane direct emissions, urban",
            (
                "Carbon monoxide, fossil",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Carbon monoxide direct emissions, suburban",
            (
                "Particulates, < 2.5 um",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Particulate matters direct emissions, rural",
            (
                "Benzene",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Benzene direct emissions, rural",
            (
                "Nitrogen oxides",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Nitrogen oxides direct emissions, suburban",
            (
                "Benzene",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Benzene direct emissions, urban",
            (
                "Dinitrogen monoxide",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Dinitrogen oxide direct emissions, urban",
            (
                "Nitrogen oxides",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Nitrogen dioxide direct emissions, urban",
            (
                "Nitrogen oxides",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Nitrogen dioxide direct emissions, suburban",
            (
                "Nitrogen oxides",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Nitrogen dioxide direct emissions, rural",
            (
                "Toluene",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Toluene direct emissions, urban",
            (
                "Toluene",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Toluene direct emissions, suburban",
            (
                "Toluene",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Toluene direct emissions, rural",
            (
                "Xylene",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Xylene direct emissions, urban",
            (
                "Xylene",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Xylene direct emissions, suburban",
            (
                "Xylene",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Xylene direct emissions, rural",
            (
                "Formaldehyde",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Formaldehyde direct emissions, urban",
            (
                "Formaldehyde",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Formaldehyde direct emissions, suburban",
            (
                "Formaldehyde",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Formaldehyde direct emissions, rural",
            (
                "Acetaldehyde",
                ("air", "urban air close to ground"),
                "kilogram",
            ): "Acetaldehyde direct emissions, urban",
            (
                "Acetaldehyde",
                ("air", "non-urban air or from high stacks"),
                "kilogram",
            ): "Acetaldehyde direct emissions, suburban",
            (
                "Acetaldehyde",
                ("air", "low population density, long-term"),
                "kilogram",
            ): "Acetaldehyde direct emissions, rural",
        }

        self.index_emissions = [
            self.inputs[i] for i in self.map_non_fuel_emissions.keys()
        ]

        self.map_noise_emissions = {
            (
                "noise, octave 1, day time, urban",
                ("octave 1", "day time", "urban"),
                "joule",
            ): "noise, octave 1, day time, urban",
            (
                "noise, octave 2, day time, urban",
                ("octave 2", "day time", "urban"),
                "joule",
            ): "noise, octave 2, day time, urban",
            (
                "noise, octave 3, day time, urban",
                ("octave 3", "day time", "urban"),
                "joule",
            ): "noise, octave 3, day time, urban",
            (
                "noise, octave 4, day time, urban",
                ("octave 4", "day time", "urban"),
                "joule",
            ): "noise, octave 4, day time, urban",
            (
                "noise, octave 5, day time, urban",
                ("octave 5", "day time", "urban"),
                "joule",
            ): "noise, octave 5, day time, urban",
            (
                "noise, octave 6, day time, urban",
                ("octave 6", "day time", "urban"),
                "joule",
            ): "noise, octave 6, day time, urban",
            (
                "noise, octave 7, day time, urban",
                ("octave 7", "day time", "urban"),
                "joule",
            ): "noise, octave 7, day time, urban",
            (
                "noise, octave 8, day time, urban",
                ("octave 8", "day time", "urban"),
                "joule",
            ): "noise, octave 8, day time, urban",
            (
                "noise, octave 1, day time, suburban",
                ("octave 1", "day time", "suburban"),
                "joule",
            ): "noise, octave 1, day time, suburban",
            (
                "noise, octave 2, day time, suburban",
                ("octave 2", "day time", "suburban"),
                "joule",
            ): "noise, octave 2, day time, suburban",
            (
                "noise, octave 3, day time, suburban",
                ("octave 3", "day time", "suburban"),
                "joule",
            ): "noise, octave 3, day time, suburban",
            (
                "noise, octave 4, day time, suburban",
                ("octave 4", "day time", "suburban"),
                "joule",
            ): "noise, octave 4, day time, suburban",
            (
                "noise, octave 5, day time, suburban",
                ("octave 5", "day time", "suburban"),
                "joule",
            ): "noise, octave 5, day time, suburban",
            (
                "noise, octave 6, day time, suburban",
                ("octave 6", "day time", "suburban"),
                "joule",
            ): "noise, octave 6, day time, suburban",
            (
                "noise, octave 7, day time, suburban",
                ("octave 7", "day time", "suburban"),
                "joule",
            ): "noise, octave 7, day time, suburban",
            (
                "noise, octave 8, day time, suburban",
                ("octave 8", "day time", "suburban"),
                "joule",
            ): "noise, octave 8, day time, suburban",
            (
                "noise, octave 1, day time, rural",
                ("octave 1", "day time", "rural"),
                "joule",
            ): "noise, octave 1, day time, rural",
            (
                "noise, octave 2, day time, rural",
                ("octave 2", "day time", "rural"),
                "joule",
            ): "noise, octave 2, day time, rural",
            (
                "noise, octave 3, day time, rural",
                ("octave 3", "day time", "rural"),
                "joule",
            ): "noise, octave 3, day time, rural",
            (
                "noise, octave 4, day time, rural",
                ("octave 4", "day time", "rural"),
                "joule",
            ): "noise, octave 4, day time, rural",
            (
                "noise, octave 5, day time, rural",
                ("octave 5", "day time", "rural"),
                "joule",
            ): "noise, octave 5, day time, rural",
            (
                "noise, octave 6, day time, rural",
                ("octave 6", "day time", "rural"),
                "joule",
            ): "noise, octave 6, day time, rural",
            (
                "noise, octave 7, day time, rural",
                ("octave 7", "day time", "rural"),
                "joule",
            ): "noise, octave 7, day time, rural",
            (
                "noise, octave 8, day time, rural",
                ("octave 8", "day time", "rural"),
                "joule",
            ): "noise, octave 8, day time, rural",
        }

        self.elec_map = {
            "Hydro": (
                "electricity production, hydro, run-of-river",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Nuclear": (
                "electricity production, nuclear, pressure water reactor",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Gas": (
                "electricity production, natural gas, conventional power plant",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Solar": (
                "electricity production, photovoltaic, 3kWp slanted-roof installation, multi-Si, panel, mounted",
                "DE",
                "kilowatt hour",
                "electricity, low voltage",
            ),
            "Wind": (
                "electricity production, wind, 1-3MW turbine, onshore",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Biomass": (
                "heat and power co-generation, wood chips, 6667 kW, state-of-the-art 2014",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Coal": (
                "electricity production, hard coal",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Oil": (
                "electricity production, oil",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Geo": (
                "electricity production, deep geothermal",
                "DE",
                "kilowatt hour",
                "electricity, high voltage",
            ),
            "Waste": (
                "treatment of municipal solid waste, incineration",
                "DE",
                "kilowatt hour",
                "electricity, for reuse in municipal waste incineration only",
            ),
        }

        self.index_noise = [self.inputs[i] for i in self.map_noise_emissions.keys()]

        self.list_cat, self.split_indices = self.get_split_indices()

        self.method = method

        if self.method == "recipe":
            self.method_type = method_type
        else:
            self.method_type = "midpoint"

        self.impact_categories = self.get_dict_impact_categories()

        # Load the B matrix
        self.B = self.get_B_matrix()

    def __getitem__(self, key):
        """
        Make class['foo'] automatically filter for the parameter 'foo'
        Makes the model code much cleaner

        :param key: Parameter name
        :type key: str
        :return: `array` filtered after the parameter selected
        """
        return self.temp_array.sel(parameter=key)

    def get_results_table(self, split, sensitivity=False):
        """
        Format an xarray.DataArray array to receive the results.

        :param sensitivity:
        :param split: "components" or "impact categories". Split by impact categories only applicable when "endpoint" level is applied.
        :return: xarrray.DataArray
        """

        if split == "components":
            cat = [
                "direct - exhaust",
                "direct - non-exhaust",
                "energy chain",
                "maintenance",
                "glider",
                "EoL",
                "powertrain",
                "energy storage",
                "road",
            ]

        dict_impact_cat = list(self.impact_categories.keys())

        if not sensitivity:

            response = xr.DataArray(
                np.zeros(
                    (
                        self.B.shape[1],
                        len(self.scope["size"]),
                        len(self.scope["powertrain"]),
                        len(self.scope["year"]),
                        len(cat),
                        self.iterations,
                    )
                ),
                coords=[
                    dict_impact_cat,
                    self.scope["size"],
                    self.scope["powertrain"],
                    self.scope["year"],
                    cat,
                    np.arange(0, self.iterations),
                ],
                dims=[
                    "impact_category",
                    "size",
                    "powertrain",
                    "year",
                    "impact",
                    "value",
                ],
            )

        else:
            params = [a for a in self.array.value.values]
            response = xr.DataArray(
                np.zeros(
                    (
                        self.B.shape[1],
                        len(self.scope["size"]),
                        len(self.scope["powertrain"]),
                        len(self.scope["year"]),
                        self.iterations,
                    )
                ),
                coords=[
                    dict_impact_cat,
                    self.scope["size"],
                    self.scope["powertrain"],
                    self.scope["year"],
                    params,
                ],
                dims=["impact_category", "size", "powertrain", "year", "parameter"],
            )

        return response

    def get_split_indices(self):
        """
        Return list of indices to split the results into categories.

        :return: list of indices
        :rtype: list
        """
        filename = "dict_split.csv"
        filepath = DATA_DIR / filename
        if not filepath.is_file():
            raise FileNotFoundError("The dictionary of splits could not be found.")

        with open(filepath) as f:
            csv_list = [[val.strip() for val in r.split(";")] for r in f.readlines()]
        (_, _, *header), *data = csv_list

        csv_dict = {}
        for row in data:
            key, sub_key, *values = row

            if key in csv_dict:
                if sub_key in csv_dict[key]:
                    csv_dict[key][sub_key].append(
                        {"search by": values[0], "search for": values[1]}
                    )
                else:
                    csv_dict[key][sub_key] = [
                        {"search by": values[0], "search for": values[1]}
                    ]
            else:
                csv_dict[key] = {
                    sub_key: [{"search by": values[0], "search for": values[1]}]
                }

        flatten = itertools.chain.from_iterable

        d = {}
        l = []

        d["direct - exhaust"] = []
        d["direct - exhaust"].append(
            self.inputs[("Carbon dioxide, fossil", ("air",), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[
                ("Carbon dioxide, from soil or biomass stock", ("air",), "kilogram")
            ]
        )
        d["direct - exhaust"].append(
            self.inputs[("Cadmium", ("air", "urban air close to ground"), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[("Copper", ("air", "urban air close to ground"), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[("Chromium", ("air", "urban air close to ground"), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[("Nickel", ("air", "urban air close to ground"), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[("Selenium", ("air", "urban air close to ground"), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[("Zinc", ("air", "urban air close to ground"), "kilogram")]
        )
        d["direct - exhaust"].append(
            self.inputs[
                ("Chromium VI", ("air", "urban air close to ground"), "kilogram")
            ]
        )
        d["direct - exhaust"].extend(self.index_emissions)
        d["direct - exhaust"].extend(self.index_noise)

        l.append(d["direct - exhaust"])

        for cat in csv_dict["components"]:
            d[cat] = list(
                flatten(
                    [
                        self.get_index_of_flows([l["search for"]], l["search by"])
                        for l in csv_dict["components"][cat]
                    ]
                )
            )
            l.append(d[cat])

        list_ind = [d[x] for x in d]
        maxLen = max(map(len, list_ind))
        for row in list_ind:
            while len(row) < maxLen:
                row.extend([len(self.inputs) - 1])
        return list(d.keys()), list_ind

    def calculate_impacts(self, split="components", sensitivity=False):

        # Prepare an array to store the results
        results = self.get_results_table(split, sensitivity=sensitivity)

        # Create electricity and fuel market datasets
        self.create_electricity_market_for_fuel_prep()

        # Create electricity market dataset for battery production
        self.create_electricity_market_for_battery_production()

        # Fill in the A matrix with car parameters
        self.set_inputs_in_A_matrix(self.array.values)
        self.A = np.nan_to_num(self.A)

        # Collect indices of activities contributing to the first level
        arr = self.A[0, : -self.number_of_cars, -self.number_of_cars :].sum(axis=1)
        ind = np.nonzero(arr)[0]

        new_arr = np.float32(
            np.zeros((self.A.shape[1], self.B.shape[1], len(self.scope["year"])))
        )

        f = np.float32(np.zeros((np.shape(self.A)[1])))

        for y in self.scope["year"]:
            if self.scenario != "static":
                B = self.B.interp(year=y, kwargs={"fill_value": "extrapolate"}).values
            else:
                B = self.B[0].values

            for a in ind:
                f[:] = 0
                f[a] = 1
                X = np.float32(sparse.linalg.spsolve(self.A[0], f.T))
                C = X * B
                new_arr[a, :, self.scope["year"].index(y)] = C.sum(axis=1)

        new_arr = new_arr.T.reshape(
            len(self.scope["year"]), B.shape[0], 1, 1, self.A.shape[-1]
        )

        a = np.float32(self.A[:, :, -self.number_of_cars :].transpose(0, 2, 1))

        arr = np.float32(ne.evaluate("a * new_arr * -1"))

        arr = arr.transpose(1, 3, 0, 4, 2)
        arr = arr[:, :, :, self.split_indices, :].sum(axis=4)

        if not sensitivity:
            for y in range(0, len(self.scope["year"])):
                results[:, :, :, y, :, :] = arr[
                    :, y :: len(self.scope["year"]), y, :, :
                ].reshape(
                    (
                        B.shape[0],
                        len(self.scope["size"]),
                        len(self.scope["powertrain"]),
                        len(results.impact.values),
                        self.iterations,
                    )
                )
        else:

            for y in range(0, len(self.scope["year"])):
                results[:, :, :, y, :] = (
                    arr[:, y :: len(self.scope["year"]), y, :]
                    .sum(axis=2)
                    .reshape(
                        (
                            B.shape[0],
                            len(self.scope["size"]),
                            len(self.scope["powertrain"]),
                            self.iterations,
                        )
                    )
                )
            results /= results.sel(parameter="reference")

        return results.astype("float32")*self.compliant_vehicles.values[:,:,:, None, :]

    def add_additional_activities(self):
        # Add as many rows and columns as cars to consider
        # Also add additional columns and rows for electricity markets
        # for fuel preparation and energy battery production

        maximum = max(self.inputs.values())

        for y in self.scope["year"]:

            if {"ICEV-d", "HEV-d", "PHEV-d"}.intersection(
                set(self.scope["powertrain"])
            ):
                maximum += 1
                self.inputs[
                    (
                        "fuel supply for diesel vehicles, " + str(y),
                        self.country,
                        "kilogram",
                        "fuel",
                    )
                ] = maximum

            if {"ICEV-g"}.intersection(set(self.scope["powertrain"])):
                maximum += 1
                self.inputs[
                    (
                        "fuel supply for gas vehicles, " + str(y),
                        self.country,
                        "kilogram",
                        "fuel",
                    )
                ] = maximum

            if {"FCEV"}.intersection(set(self.scope["powertrain"])):
                maximum += 1
                self.inputs[
                    (
                        "fuel supply for hydrogen vehicles, " + str(y),
                        self.country,
                        "kilogram",
                        "fuel",
                    )
                ] = maximum

            if {"BEV", "PHEV-d"}.intersection(set(self.scope["powertrain"])):
                maximum += 1
                self.inputs[
                    (
                        "electricity supply for electric vehicles, " + str(y),
                        self.country,
                        "kilowatt hour",
                        "electricity, low voltage, for battery electric vehicles",
                    )
                ] = maximum

            maximum += 1
            self.inputs[
                (
                    "electricity market for fuel preparation, " + str(y),
                    self.country,
                    "kilowatt hour",
                    "electricity, low voltage",
                )
            ] = maximum

            maximum += 1
            self.inputs[
                (
                    "electricity market for energy storage production, " + str(y),
                    self.background_configuration["energy storage"]["electric"][
                        "origin"
                    ],
                    "kilowatt hour",
                    "electricity, low voltage, for energy storage production",
                )
            ] = maximum

        for s in self.scope["size"]:
            for pt in self.scope["powertrain"]:
                for y in self.scope["year"]:
                    maximum += 1

                    if y < 1992:
                        euro_class = "EURO-0"
                    if 1992 <= y < 1995:
                        euro_class = "EURO-I"
                    if 1995 <= y < 1999:
                        euro_class = "EURO-II"
                    if 1999 <= y < 2005:
                        euro_class = "EURO-III"
                    if 2000 <= y < 2008:
                        euro_class = "EURO-IV"
                    if 2008 <= y < 2012:
                        euro_class = "EURO-V"
                    if y >= 2012:
                        euro_class = "EURO-VI"

                    if s in ("3.5t", "7.5t", "18t", "26t"):
                        name = (
                            "Medium duty truck, "
                            + pt
                            + ", "
                            + s
                            + " gross weight, "
                            + str(y)
                            + ", "
                            + euro_class
                        )

                    if s in ("40t", "60t"):
                        name = (
                            "Heavy duty truck, "
                            + pt
                            + ", "
                            + s
                            + " gross weight, "
                            + str(y)
                            + ", "
                            + euro_class
                        )

                    self.inputs[
                        (
                            name,
                            self.country,
                            "ton-kilometer",
                            "transport, freight, " + euro_class,
                        )
                    ] = maximum

    def get_A_matrix(self):
        """
        Load the A matrix. The A matrix contains exchanges of products (rows) between activities (columns).

        :return: A matrix with three dimensions of shape (number of values, number of products, number of activities).
        :rtype: numpy.ndarray

        """
        filename = "A_matrix.csv"
        filepath = (
            Path(getframeinfo(currentframe()).filename)
            .resolve()
            .parent.joinpath("data/" + filename)
        )
        if not filepath.is_file():
            raise FileNotFoundError("The technology matrix could not be found.")

        initial_A = np.genfromtxt(filepath, delimiter=";")

        new_A = np.identity(len(self.inputs))

        new_A[0 : np.shape(initial_A)[0], 0 : np.shape(initial_A)[0]] = initial_A

        # Resize the matrix to fit the number of iterations in `array`
        new_A = np.resize(new_A, (self.array.shape[1], new_A.shape[0], new_A.shape[1]))
        return new_A

    def get_B_matrix(self):
        """
        Load the B matrix. The B matrix contains impact assessment figures for a give impact assessment method,
        per unit of activity. Its length column-wise equals the length of the A matrix row-wise.
        Its length row-wise equals the number of impact assessment methods.

        :return: an array with impact values per unit of activity for each method.
        :rtype: numpy.ndarray

        """

        if self.method == "recipe":
            if self.method_type == "midpoint":
                list_file_names = glob.glob(
                    str(REMIND_FILES_DIR)
                    + "/*recipe_midpoint*{}*.csv".format(self.scenario)
                )
                B = np.zeros((len(list_file_names), 21, len(self.inputs)))
            else:
                list_file_names = glob.glob(
                    str(REMIND_FILES_DIR)
                    + "/*recipe_endpoint*{}*.csv".format(self.scenario)
                )
                B = np.zeros((len(list_file_names), 3, len(self.inputs)))

        else:
            list_file_names = glob.glob(
                str(REMIND_FILES_DIR) + "/*ilcd*{}*.csv".format(self.scenario)
            )
            B = np.zeros((len(list_file_names), 19, len(self.inputs)))

        for f in list_file_names:
            initial_B = np.genfromtxt(f, delimiter=";")

            new_B = np.zeros((np.shape(initial_B)[0], len(self.inputs),))

            new_B[0 : np.shape(initial_B)[0], 0 : np.shape(initial_B)[1]] = initial_B

            B[list_file_names.index(f), :, :] = new_B

        list_impact_categories = list(self.impact_categories.keys())

        if self.scenario != "static":
            response = xr.DataArray(
                B,
                coords=[
                    [2005, 2010, 2020, 2030, 2040, 2050],
                    list_impact_categories,
                    list(self.inputs.keys()),
                ],
                dims=["year", "category", "activity"],
            )
        else:
            response = xr.DataArray(
                B,
                coords=[[2020], list_impact_categories, list(self.inputs.keys()),],
                dims=["year", "category", "activity"],
            )

        return response

    def get_dict_impact_categories(self):
        """
        Load a dictionary with available impact assessment methods as keys, and assessment level and categories as values.

        ..code-block:: python

            {'recipe': {'midpoint': ['freshwater ecotoxicity',
                                   'human toxicity',
                                   'marine ecotoxicity',
                                   'terrestrial ecotoxicity',
                                   'metal depletion',
                                   'agricultural land occupation',
                                   'climate change',
                                   'fossil depletion',
                                   'freshwater eutrophication',
                                   'ionising radiation',
                                   'marine eutrophication',
                                   'natural land transformation',
                                   'ozone depletion',
                                   'particulate matter formation',
                                   'photochemical oxidant formation',
                                   'terrestrial acidification',
                                   'urban land occupation',
                                   'water depletion',
                                   'human noise',
                                   'primary energy, non-renewable',
                                   'primary energy, renewable']
                       }
           }

        :return: dictionary
        :rtype: dict
        """
        filename = "dict_impact_categories.csv"
        filepath = DATA_DIR / filename
        if not filepath.is_file():
            raise FileNotFoundError(
                "The dictionary of impact categories could not be found."
            )

        csv_dict = {}

        with open(filepath) as f:
            input_dict = csv.reader(f, delimiter=";")
            for row in input_dict:
                if row[0] == self.method and row[3] == self.method_type:
                    csv_dict[row[2]] = {
                        "method": row[1],
                        "category": row[2],
                        "type": row[3],
                        "abbreviation": row[4],
                        "unit": row[5],
                        "source": row[6],
                    }

        return csv_dict

    def get_rev_dict_input(self):
        """
        Reverse the self.inputs dictionary.

        :return: reversed dictionary
        :rtype: dict
        """
        return {v: k for k, v in self.inputs.items()}

    def get_index_vehicle_from_array(
        self, items_to_look_for, items_to_look_for_also=None, method="or"
    ):
        """
        Return list of row/column indices of self.array of labels that contain the string defined in `items_to_look_for`.

        :param items_to_look_for_also:
        :param method:
        :param items_to_look_for: string to search for
        :return: list
        """
        if not isinstance(items_to_look_for, list):
            items_to_look_for = [items_to_look_for]

        if not items_to_look_for_also is None:
            if not isinstance(items_to_look_for_also, list):
                items_to_look_for_also = [items_to_look_for_also]

        list_vehicles = self.array.desired.values.tolist()

        if method == "or":
            return [
                list_vehicles.index(c)
                for c in list_vehicles
                if set(items_to_look_for).intersection(c)
            ]

        if method == "and":
            return [
                list_vehicles.index(c)
                for c in list_vehicles
                if set(items_to_look_for).intersection(c)
                and set(items_to_look_for_also).intersection(c)
            ]

    def get_index_of_flows(self, items_to_look_for, search_by="name"):
        """
        Return list of row/column indices of self.A of labels that contain the string defined in `items_to_look_for`.

        :param items_to_look_for: string
        :param search_by: "name" or "compartment" (for elementary flows)
        :return: list of row/column indices
        :rtype: list
        """
        if search_by == "name":
            return [
                int(self.inputs[c])
                for c in self.inputs
                if all(ele in c[0].lower() for ele in items_to_look_for)
            ]
        if search_by == "compartment":
            return [
                int(self.inputs[c])
                for c in self.inputs
                if all(ele in c[1] for ele in items_to_look_for)
            ]

    def export_lci(
        self,
        presamples=True,
        ecoinvent_compatibility=True,
        ecoinvent_version="3.6",
        db_name="carculator db",
    ):
        """
        Export the inventory as a dictionary. Also return a list of arrays that contain pre-sampled random values if
        :param db_name:
        :meth:`stochastic` of :class:`CarModel` class has been called.

        :param presamples: boolean.
        :param ecoinvent_compatibility: bool. If True, compatible with ecoinvent. If False, compatible with REMIND-ecoinvent.
        :param ecoinvent_version: str. "3.5", "3.6" or "uvek"
        :return: inventory, and optionally, list of arrays containing pre-sampled values.
        :rtype: list
        """
        # Create electricity and fuel market datasets
        self.create_electricity_market_for_fuel_prep()

        # Create electricity market dataset for battery production
        self.create_electricity_market_for_battery_production()

        self.set_inputs_in_A_matrix(self.array.values)
        if presamples:
            lci, array = ExportInventory(
                self.A, self.rev_inputs, db_name=db_name
            ).write_lci(presamples, ecoinvent_compatibility, ecoinvent_version)
            return lci, array
        else:
            lci = ExportInventory(self.A, self.rev_inputs, db_name=db_name).write_lci(
                presamples, ecoinvent_compatibility, ecoinvent_version
            )
            return lci

    def export_lci_to_bw(
        self,
        presamples=True,
        ecoinvent_compatibility=True,
        ecoinvent_version="3.6",
        db_name="carculator db",
    ):
        """
        Export the inventory as a `brightway2` bw2io.importers.base_lci.LCIImporter object
        with the inventory in the `data` attribute.

        .. code-block:: python

            # get the inventory
            i, _ = ic.export_lci_to_bw()

            # import it in a Brightway2 project
            i.match_database('ecoinvent 3.6 cutoff', fields=('name', 'unit', 'location', 'reference product'))
            i.match_database("biosphere3", fields=('name', 'unit', 'categories'))
            i.match_database(fields=('name', 'unit', 'location', 'reference product'))
            i.match_database(fields=('name', 'unit', 'categories'))

            # Create an additional biosphere database for the few flows that do not
            # exist in "biosphere3"
            i.create_new_biosphere("additional_biosphere", relink=True)

            # Check if all exchanges link
            i.statistics()

            # Register the database
            i.write_database()

        :return: LCIImport object that can be directly registered in a `brightway2` project.
        :rtype: bw2io.importers.base_lci.LCIImporter
        """
        # Create electricity and fuel market datasets
        self.create_electricity_market_for_fuel_prep()

        # Create electricity market dataset for battery production
        self.create_electricity_market_for_battery_production()

        self.set_inputs_in_A_matrix(self.array.values)

        if presamples:
            lci, array = ExportInventory(
                self.A, self.rev_inputs, db_name=db_name
            ).write_lci_to_bw(presamples, ecoinvent_compatibility, ecoinvent_version)
            return lci, array
        else:
            lci = ExportInventory(
                self.A, self.rev_inputs, db_name=db_name
            ).write_lci_to_bw(presamples, ecoinvent_compatibility, ecoinvent_version)
            return lci

    def export_lci_to_excel(
        self,
        directory=None,
        ecoinvent_compatibility=True,
        ecoinvent_version="3.6",
        software_compatibility="brightway2",
        filename=None,
    ):
        """
        Export the inventory as an Excel file (if the destination software is Brightway2) or a CSV file (if the destination software is Simapro) file.
        Also return the file path where the file is stored.

        :param filename:
        :param directory: directory where to save the file.
        :type directory: str
        :param ecoinvent_compatibility: If True, compatible with ecoinvent. If False, compatible with REMIND-ecoinvent.
        :param ecoinvent_version: "3.6", "3.5" or "uvek"
        :param software_compatibility: "brightway2" or "simapro"
        :return: file path where the file is stored.
        :rtype: str
        """

        if software_compatibility not in ("brightway2", "simapro"):
            raise NameError(
                "The destination software argument is not valid. Choose between 'brightway2' or 'simapro'."
            )

        # Simapro inventory only for ecoinvent 3.5 or UVEK
        if software_compatibility == "simapro":
            if ecoinvent_version == "3.6":
                print(
                    "Simapro-compatible inventory export is only available for ecoinvent 3.5 or UVEK."
                )
                return
            ecoinvent_compatibility = True
            ecoinvent_version = "3.5"

        # Create electricity and fuel market datasets
        self.create_electricity_market_for_fuel_prep()

        # Create electricity market dataset for battery production
        self.create_electricity_market_for_battery_production()

        self.set_inputs_in_A_matrix(self.array.values)
        fp = ExportInventory(
            self.A, self.rev_inputs, db_name=filename or "carculator db"
        ).write_lci_to_excel(
            directory,
            ecoinvent_compatibility,
            ecoinvent_version,
            software_compatibility,
            filename,
        )
        return fp

    def define_electricity_mix_for_fuel_prep(self):
        """
        This function defines a fuel mix based either on user-defined mix, or on default mixes for a given country.
        The mix is calculated as the average mix, weighted by the distribution of annually driven kilometers.
        :return:
        """

        if "custom electricity mix" in self.background_configuration:
            # If a special electricity mix is specified, we use it
            if not np.allclose(
                np.sum(self.background_configuration["custom electricity mix"], axis=1),
                [1] * len(self.scope["year"])
                ):
                raise ValueError("The custom electricity mixes are not valid")

            mix = self.background_configuration["custom electricity mix"]
        else:
            use_year = [
                int(i)
                for i in (
                    self.array.values[
                        self.array_inputs["lifetime kilometers"],
                        :,
                        self.get_index_vehicle_from_array(
                            [
                                "BEV",
                                "FCEV",
                                "PHEV-p",
                                "PHEV-d",
                                "ICEV-p",
                                "ICEV-d",
                                "HEV-p",
                                "HEV-d",
                                "ICEV-g",
                            ]
                        ),
                    ]
                    / self.array.values[
                        self.array_inputs["kilometers per year"],
                        :,
                        self.get_index_vehicle_from_array(
                            [
                                "BEV",
                                "FCEV",
                                "PHEV-p",
                                "PHEV-d",
                                "ICEV-p",
                                "ICEV-d",
                                "HEV-p",
                                "HEV-d",
                                "ICEV-g",
                            ]
                        ),
                    ]
                )
                .mean(axis=1)
                .reshape(-1, len(self.scope["year"]))
                .mean(axis=0)
            ]

            if self.country not in self.bs.electricity_mix.country.values:
                print(
                    "The electricity mix for {} could not be found. Average European electricity mix is used instead.".format(
                        self.country
                    )
                )
                country = "RER"
            else:
                country = self.country

            mix = [
                self.bs.electricity_mix.sel(
                    country=country,
                    variable=[
                        "Hydro",
                        "Nuclear",
                        "Gas",
                        "Solar",
                        "Wind",
                        "Biomass",
                        "Coal",
                        "Oil",
                        "Geothermal",
                        "Waste",
                    ],
                )
                .interp(
                    year=np.arange(y, y + use_year[self.scope["year"].index(y)]),
                    kwargs={"fill_value": "extrapolate"},
                )
                .mean(axis=0)
                .values
                if y + use_year[self.scope["year"].index(y)] <= 2050
                else self.bs.electricity_mix.sel(
                    country=country,
                    variable=[
                        "Hydro",
                        "Nuclear",
                        "Gas",
                        "Solar",
                        "Wind",
                        "Biomass",
                        "Coal",
                        "Oil",
                        "Geothermal",
                        "Waste",
                    ],
                )
                .interp(year=np.arange(y, 2051), kwargs={"fill_value": "extrapolate"})
                .mean(axis=0)
                .values
                for y in self.scope["year"]
            ]

        return mix

    def define_renewable_rate_in_mix(self):

        try:
            losses_to_low = float(self.bs.losses[self.country]["LV"])
        except KeyError:
            # If losses for the country are not found, assume EU average
            losses_to_low = float(self.bs.losses["RER"]["LV"])

        category_name = (
                "climate change"
                if self.method == "recipe"
                else "climate change - climate change total"
            )

        co2_intensity_tech = (
                        self.B.sel(
                            category=category_name,
                            activity=list(self.elec_map.values()),
                        )
                        .interp(year=self.scope["year"], kwargs={"fill_value": "extrapolate"})
                        .values
                        * losses_to_low
                    ) * 1000

        sum_renew = [
            np.sum([self.mix[x][i] for i in [0, 3, 4, 5, 8]])
            for x in range(0, len(self.mix))
        ]

        return sum_renew, co2_intensity_tech

    def create_electricity_market_for_fuel_prep(self):
        """ This function fills the electricity market that supplies battery charging operations
        and hydrogen production through electrolysis.
        """

        try:
            losses_to_low = float(self.bs.losses[self.country]["LV"])
        except KeyError:
            # If losses for the country are not found, assume EU average
            losses_to_low = float(self.bs.losses["RER"]["LV"])

        # Fill the electricity markets for battery charging and hydrogen production
        for y in self.scope["year"]:
            m = np.array(self.mix[self.scope["year"].index(y)]).reshape(-1, 10, 1)
            # Add electricity technology shares
            self.A[
                np.ix_(
                    np.arange(self.iterations),
                    [self.inputs[self.elec_map[t]] for t in self.elec_map],
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0]
                        and "electricity market for fuel preparation" in i[0]
                    ],
                )
            ] = (m * -1 * losses_to_low)

            # Add transmission network for high and medium voltage
            self.A[
                :,
                self.inputs[
                    (
                        "transmission network construction, electricity, high voltage",
                        "CH",
                        "kilometer",
                        "transmission network, electricity, high voltage",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for fuel preparation" in i[0]
                ],
            ] = (6.58e-9 * -1 * losses_to_low)

            self.A[
                :,
                self.inputs[
                    (
                        "transmission network construction, electricity, medium voltage",
                        "CH",
                        "kilometer",
                        "transmission network, electricity, medium voltage",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for fuel preparation" in i[0]
                ],
            ] = (1.86e-8 * -1 * losses_to_low)

            self.A[
                :,
                self.inputs[
                    (
                        "transmission network construction, long-distance",
                        "UCTE",
                        "kilometer",
                        "transmission network, long-distance",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for fuel preparation" in i[0]
                ],
            ] = (3.17e-10 * -1 * losses_to_low)

            # Add distribution network, low voltage
            self.A[
                :,
                self.inputs[
                    (
                        "distribution network construction, electricity, low voltage",
                        "CH",
                        "kilometer",
                        "distribution network, electricity, low voltage",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for fuel preparation" in i[0]
                ],
            ] = (8.74e-8 * -1 * losses_to_low)

            # Add supply of sulfur hexafluoride for transformers
            self.A[
                :,
                self.inputs[
                    (
                        "market for sulfur hexafluoride, liquid",
                        "RER",
                        "kilogram",
                        "sulfur hexafluoride, liquid",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for fuel preparation" in i[0]
                ],
            ] = ((5.4e-8 + 2.99e-9) * -1 * losses_to_low)

            # Add SF_6 leakage

            self.A[
                :,
                self.inputs[("Sulfur hexafluoride", ("air",), "kilogram")],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for fuel preparation" in i[0]
                ],
            ] = ((5.4e-8 + 2.99e-9) * -1 * losses_to_low)

    def create_electricity_market_for_battery_production(self):
        """
        This funciton fills in the dataset that contains the electricity mix used for manufacturing battery cells
        :return:
        """

        battery_tech = self.background_configuration["energy storage"]["electric"][
            "type"
        ]
        battery_origin = self.background_configuration["energy storage"]["electric"][
            "origin"
        ]

        try:
            losses_to_low = float(self.bs.losses[battery_origin]["LV"])
        except KeyError:
            losses_to_low = float(self.bs.losses["CN"]["LV"])

        mix_battery_manufacturing = (
            self.bs.electricity_mix.sel(
                country=battery_origin,
                variable=[
                    "Hydro",
                    "Nuclear",
                    "Gas",
                    "Solar",
                    "Wind",
                    "Biomass",
                    "Coal",
                    "Oil",
                    "Geothermal",
                    "Waste",
                ],
            )
            .interp(year=self.scope["year"], kwargs={"fill_value": "extrapolate"})
            .values
        )

        # Fill the electricity markets for battery production
        for y in self.scope["year"]:
            m = np.array(
                mix_battery_manufacturing[self.scope["year"].index(y)]
            ).reshape(-1, 10, 1)

            self.A[
                np.ix_(
                    np.arange(self.iterations),
                    [self.inputs[self.elec_map[t]] for t in self.elec_map],
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0]
                        and "electricity market for energy storage production" in i[0]
                    ],
                )
            ] = (m * losses_to_low * -1)

            # Add transmission network for high and medium voltage
            self.A[
                :,
                self.inputs[
                    (
                        "transmission network construction, electricity, high voltage",
                        "CH",
                        "kilometer",
                        "transmission network, electricity, high voltage",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for energy storage production" in i[0]
                ],
            ] = (6.58e-9 * -1 * losses_to_low)

            self.A[
                :,
                self.inputs[
                    (
                        "transmission network construction, electricity, medium voltage",
                        "CH",
                        "kilometer",
                        "transmission network, electricity, medium voltage",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for energy storage production" in i[0]
                ],
            ] = (1.86e-8 * -1 * losses_to_low)

            self.A[
                :,
                self.inputs[
                    (
                        "transmission network construction, long-distance",
                        "UCTE",
                        "kilometer",
                        "transmission network, long-distance",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for energy storage production" in i[0]
                ],
            ] = (3.17e-10 * -1 * losses_to_low)

            # Add distribution network, low voltage
            self.A[
                :,
                self.inputs[
                    (
                        "distribution network construction, electricity, low voltage",
                        "CH",
                        "kilometer",
                        "distribution network, electricity, low voltage",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for energy storage production" in i[0]
                ],
            ] = (8.74e-8 * -1 * losses_to_low)

            # Add supply of sulfur hexafluoride for transformers
            self.A[
                :,
                self.inputs[
                    (
                        "market for sulfur hexafluoride, liquid",
                        "RER",
                        "kilogram",
                        "sulfur hexafluoride, liquid",
                    )
                ],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for energy storage production" in i[0]
                ],
            ] = ((5.4e-8 + 2.99e-9) * -1 * losses_to_low)

            # Add SF_6 leakage

            self.A[
                :,
                self.inputs[("Sulfur hexafluoride", ("air",), "kilogram")],
                [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "electricity market for energy storage production" in i[0]
                ],
            ] = ((5.4e-8 + 2.99e-9) * -1 * losses_to_low)

    def create_fuel_markets(self):
        """
        This function creates markets for fuel, considering a given blend, a given fuel type and a given year
        :return:
        """

        d_fuels = {
            "electrolysis": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from electrolysis, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 58,
            },
            "smr - natural gas": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from SMR of NG, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "smr - natural gas with CCS": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from SMR of NG, with CCS, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "smr - biogas": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from SMR of biogas, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "smr - biogas with CCS": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from SMR of biogas with CCS, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "coal gasification": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from coal gasification, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "wood gasification": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from dual fluidised bed gasification of woody biomass, at H2 fuelling station",
                    "CH",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "wood gasification with CCS": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from dual fluidised bed gasification of woody biomass with CCS, at H2 fuelling station",
                    "CH",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "wood gasification with EF": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from gasification of woody biomass in oxy-fired entrained flow gasifier, at fuelling station",
                    "CH",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "wood gasification with EF with CCS": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from gasification of woody biomass in oxy-fired entrained flow gasifier, with CCS, at fuelling station",
                    "CH",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "atr - natural gas": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, ATR of NG, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "atr - natural gas with CCS": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, ATR of NG, with CCS, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "atr - biogas": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from ATR of biogas, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "atr - biogas with CCS": {
                "name": (
                    "Hydrogen, gaseous, 700 bar, from ATR of biogas with CCS, at H2 fuelling station",
                    "RER",
                    "kilogram",
                    "Hydrogen, gaseous, 700 bar",
                ),
                "additional electricity": 0,
            },
            "cng": {
                "name": (
                    "market for natural gas, from high pressure network (1-5 bar), at service station",
                    "GLO",
                    "kilogram",
                    "natural gas, from high pressure network (1-5 bar), at service station",
                ),
                "additional electricity": 0,
            },
            "biogas - sewage sludge": {
                "name": (
                    "biogas upgrading - sewage sludge - amine scrubbing - best",
                    "CH",
                    "kilogram",
                    "biogas upgrading - sewage sludge - amine scrubbing - best",
                ),
                "additional electricity": 0,
            },
            "biogas - biowaste": {
                "name": (
                    "biomethane from biogas upgrading - biowaste - amine scrubbing",
                    "CH",
                    "kilogram",
                    "biomethane",
                ),
                "additional electricity": 0,
            },
            "syngas": {
                "name": (
                    "Methane production, synthetic, from electrochemical methanation",
                    "RER",
                    "kilogram",
                    "Methane, synthetic",
                ),
                "additional electricity": 58 * 0.50779661,
            },
            "lpg": {
                "name": ('market for liquefied petroleum gas',
                          'Europe without Switzerland',
                          'kilogram',
                          'liquefied petroleum gas'),
                "additional electricity": 0,
            },
            "diesel": {
                "name": (
                    "market for diesel",
                    "Europe without Switzerland",
                    "kilogram",
                    "diesel",
                ),
                "additional electricity": 0,
            },
            "biodiesel - algae": {
                "name": (
                    "Biodiesel from algae",
                    "RER",
                    "kilogram",
                    "Biodiesel from algae",
                ),
                "additional electricity": 0,
            },
            "biodiesel - cooking oil": {
                "name": (
                    "Biodiesel from cooking oil",
                    "RER",
                    "kilogram",
                    "Biodiesel from cooking oil",
                ),
                "additional electricity": 0,
            },
            "synthetic diesel": {
                "name": (
                    "Diesel production, synthetic, Fischer Tropsch process",
                    "RER",
                    "kilogram",
                    "Diesel, synthetic",
                ),
                "additional electricity": 58 * 0.2875,
            },
        }

        d_dataset_name = {
            "diesel": "fuel supply for diesel vehicles, ",
            "cng": "fuel supply for gas vehicles, ",
            "hydrogen": "fuel supply for hydrogen vehicles, ",
            "electricity": "electricity supply for electric vehicles, ",
        }

        d_map_fuel_pt = {
            "diesel": ["ICEV-d", "HEV-d", "PHEV-d"],
            "cng": ["ICEV-g"],
            "hydrogen": ["FCEV"],
        }

        for fuel_type in self.fuel_blends:

            if any(
                {x}.intersection(set(self.scope["powertrain"]))
                for x in d_map_fuel_pt[fuel_type]
            ):

                primary = self.fuel_blends[fuel_type]["primary"]["type"]
                secondary = self.fuel_blends[fuel_type]["secondary"]["type"]
                primary_share = self.fuel_blends[fuel_type]["primary"]["share"]
                secondary_share = self.fuel_blends[fuel_type]["secondary"]["share"]

                for y in self.scope["year"]:
                    dataset_name = d_dataset_name[fuel_type] + str(y)
                    fuel_market_index = [
                        self.inputs[i] for i in self.inputs if i[0] == dataset_name
                    ][0]
                    primary_fuel_activity_index = self.inputs[d_fuels[primary]["name"]]
                    secondary_fuel_activity_index = self.inputs[
                        d_fuels[secondary]["name"]
                    ]
                    self.A[:, primary_fuel_activity_index, fuel_market_index] = (
                        -1 * primary_share[self.scope["year"].index(y)]
                    )
                    self.A[:, secondary_fuel_activity_index, fuel_market_index] = (
                        -1 * secondary_share[self.scope["year"].index(y)]
                    )

                    additional_electricity = (
                        d_fuels[primary]["additional electricity"]
                        * primary_share[self.scope["year"].index(y)]
                    ) + (
                        d_fuels[secondary]["additional electricity"]
                        * secondary_share[self.scope["year"].index(y)]
                    )

                    if additional_electricity > 0:
                        electricity_mix_index = [
                            self.inputs[i]
                            for i in self.inputs
                            if i[0]
                            == "electricity market for fuel preparation, " + str(y)
                        ][0]
                        self.A[:, electricity_mix_index, fuel_market_index] = (
                            -1 * additional_electricity
                        )
        if any(pt in self.scope["powertrain"] for pt in ["BEV", "PHEV-d"]):
            fuel_type = "electricity"
            for y in self.scope["year"]:
                dataset_name = d_dataset_name[fuel_type] + str(y)
                electricity_market_index = [
                    self.inputs[i] for i in self.inputs if i[0] == dataset_name
                ][0]
                electricity_mix_index = [
                    self.inputs[i]
                    for i in self.inputs
                    if i[0] == "electricity market for fuel preparation, " + str(y)
                ][0]
                self.A[:, electricity_mix_index, electricity_market_index] = -1

    def set_inputs_in_A_matrix(self, array):
        """
        Fill-in the A matrix. Does not return anything. Modifies in place.
        Shape of the A matrix (values, products, activities).

        :param array: :attr:`array` from :class:`CarModel` class
        """

        # Glider/Frame
        self.A[
            :,
            self.inputs[
                (
                    "frame, blanks and saddle, for lorry",
                    "RER",
                    "kilogram",
                    "frame, blanks and saddle, for lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["glider base mass"], :])
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Suspension + Brakes
        self.A[
            :,
            self.inputs[
                ("suspension, for lorry", "RER", "kilogram", "suspension, for lorry")
            ],
            -self.number_of_cars :,
        ] = (
            (
                array[
                    [
                        self.array_inputs["suspension mass"],
                        self.array_inputs["braking system mass"],
                    ],
                    :,
                ].sum(axis=0)
            )
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Wheels and tires
        self.A[
            :,
            self.inputs[
                (
                    "tires and wheels, for lorry",
                    "RER",
                    "kilogram",
                    "tires and wheels, for lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["wheels and tires mass"], :])
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Cabin
        self.A[
            :,
            self.inputs[("cabin, for lorry", "RER", "kilogram", "cabin, for lorry")],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["cabin mass"], :])
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Exhaust
        self.A[
            :,
            self.inputs[
                (
                    "exhaust system, for lorry",
                    "RER",
                    "kilogram",
                    "exhaust system, for lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["exhaust system mass"], :])
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Electrical system
        self.A[
            :,
            self.inputs[
                (
                    "power electronics, for lorry",
                    "RER",
                    "kilogram",
                    "power electronics, for lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["electrical system mass"], :])
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Transmission (52% transmission shaft, 36% gearbox + 12% retarder)
        self.A[
            :,
            self.inputs[
                (
                    "transmission, for lorry",
                    "RER",
                    "kilogram",
                    "transmission, for lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["transmission mass"], :] * 0.52)
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )
        self.A[
            :,
            self.inputs[
                ("gearbox, for lorry", "RER", "kilogram", "gearbox, for lorry")
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["transmission mass"], :] * 0.36)
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )
        self.A[
            :,
            self.inputs[
                ("retarder, for lorry", "RER", "kilogram", "retarder, for lorry")
            ],
            -self.number_of_cars :,
        ] = (
            (array[self.array_inputs["transmission mass"], :] * 0.12)
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Other components, for non-electric and hybrid trucks
        index = self.get_index_vehicle_from_array(
            ["ICEV-d", "PHEV-d", "HEV-d", "ICEV-g"]
        )
        ind_A = [
            self.inputs[i]
            for i in self.inputs
            if "duty" in i[0]
            and any(x in i[0] for x in ["ICEV-d", "PHEV-d", "HEV-d", "ICEV-g"])
        ]
        self.A[
            :,
            self.inputs[
                (
                    "other components, for hybrid electric lorry",
                    "RER",
                    "kilogram",
                    "other components, for hybrid electric lorry",
                )
            ],
            ind_A,
        ] = (
            array[self.array_inputs["other components mass"], :, index]
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        # Other components, for electric trucks
        index = self.get_index_vehicle_from_array(["BEV", "FCEV"])
        ind_A = [
            self.inputs[i]
            for i in self.inputs
            if "duty" in i[0] and any(x in i[0] for x in ["BEV", "FCEV"])
        ]
        self.A[
            :,
            self.inputs[
                (
                    "other components, for electric lorry",
                    "RER",
                    "kilogram",
                    "other components, for electric lorry",
                )
            ],
            ind_A,
        ] = (
            array[self.array_inputs["other components mass"], :, index]
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        self.A[
            :,
            self.inputs[
                ("Glider lightweighting", "GLO", "kilogram", "Glider lightweighting")
            ],
            -self.number_of_cars :,
        ] = (
            (
                array[self.array_inputs["lightweighting"], :]
                * array[self.array_inputs["glider base mass"], :]
            )
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        index_16t = [
            self.inputs[i]
            for i in self.inputs
            if any(x in i[0] for x in ("3.5t", "7.5t", "18t"))
        ]
        index_arr_16t = self.get_index_vehicle_from_array(["3.5t", "7.5t", "18t"])
        index_28t = [self.inputs[i] for i in self.inputs if "26t" in i[0]]
        index_arr_28t = self.get_index_vehicle_from_array("26t")

        index_40t = [
            self.inputs[i]
            for i in self.inputs
            if any(x in i[0] for x in ("40t", "60t"))
        ]
        index_arr_40t = self.get_index_vehicle_from_array(["40t", "60t"])

        self.A[
            :,
            self.inputs[
                (
                    "maintenance, lorry 16 metric ton",
                    "CH",
                    "unit",
                    "maintenance, lorry 16 metric ton",
                )
            ],
            index_16t,
        ] = (
            (
                1
                / array[self.array_inputs["lifetime kilometers"], :, index_arr_16t]
                / (
                    array[self.array_inputs["total cargo mass"], :, index_arr_16t]
                    / 1000
                )
            ).T
            * -1
        )

        self.A[
            :,
            self.inputs[
                (
                    "maintenance, lorry 28 metric ton",
                    "CH",
                    "unit",
                    "maintenance, lorry 28 metric ton",
                )
            ],
            index_28t,
        ] = (
            (
                1
                / array[self.array_inputs["lifetime kilometers"], :, index_arr_28t]
                / (
                    array[self.array_inputs["total cargo mass"], :, index_arr_28t]
                    / 1000
                )
            ).T
            * -1
        )

        self.A[
            :,
            self.inputs[
                (
                    "maintenance, lorry 40 metric ton",
                    "CH",
                    "unit",
                    "maintenance, lorry 40 metric ton",
                )
            ],
            index_40t,
        ] = (
            (
                1
                / array[self.array_inputs["lifetime kilometers"], :, index_arr_40t]
                / (
                    array[self.array_inputs["total cargo mass"], :, index_arr_40t]
                    / 1000
                )
            ).T
            * -1
        )

        # Powertrain components
        self.A[
            :,
            self.inputs[
                (
                    "market for charger, electric passenger car",
                    "GLO",
                    "kilogram",
                    "charger, electric passenger car",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["charger mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[
                (
                    "market for converter, for electric passenger car",
                    "GLO",
                    "kilogram",
                    "converter, for electric passenger car",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["converter mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[
                (
                    "market for electric motor, electric passenger car",
                    "GLO",
                    "kilogram",
                    "electric motor, electric passenger car",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["electric engine mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[
                (
                    "market for inverter, for electric passenger car",
                    "GLO",
                    "kilogram",
                    "inverter, for electric passenger car",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["inverter mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[
                (
                    "market for power distribution unit, for electric passenger car",
                    "GLO",
                    "kilogram",
                    "power distribution unit, for electric passenger car",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["power distribution unit mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        l_elec_pt = [
            "charger mass",
            "converter mass",
            "inverter mass",
            "power distribution unit mass",
            "electric engine mass",
            "fuel cell stack mass",
            "fuel cell ancillary BoP mass",
            "fuel cell essential BoP mass",
            "battery cell mass",
            "battery BoP mass",
        ]

        # self.A[
        #     :,
        #     self.inputs[
        #         (
        #             "market for used powertrain from electric passenger car, manual dismantling",
        #             "GLO",
        #             "kilogram",
        #             "used powertrain from electric passenger car, manual dismantling",
        #         )
        #     ],
        #     -self.number_of_cars :,
        # ] = (
        #     array[[self.array_inputs[l] for l in l_elec_pt], :].sum(axis=0)
        #     / array[self.array_inputs["lifetime kilometers"], :]
        #     / (array[self.array_inputs["total cargo mass"], :] / 1000)
        # )

        self.A[
            :,
            self.inputs[
                (
                    "internal combustion engine, for lorry",
                    "RER",
                    "kilogram",
                    "internal combustion engine, for lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            (
                array[
                    [self.array_inputs[l] for l in ["combustion engine mass"]], :,
                ].sum(axis=0)
            )
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[("Ancillary BoP", "GLO", "kilogram", "Ancillary BoP")],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["fuel cell ancillary BoP mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[("Essential BoP", "GLO", "kilogram", "Essential BoP")],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["fuel cell essential BoP mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        self.A[
            :,
            self.inputs[("Stack", "GLO", "kilowatt", "Stack")],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["fuel cell stack mass"], :]
            / array[self.array_inputs["lifetime kilometers"], :]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        )

        # Start of printout

        print(
            "****************** IMPORTANT BACKGROUND PARAMETERS ******************",
            end="\n * ",
        )

        # Energy storage for electric trucks

        print(
            "The country of use is " + self.country, end="\n * ",
        )

        battery_tech = self.background_configuration["energy storage"]["electric"][
            "type"
        ]
        battery_origin = self.background_configuration["energy storage"]["electric"][
            "origin"
        ]

        print(
            "Energy batteries produced in "
            + battery_origin
            + " using "
            + battery_tech
            + " chemistry.",
            end="\n * ",
        )

        # Use the NMC inventory of Schmidt et al. 2019 for electric and hybrid trucks
        index = self.get_index_vehicle_from_array(["BEV", "FCEV", "PHEV-d", "HEV-d"])
        ind_A = [
            self.inputs[i]
            for i in self.inputs
            if "duty" in i[0]
            and any(x in i[0] for x in ["BEV", "FCEV", "PHEV-d", "HEV-d"])
        ]

        self.A[
            :, self.inputs[("Battery BoP", "GLO", "kilogram", "Battery BoP")], ind_A
        ] = (
            (
                array[self.array_inputs["battery BoP mass"], :, index]
                * (
                    1
                    + array[
                        self.array_inputs["battery lifetime replacements"], :, index
                    ]
                )
            )
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        battery_cell_label = (
            "Battery cell, " + battery_tech,
            "GLO",
            "kilogram",
            "Battery cell",
        )

        self.A[:, self.inputs[battery_cell_label], ind_A] = (
            (
                array[self.array_inputs["battery cell mass"], :, index]
                * (
                    1
                    + array[
                        self.array_inputs["fuel cell lifetime replacements"], :, index
                    ]
                )
            )
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        # Set an input of electricity, given the country of manufacture
        self.A[
            :,
            self.inputs[
                (
                    "market group for electricity, medium voltage",
                    "World",
                    "kilowatt hour",
                    "electricity, medium voltage",
                )
            ],
            self.inputs[battery_cell_label],
        ] = 0

        for y in self.scope["year"]:
            index = self.get_index_vehicle_from_array(y)

            self.A[
                np.ix_(
                    np.arange(self.iterations),
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0]
                        and "electricity market for energy storage production" in i[0]
                    ],
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0] and "duty" in i[0]
                    ],
                )
            ] = (
                array[
                    self.array_inputs["battery cell production electricity"], :, index
                ].T
                * self.A[
                    :,
                    self.inputs[battery_cell_label],
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0] and "duty" in i[0]
                    ],
                ]
            ).reshape(
                self.iterations, 1, -1
            )

        # Use the inventory of Wolff et al. 2020 for lead acid battery for non-electric and non-hybrid trucks

        ind_A = [
            self.inputs[i]
            for i in self.inputs
            if "duty" in i[0] and any(x in i[0] for x in ["ICEV-d", "ICEV-g"])
        ]
        index = self.get_index_vehicle_from_array(["ICEV-d", "ICEV-g"])

        self.A[
            :,
            self.inputs[
                (
                    "lead acid battery, for lorry",
                    "RER",
                    "kilogram",
                    "lead acid battery, for lorry",
                )
            ],
            ind_A,
        ] = (
            (
                array[self.array_inputs["battery BoP mass"], :, index]
                * (
                    1
                    + array[
                        self.array_inputs["battery lifetime replacements"], :, index
                    ]
                )
            )
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        self.A[
            :,
            self.inputs[
                (
                    "lead acid battery, for lorry",
                    "RER",
                    "kilogram",
                    "lead acid battery, for lorry",
                )
            ],
            ind_A,
        ] += (
            (
                array[self.array_inputs["battery cell mass"], :, index]
                * (
                    1
                    + array[
                        self.array_inputs["battery lifetime replacements"], :, index
                    ]
                )
            )
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        # Fuel tank for diesel trucks
        index_A = [
            self.inputs[c]
            for c in self.inputs
            if any(ele in c[0] for ele in ["ICEV-d", "PHEV-d", "HEV-d"])
        ]
        index = self.get_index_vehicle_from_array(["ICEV-d", "PHEV-d", "HEV-d"])

        self.A[
            :,
            self.inputs[
                ("fuel tank, for diesel vehicle", "RER", "kilogram", "fuel tank")
            ],
            index_A,
        ] = (
            array[self.array_inputs["fuel tank mass"], :, index]
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        index = self.get_index_vehicle_from_array("ICEV-g")
        self.A[
            :,
            self.inputs[
                (
                    "glass fibre reinforced plastic production, polyamide, injection moulded",
                    "RER",
                    "kilogram",
                    "glass fibre reinforced plastic, polyamide, injection moulded",
                )
            ],
            self.index_cng,
        ] = (
            array[self.array_inputs["fuel tank mass"], :, index]
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        if "hydrogen" in self.background_configuration["energy storage"]:
            # If a customization dict is passed
            hydro_tank_technology = self.background_configuration["energy storage"][
                "hydrogen"
            ]["type"]
        else:
            hydro_tank_technology = "carbon fiber"

        dict_tank_map = {
            "carbon fiber": (
                "Fuel tank, compressed hydrogen gas, 700bar",
                "GLO",
                "kilogram",
                "Fuel tank, compressed hydrogen gas, 700bar",
            ),
            "hdpe": (
                "Fuel tank, compressed hydrogen gas, 700bar, with HDPE liner",
                "RER",
                "kilogram",
                "Hydrogen tank",
            ),
            "aluminium": (
                "Fuel tank, compressed hydrogen gas, 700bar, with aluminium liner",
                "RER",
                "kilogram",
                "Hydrogen tank",
            ),
        }

        index = self.get_index_vehicle_from_array("FCEV")
        self.A[
            :, self.inputs[dict_tank_map[hydro_tank_technology]], self.index_fuel_cell,
        ] = (
            array[self.array_inputs["fuel tank mass"], :, index]
            / array[self.array_inputs["lifetime kilometers"], :, index]
            / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
            * -1
        ).T

        sum_renew, co2_intensity_tech = self.define_renewable_rate_in_mix()

        for y in self.scope["year"]:

            if self.scope["year"].index(y) + 1 == len(self.scope["year"]):
                end_str = "\n * "
            else:
                end_str = "\n \t * "

            print(
                "in "
                + str(y)
                + ", % of renewable: "
                + str(np.round(sum_renew[self.scope["year"].index(y)] * 100, 0))
                + "%"
                + ", GHG intensity per kWh: "
                + str(
                    int(
                        np.sum(
                            co2_intensity_tech[self.scope["year"].index(y)] * self.mix[self.scope["year"].index(y)]
                        )
                    )
                )
                + " g. CO2-eq.",
                end=end_str,
            )

        if any(True for x in ["BEV", "PHEV-d"] if x in self.scope["powertrain"]):
            for y in self.scope["year"]:
                index = self.get_index_vehicle_from_array(
                    ["BEV", "PHEV-d"], y, method="and"
                )

                self.A[
                    np.ix_(
                        np.arange(self.iterations),
                        [
                            self.inputs[i]
                            for i in self.inputs
                            if str(y) in i[0]
                            and "electricity supply for electric vehicles" in i[0]
                        ],
                        [
                            self.inputs[i]
                            for i in self.inputs
                            if str(y) in i[0]
                            and "duty" in i[0]
                            and any(True for x in ["BEV", "PHEV-d"] if x in i[0])
                        ],
                    )
                ] = (
                    array[self.array_inputs["electricity consumption"], :, index]
                    / (array[self.array_inputs["total cargo mass"], :, index] / 1000)
                    * -1
                ).T.reshape(
                    self.iterations, 1, -1
                )

        if "FCEV" in self.scope["powertrain"]:

            index = self.get_index_vehicle_from_array("FCEV")

            print(
                "{} is completed by {}.".format(
                    self.fuel_blends["hydrogen"]["primary"]["type"],
                    self.fuel_blends["hydrogen"]["secondary"]["type"],
                ),
                end="\n \t * ",
            )
            for y in self.scope["year"]:
                if self.scope["year"].index(y) + 1 == len(self.scope["year"]):
                    end_str = "\n * "
                else:
                    end_str = "\n \t * "
                print(
                    "in "
                    + str(y)
                    + " _________________________________________ "
                    + str(
                        np.round(
                            self.fuel_blends["hydrogen"]["secondary"]["share"][
                                self.scope["year"].index(y)
                            ]
                            * 100,
                            0,
                        )
                    )
                    + "%",
                    end=end_str,
                )

            # Primary fuel share
            for y in self.scope["year"]:
                ind_A = [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0] and "duty" in i[0] and "FCEV" in i[0]
                ]
                ind_array = [
                    x for x in self.get_index_vehicle_from_array(y) if x in index
                ]

                self.A[
                    :,
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0]
                        and "fuel supply for hydrogen vehicles" in i[0]
                    ],
                    ind_A,
                ] = (
                    array[self.array_inputs["fuel mass"], :, ind_array]
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

        if "ICEV-g" in self.scope["powertrain"]:
            index = self.get_index_vehicle_from_array("ICEV-g")

            print(
                "{} is completed by {}.".format(
                    self.fuel_blends["cng"]["primary"]["type"],
                    self.fuel_blends["cng"]["secondary"]["type"],
                ),
                end="\n \t * ",
            )

            for y in self.scope["year"]:
                if self.scope["year"].index(y) + 1 == len(self.scope["year"]):
                    end_str = "\n * "
                else:
                    end_str = "\n \t * "
                print(
                    "in "
                    + str(y)
                    + " _________________________________________ "
                    + str(
                        np.round(
                            self.fuel_blends["cng"]["secondary"]["share"][
                                self.scope["year"].index(y)
                            ]
                            * 100,
                            0,
                        )
                    )
                    + "%",
                    end=end_str,
                )

            # Primary fuel share
            for y in self.scope["year"]:
                ind_A = [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0] and "duty" in i[0] and "ICEV-g" in i[0]
                ]
                ind_array = [
                    x for x in self.get_index_vehicle_from_array(y) if x in index
                ]

                # Includes pump-to-tank gas leakage, as a fraction of gas input
                self.A[
                    :,
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0] and "fuel supply for gas vehicles" in i[0]
                    ],
                    ind_A,
                ] = (
                    (array[self.array_inputs["fuel mass"], :, ind_array])
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    ) *
                    (1 + array[self.array_inputs["CNG pump-to-tank leakage"], :, ind_array])
                    * -1
                ).T

                # Fuel-based emissions from CNG, CO2
                # The share and CO2 emissions factor of CNG is retrieved, if used

                share_fossil = 0
                CO2_fossil = 0

                if self.fuel_blends["cng"]["primary"]["type"] == "cng":
                    share_fossil += self.fuel_blends["cng"]["primary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_fossil = self.fuel_blends["cng"]["primary"]["CO2"]

                if self.fuel_blends["cng"]["secondary"]["type"] == "cng":
                    share_fossil += self.fuel_blends["cng"]["secondary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_fossil = self.fuel_blends["cng"]["primary"]["CO2"]

                self.A[
                    :,
                    self.inputs[("Carbon dioxide, fossil", ("air",), "kilogram")],
                    ind_A,
                ] = (
                    (
                        array[self.array_inputs["fuel mass"], :, ind_array]
                        * share_fossil
                        * CO2_fossil
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

                # Fuel-based CO2 emission from alternative cng
                # The share of non-fossil gas in the blend is retrieved
                # As well as the CO2 emission factor of the fuel

                share_non_fossil = 0
                CO2_non_fossil = 0

                if self.fuel_blends["cng"]["primary"]["type"] != "cng":
                    share_non_fossil += self.fuel_blends["cng"]["primary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_non_fossil = self.fuel_blends["cng"]["primary"]["CO2"]

                if self.fuel_blends["cng"]["secondary"]["type"] != "cng":
                    share_non_fossil += self.fuel_blends["cng"]["secondary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_non_fossil = self.fuel_blends["cng"]["secondary"]["CO2"]

                self.A[
                    :,
                    self.inputs[
                        (
                            "Carbon dioxide, from soil or biomass stock",
                            ("air",),
                            "kilogram",
                        )
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_non_fossil
                            * CO2_non_fossil
                        )
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

        if [i for i in self.scope["powertrain"] if i in ["ICEV-d", "PHEV-d", "HEV-d"]]:
            index = self.get_index_vehicle_from_array(["ICEV-d", "PHEV-d", "HEV-d"])

            print(
                "{} is completed by {}.".format(
                    self.fuel_blends["diesel"]["primary"]["type"],
                    self.fuel_blends["diesel"]["secondary"]["type"],
                ),
                end="\n \t * ",
            )

            for y in self.scope["year"]:
                if self.scope["year"].index(y) + 1 == len(self.scope["year"]):
                    end_str = "\n * "
                else:
                    end_str = "\n \t * "
                print(
                    "in "
                    + str(y)
                    + " _________________________________________ "
                    + str(
                        np.round(
                            self.fuel_blends["diesel"]["secondary"]["share"][
                                self.scope["year"].index(y)
                            ]
                            * 100,
                            0,
                        )
                    )
                    + "%",
                    end=end_str,
                )

            for y in self.scope["year"]:
                ind_A = [
                    self.inputs[i]
                    for i in self.inputs
                    if str(y) in i[0]
                    and "duty" in i[0]
                    and any(x in i[0] for x in ["ICEV-d", "PHEV-d", "HEV-d"])
                ]

                ind_array = [
                    x for x in self.get_index_vehicle_from_array(y) if x in index
                ]

                # Fuel supply
                self.A[
                    :,
                    [
                        self.inputs[i]
                        for i in self.inputs
                        if str(y) in i[0] and "fuel supply for diesel vehicles" in i[0]
                    ],
                    ind_A,
                ] = (
                    (array[self.array_inputs["fuel mass"], :, ind_array])
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

                # Fuel-based CO2 emission from conventional diesel
                share_fossil = 0
                CO2_fossil = 0
                if self.fuel_blends["diesel"]["primary"]["type"] == "diesel":
                    share_fossil = self.fuel_blends["diesel"]["primary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_fossil = self.fuel_blends["diesel"]["primary"]["CO2"]

                if self.fuel_blends["diesel"]["secondary"]["type"] == "diesel":
                    share_fossil += self.fuel_blends["diesel"]["secondary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_fossil = self.fuel_blends["diesel"]["secondary"]["CO2"]

                self.A[
                    :,
                    self.inputs[("Carbon dioxide, fossil", ("air",), "kilogram")],
                    ind_A,
                ] = (
                    (
                        array[self.array_inputs["fuel mass"], :, ind_array]
                        * share_fossil
                        * CO2_fossil
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

                # Fuel-based SO2 emissions
                # Sulfur concentration value for a given country, a given year, as concentration ratio
                if self.country in self.bs.sulfur.country.values:
                    sulfur_concentration = (
                        self.bs.sulfur.sel(country=self.country, year=y, fuel="diesel")
                        .sum()
                        .values
                    )
                else:
                    # if we do not have the sulfur concentration for the required country, we pick Europe
                    print(
                        "The sulfur content for diesel fuel in {} could not be found. European average sulfur content is used instead.".format(
                            self.country
                        )
                    )
                    sulfur_concentration = (
                        self.bs.sulfur.sel(country="RER", year=y, fuel="diesel")
                        .sum()
                        .values
                    )

                self.A[
                    :, self.inputs[("Sulfur dioxide", ("air",), "kilogram")], ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil  # assumes sulfur only present in conventional diesel
                            * sulfur_concentration
                            * (64 / 32)  # molar mass of SO2/molar mass of O2
                        )
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

                share_non_fossil = 0
                CO2_non_fossil = 0

                # Fuel-based CO2 emission from alternative diesel
                # The share of non-fossil fuel in the blend is retrieved
                # As well as the CO2 emission factor of the fuel
                if self.fuel_blends["diesel"]["primary"]["type"] != "diesel":
                    share_non_fossil += self.fuel_blends["diesel"]["primary"]["share"][
                        self.scope["year"].index(y)
                    ]
                    CO2_non_fossil = self.fuel_blends["diesel"]["primary"]["CO2"]

                if self.fuel_blends["diesel"]["secondary"]["type"] != "diesel":
                    share_non_fossil += self.fuel_blends["diesel"]["secondary"][
                        "share"
                    ][self.scope["year"].index(y)]
                    CO2_non_fossil = self.fuel_blends["diesel"]["secondary"]["CO2"]

                self.A[
                    :,
                    self.inputs[
                        (
                            "Carbon dioxide, from soil or biomass stock",
                            ("air",),
                            "kilogram",
                        )
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_non_fossil
                            * CO2_non_fossil
                        )
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    / (
                        array[self.array_inputs["total cargo mass"], :, ind_array]
                        / 1000
                    )
                    * -1
                ).T

                # Heavy metals emissions from conventional diesel
                # Emission factors from Spielmann et al., Transport Services Data v.2 (2007)
                # Cadmium, 0.01 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        ("Cadmium", ("air", "urban air close to ground"), "kilogram")
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 1e-8
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

                # Copper, 1.7 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        ("Copper", ("air", "urban air close to ground"), "kilogram")
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 1.7e-6
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

                # Chromium, 0.05 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        ("Chromium", ("air", "urban air close to ground"), "kilogram")
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 5.0e-8
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

                # Nickel, 0.07 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        ("Nickel", ("air", "urban air close to ground"), "kilogram")
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 7.0e-8
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

                # Selenium, 0.01 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        ("Selenium", ("air", "urban air close to ground"), "kilogram")
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 1.0e-8
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

                # Zinc, 1 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        ("Zinc", ("air", "urban air close to ground"), "kilogram")
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 1.0e-6
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

                # Chromium VI, 0.0001 mg/kg diesel
                self.A[
                    :,
                    self.inputs[
                        (
                            "Chromium VI",
                            ("air", "urban air close to ground"),
                            "kilogram",
                        )
                    ],
                    ind_A,
                ] = (
                    (
                        (
                            array[self.array_inputs["fuel mass"], :, ind_array]
                            * share_fossil
                        )
                        * 1.0e-10
                    )
                    / array[self.array_inputs["target range"], :, ind_array]
                    * -1
                ).T

        # Non-exhaust emissions
        self.A[
            :,
            self.inputs[
                (
                    "treatment of road wear emissions, lorry",
                    "RER",
                    "kilogram",
                    "road wear emissions, lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["driving mass"], :]
            * 7e-09
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
        )
        self.A[
            :,
            self.inputs[
                (
                    "treatment of tyre wear emissions, lorry",
                    "RER",
                    "kilogram",
                    "tyre wear emissions, lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["driving mass"], :]
            * 8.055e-8
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
        )
        self.A[
            :,
            self.inputs[
                (
                    "treatment of brake wear emissions, lorry",
                    "RER",
                    "kilogram",
                    "brake wear emissions, lorry",
                )
            ],
            -self.number_of_cars :,
        ] = (
            array[self.array_inputs["driving mass"], :]
            * 8.13e-9
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
        )

        # Infrastructure: 5.37e-4 per gross tkm
        self.A[
            :,
            self.inputs[("market for road", "GLO", "meter-year", "road")],
            -self.number_of_cars :,
        ] = (
            (
                (array[self.array_inputs["driving mass"], :] / 1000)
                * 5.37e-4
                / (array[self.array_inputs["total cargo mass"], :] / 1000)
            )
            * -1
        )

        # Infrastructure maintenance
        self.A[
            :,
            self.inputs[
                ("market for road maintenance", "RER", "meter-year", "road maintenance")
            ],
            -self.number_of_cars :,
        ] = (1.29e-3 / (array[self.array_inputs["total cargo mass"], :] / 1000) * -1)

        # Exhaust emissions
        # Non-fuel based emissions
        self.A[:, self.index_emissions, -self.number_of_cars :] = (
            array[
                [
                    self.array_inputs[self.map_non_fuel_emissions[self.rev_inputs[x]]]
                    for x in self.index_emissions
                ]
            ]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        ).transpose([1, 0, 2])

        # End-of-life disposal and treatment
        self.A[
            :,
            self.inputs[
                (
                    "treatment of used lorry, 16 metric ton",
                    "CH",
                    "unit",
                    "used lorry, 16 metric ton",
                )
            ],
            index_16t,
        ] = (
            1
            / array[self.array_inputs["lifetime kilometers"], :, index_arr_16t]
            / (array[self.array_inputs["total cargo mass"], :, index_arr_16t] / 1000)
        ).T

        self.A[
            :,
            self.inputs[
                (
                    "treatment of used lorry, 28 metric ton",
                    "CH",
                    "unit",
                    "used lorry, 28 metric ton",
                )
            ],
            index_28t,
        ] = (
            1
            / array[self.array_inputs["lifetime kilometers"], :, index_arr_28t]
            / (array[self.array_inputs["total cargo mass"], :, index_arr_28t] / 1000)
        ).T

        self.A[
            :,
            self.inputs[
                (
                    "treatment of used lorry, 40 metric ton",
                    "CH",
                    "unit",
                    "used lorry, 40 metric ton",
                )
            ],
            index_40t,
        ] = (
            1
            / array[self.array_inputs["lifetime kilometers"], :, index_arr_40t]
            / (array[self.array_inputs["total cargo mass"], :, index_arr_40t] / 1000)
        ).T

        # Noise emissions
        self.A[:, self.index_noise, -self.number_of_cars :] = (
            array[
                [
                    self.array_inputs[self.map_noise_emissions[self.rev_inputs[x]]]
                    for x in self.index_noise
                ]
            ]
            / (array[self.array_inputs["total cargo mass"], :] / 1000)
            * -1
        ).transpose([1, 0, 2])
        print("*********************************************************************")
