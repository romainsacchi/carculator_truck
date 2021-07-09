import sys

import numpy as np

from . import DATA_DIR


def get_standard_driving_cycle(
    name="Urban delivery", size=["3.5t", "7.5t", "18t", "26t", "32t", "40t", "60t"]
):

    """Get driving cycle data as a Pandas `Series`.

    Driving cycles are given as km/h per second. Sourced from VECTO 3.3.7.

    :param name: The name of the driving cycle. "Urban delivery" is chosen by default if :param name: left unspecified.
    :type name: str

    ``name`` should be one of:

    * Urban delivery
    * Regional delivery
    * Long haul

    :returns: A pandas DataFrame object with driving time (in seconds) as index,
        and velocity (in km/h) as values.
    :rtype: panda.Series

    """

    # definition of columns to select in the CSV file
    # each column corresponds to a size class
    # since the driving cycle is simulated for each size class
    # for example, a heavier truck will take more time to reach the target speed
    # because of higher inertia resistance
    dict_dc_names = {
        "Urban delivery": [1, 4, 7, 10, 13, 16, 19],
        "Regional delivery": [2, 5, 8, 11, 14, 17, 20],
        "Long haul": [3, 6, 9, 12, 15, 18, 21],
    }

    dict_dc_sizes = {
        "3.5t": [1, 2, 3],
        "7.5t": [4, 5, 6],
        "18t": [7, 8, 9],
        "26t": [10, 11, 12],
        "32t": [13, 14, 15],
        "40t": [16, 17, 18],
        "60t": [19, 20, 21],
    }

    try:
        list_col = [
            c for s in size for c in dict_dc_sizes[s] if c in dict_dc_names[name]
        ]
        arr = np.genfromtxt(DATA_DIR / "driving_cycles.csv", delimiter=";")
        # we skip the headers
        dc = arr[1:, list_col]
        dc = dc[~np.isnan(dc)]
        return dc.reshape((-1, len(list_col)))

    except KeyError:
        print("The specified driving cycle could not be found.")
        sys.exit(1)
