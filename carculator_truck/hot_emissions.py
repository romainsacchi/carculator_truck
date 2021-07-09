import numpy as np
import pandas as pd
import xarray

from . import DATA_DIR


def _(o):
    """Add a trailing dimension to make input arrays broadcast correctly"""
    if isinstance(o, (np.ndarray, xarray.DataArray)):
        return np.expand_dims(o, -1)
    else:
        return o


def get_emission_factors():
    """Emissions factors extracted for trucks from HBEFA 4.1
    deatiled by size, powertrain and EURO class for each substance.
    """
    fp = DATA_DIR / "hbefa_factors_vs_fc.xls"
    ef = pd.read_excel(fp)
    return (
        ef.groupby(["powertrain", "euro_class", "component"]).sum().to_xarray() / 1000
    ).to_array()


class HotEmissionsModel:
    """
    Calculate hot pollutants emissions based on HBEFA 4.1 data, function of speed (given by the driving cycle)
    for vehicles with a combustion engine.

    :param cycle: Driving cycle. Pandas Series of second-by-second speeds (km/h) or name (str)
        of cycle e.g., "Urban delivery", "Regional delivery", "Long haul".
    :type cycle: pandas.Series

    """

    def __init__(self, cycle_name, cycle):

        self.cycle_name = cycle_name
        self.cycle = cycle
        # We determine which sections of the driving cycle correspond to an urban, suburban and rural environment
        # This is to compartmentalize emissions
        self.cycle_environment = {
            "Urban delivery": {"urban start": 0, "urban stop": -1},
            "Long haul": {"rural start": 0, "rural stop": -1},
            "Regional delivery": {
                "urban start": 0,
                "urban stop": 250,
                "suburban start": 251,
                "suburban stop": 750,
                "rural start": 751,
                "rural stop": -1,
            },
        }
        self.em = get_emission_factors()

    def get_emissions_per_powertrain(
        self, powertrain_type, euro_classes, energy_consumption, debug_mode=False
    ):
        """
        Calculate hot pollutants emissions given a powertrain type (i.e., diesel, CNG) and a EURO pollution class,
        per air sub-compartment (i.e., urban, suburban and rural).

        The emission sums are further divided into `air compartments`: urban, suburban and rural.

        :param euro_classes:
        :param debug_mode:
        :param powertrain_type: "diesel", or "CNG"
        :type powertrain_type: str
        :param energy: second by second tank-to-wheel energy consumption
        :type energy: array
        :return: Pollutants emission per km driven, per air compartment.
        :rtype: numpy.array
        """

        if powertrain_type not in ("diesel", "cng"):
            raise TypeError("The powertrain type is not valid.")

        arr = self.em.sel(
            powertrain=powertrain_type,
            euro_class=euro_classes,
            component=[
                "HC",
                "CO",
                "NOx",
                "PM",
                "CH4",
                "NMHC",
                "N2O",
                "NH3",
                "Benzene",
            ],
        ).transpose("component", "euro_class", "variable")

        distance = np.squeeze(self.cycle.sum(axis=0)) / 3600

        if isinstance(distance, np.float):
            distance = np.array(distance).reshape(1, 1)

        # Emissions for each second of the driving cycle equal:
        # a * energy consumption + b
        # with a, b being a coefficient and an intercept respectively given by fitting HBEFA 4.1 data
        # the fitting of emissions function of energy consumption is described in the notebook
        # `HBEFA trucks.ipynb` in the folder `dev`.
        a = (
            arr.sel(variable="a").values[:, None, None, :, None, None]
            * energy_consumption.values
        )
        b = arr.sel(variable="b").values[:, None, None, :, None, None]

        # The receiving array should contain 39 substances, not 10
        arr_shape = list(a.shape)
        arr_shape[0] = 39
        em_arr = np.zeros(tuple(arr_shape))

        em_arr[:9] = a + b

        # NH3 and N2O emissions seem to vary with the Euro class
        # rather than the fuel consumption

        # NH3

        # Euro class --> correction factor
        correction_map = {3: 0.15, 4: 0.15, 5: 0.12, 6: 0.5}
        k = np.array(list(correction_map.keys()))
        v = np.array(list(correction_map.values()))

        correction_factors = np.zeros_like(euro_classes, dtype=np.float64)
        for key, val in zip(k, v):
            correction_factors[np.array(euro_classes) == key] = val

        em_arr[7] /= correction_factors[None, None, :, None, None]

        # Ethane, Propane, Butane, Pentane, Hexane, Cyclohexane, Heptane
        # Ethene, Propene, 1-Pentene, Toluene, m-Xylene, o-Xylene
        # Formaldehyde, Acetaldehyde, Benzaldehyde, Acetone
        # Methyl ethyl ketone, Acrolein, Styrene
        # which are calculated as fractions of NMVOC emissions

        ratios_NMHC = np.array(
            [
                3.00e-04,
                1.00e-03,
                1.50e-03,
                6.00e-04,
                0.00e00,
                0.00e00,
                3.00e-03,
                0.00e00,
                0.00e00,
                0.00e00,
                1.00e-04,
                9.80e-03,
                4.00e-03,
                8.40e-02,
                4.57e-02,
                1.37e-02,
                0.00e00,
                0.00e00,
                1.77e-02,
                5.60e-03,
            ]
        )

        em_arr[9:29] = (em_arr[6] * ratios_NMHC.reshape(-1, 1, 1, 1, 1, 1)).transpose(
            0, 1, 2, 3, 4, 5
        )

        # remaining NMVOC
        em_arr[5] *= 1 - np.sum(ratios_NMHC)

        if powertrain_type == "diesel":
            # We also add heavy metals if diesel
            # which are initially defined per kg of fuel consumed
            # here converted to grams emitted/kj
            heavy_metals = np.array(
                [
                    1.82e-09,
                    2.33e-12,
                    2.33e-12,
                    4.05e-08,
                    4.93e-10,
                    2.05e-10,
                    6.98e-10,
                    1.40e-12,
                    1.23e-10,
                    2.02e-10,
                ]
            )

            em_arr[29:] = (
                heavy_metals.reshape(-1, 1, 1, 1, 1, 1) * energy_consumption.values
            )

        # In case the fit produces negative numbers (it should not, though)
        em_arr[em_arr < 0] = 0

        # If the driving cycle selected is one of the driving cycles for which carculator has specifications,
        # we use the driving cycle "official" road section types to compartmentalize emissions.
        # If the driving cycle selected is instead specified by the user (passed directly as an array), we used
        # speed levels to compartmentalize emissions.

        if "urban start" in self.cycle_environment[self.cycle_name]:
            start = self.cycle_environment[self.cycle_name]["urban start"]
            stop = self.cycle_environment[self.cycle_name]["urban stop"]
            urban = np.sum(em_arr[..., start:stop], axis=-1)
            urban /= 1000  # going from grams to kg
            urban /= distance[:, None, None, None]

        else:
            urban = np.zeros(
                (
                    39,
                    self.cycle.shape[-1],
                    em_arr.shape[2],
                    em_arr.shape[3],
                    em_arr.shape[4],
                )
            )

        if "suburban start" in self.cycle_environment[self.cycle_name]:
            start = self.cycle_environment[self.cycle_name]["suburban start"]
            stop = self.cycle_environment[self.cycle_name]["suburban stop"]
            suburban = np.sum(em_arr[..., start:stop], axis=-1)
            suburban /= 1000  # going from grams to kg
            suburban /= distance[:, None, None, None]

        else:
            suburban = np.zeros(
                (
                    39,
                    self.cycle.shape[-1],
                    em_arr.shape[2],
                    em_arr.shape[3],
                    em_arr.shape[4],
                )
            )

        if "rural start" in self.cycle_environment[self.cycle_name]:
            start = self.cycle_environment[self.cycle_name]["rural start"]
            stop = self.cycle_environment[self.cycle_name]["rural stop"]
            rural = np.sum(em_arr[..., start:stop], axis=-1)
            rural /= 1000  # going from grams to kg
            rural /= distance[:, None, None, None]

        else:

            rural = np.zeros(
                (
                    39,
                    self.cycle.shape[-1],
                    em_arr.shape[2],
                    em_arr.shape[3],
                    em_arr.shape[4],
                )
            )

        res = np.vstack((urban, suburban, rural))

        return res.transpose(1, 2, 0, 3, 4)
