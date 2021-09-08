import itertools

import numpy as np
import pandas as pd

from . import DATA_DIR

pd.options.mode.chained_assignment = None

REGION_MAPPING_FILEPATH = DATA_DIR / "regionmappingH12.csv"
IAM_ELEC_MARKETS = DATA_DIR / "electricity_markets.csv"
IEA_DIESEL_SHARE = DATA_DIR / "diesel_share_oecd.csv"


def build_fleet_array(fp, scope):
    """
    Receives a file path that points to a CSV file that contains the fleet composition
    Checks that the fleet composition array is valid.

    Specifically:

    * the years specified in the fleet must be present in scope["year"]
    * the powertrains specified in the fleet must be present in scope["powertrain"]
    * the sizes specified in the fleet must be present in scope["size"]
    * the sum for each year-powertrain-size set must equal 1

    :param fp: filepath to an array that contains fleet composition
    :type fp: str
    :return array: fleet composition array
    :rtype array: xarray.DataArray
    """
    arr = pd.read_csv(fp, delimiter=";", header=0, index_col=[0, 1, 2])
    arr = arr.fillna(0)
    arr.columns = [int(c) for c in arr.columns]

    new_cols = [c for c in scope["year"] if c not in arr.columns]
    arr[new_cols] = pd.DataFrame([[0] * len(new_cols)], index=arr.index)

    a = [scope["powertrain"]] + [scope["size"]] + [scope["year"]]

    for row in [i for i in list(itertools.product(*a)) if i not in arr.index]:
        arr.loc[row] = 0

    array = arr.to_xarray()
    array = array.rename(
        {"level_0": "powertrain", "level_1": "size", "level_2": "vintage_year"}
    )

    if not set(list(array.data_vars)).issubset(scope["year"]):
        raise ValueError("The fleet years differ from {}".format(scope["year"]))

    if set(scope["year"]) != set(array.coords["vintage_year"].values.tolist()):
        raise ValueError(
            "The list of vintage years differ from {}.".format(scope["year"])
        )

    if not set(array.coords["powertrain"].values.tolist()).issubset(
        scope["powertrain"]
    ):
        raise ValueError(
            "The fleet powertrain list differs from {}".format(scope["powertrain"])
        )

    if not set(array.coords["size"].values.tolist()).issubset(scope["size"]):
        raise ValueError("The fleet size list differs from {}".format(scope["size"]))

    return array.to_array().fillna(0)


def create_fleet_composition_from_IAM_file(fp):
    """
    This function creates a consumable fleet composition array from a CSV file.
    The array returned is consumed by `InventoryCalculation`.
    :param fp: Path file path
    :type fp: Path
    :param iam_region: IAM region for which to extract fleet composition
    :type iam_region: str
    :param fleet_year: the year for which to extract fleet composition
    :type fleet_year: int
    :return: fleet composition array
    :rtype: xarray.DataArray
    """

    # Read the fleet composition CSV file
    df = pd.read_csv(fp, delimiter=",")
    df = df.fillna(0)
    df = df[
        [
            "year",
            "vintage_year",
            "IAM_region",
            "powertrain",
            "size",
            "vintage_demand_tkm",
        ]
    ]

    df_gr = df.groupby(
        ["year", "vintage_year", "IAM_region", "powertrain", "size"]
    ).sum()

    df_gr = df_gr.groupby(level=[0, 2, 3]).apply(lambda x: x / float(x.sum()))
    df = df_gr.reset_index()
    df = df.fillna(0)

    # Turn the dataframe into a pivot table
    df = df.pivot_table(
        index=["IAM_region", "powertrain", "size", "vintage_year"],
        columns=["year"],
        aggfunc=np.sum,
    )["vintage_demand_tkm"]

    # xarray.DataArray is returned
    return df.to_xarray().fillna(0).to_array().round(3)
