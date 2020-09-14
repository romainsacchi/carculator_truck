from . import DATA_DIR
import numpy as np
import sys


def get_standard_driving_cycle(name="Urban delivery"):

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
        "Urban delivery": [1, 4, 7, 10, 13, 16],
        "Regional delivery": [2, 5, 8, 11, 14, 17],
        "Long haul": [3, 6, 9, 12, 15, 18]
    }

    try:
        arr = np.genfromtxt(DATA_DIR / "driving_cycles.csv", delimiter=";")
        # we skip the headers
        dc = arr[1:, dict_dc_names[name]]
        dc = dc[~np.isnan(dc)]
        return dc.reshape((-1,6))

    except KeyError:
        print("The specified driving cycle could not be found.")
        sys.exit(1)
