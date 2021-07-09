import numpy as np


class ParticulatesEmissionsModel:
    """
    Calculate particulates emissions based on the method described in
    https://www.eea.europa.eu/ds_resolveuid/6USNA27I4D

    Include emission from:

    - brake wear
    - tire wear
    - road wear

    by considering:

    - load factor of the vehicle
    - number of axles
    - speed levels

    into the following fractions:

    - PM 10
    - PM 2.5
    - PM 1
    - PM 0.1

    Emissions are subdivided in compartments: urban, suburban and rural.

    :param cycle: Driving cycle. Pandas Series of second-by-second speeds (km/h) or name (str)
        of cycle e.g., "Urban delivery", "Regional delivery", "Long haul".
    :param cycle_name: name of the driving cycle. Str.
    :type cycle: pandas.Series

    """

    def __init__(self, cycle_name, cycle, number_axles, load_factor):

        self.cycle_name = cycle_name
        self.cycle = np.resize(
            cycle,
            (
                cycle.shape[0],
                number_axles.shape[-1],
                number_axles.shape[2],
                number_axles.shape[1],
                cycle.shape[-1],
            ),
        )

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

        self.velocity = self.cycle / 3600  # m/s per second

        self.number_axles = number_axles.values
        self.load_factor = load_factor.values

    def get_abrasion_emissions(self):

        tire_wear = (
            self.get_tire_wear_emissions(self.number_axles, self.load_factor) / 1000
        )

        brake_wear = self.get_brake_wear_emissions(self.load_factor) / 1000

        road_wear = self.get_road_wear_emissions() / 1000

        res = np.vstack(
            (
                tire_wear.sum(axis=0)[None, ...],
                brake_wear.sum(axis=0)[None, ...],
                road_wear.sum(axis=0)[None, ...],
            )
        )

        distance = self.cycle.sum(axis=0) / 3600

        return res / distance  # total emission per duty cycle to total emissions per km

    def get_tire_wear_emissions(self, number_axles, load_factor):
        """
        Returns tire wear emissions.

        :param number_axles: number of axles. Int.
        :param load_factor: load factor. Float.
        :return:
        """
        PM_total = number_axles / 2 * (1.41 + (1.38 * load_factor)) * 0.0107

        PM_total = PM_total.T * self.velocity
        PM_total[self.cycle <= 40] *= 1.39
        PM_total[(self.cycle > 40) & (self.cycle < 90)] *= (
            -0.00974 * self.cycle[(self.cycle > 40) & (self.cycle < 90)] + 1.78
        )
        PM_total[self.cycle > 90] *= 0.902

        return PM_total

    def get_brake_wear_emissions(self, load_factor):
        """
        Returns brake wear emissions.

        :param number_axles: number of axles. Int.
        :param load_factor: load factor. Float.
        :return:
        """
        PM_total = 3.13 * (1 + 0.79 * load_factor) * 0.0075

        PM_total = PM_total.T * self.velocity
        PM_total[self.cycle <= 40] *= 1.67
        PM_total[(self.cycle > 40) & (self.cycle < 90)] *= (
            -0.027 * self.cycle[(self.cycle > 40) & (self.cycle < 90)] + 2.75
        )
        PM_total[self.cycle > 90] *= 0.185

        return PM_total

    def get_road_wear_emissions(self):
        """
        Returns road wear emissions.

        :param number_axles: number of axles. Int.
        :param load_factor: load factor. Float.
        :return:
        """
        PM_total = np.full_like(self.velocity.T, 0.076)
        PM_total = PM_total.T * self.velocity

        return PM_total
