import numpy as np


class ParticulatesEmissionsModel:
    """
    Calculate particulates emissions based on the method described in:
    https://www.eea.europa.eu/ds_resolveuid/6USNA27I4D

    and further disaggregated in:
    https://doi.org/10.1016/j.atmosenv.2020.117886

    Include emission from:

    - brake wear
    - tire wear
    - road wear
    - re-suspended road dust

    by considering:

    - vehicle mass
    - driving situation (urban, rural, motorway)

    into the following fractions:

    - PM 2.5
    - PM 10

    Emissions are subdivided in compartments: urban, suburban and rural.

    :param cycle: Driving cycle. Pandas Series of second-by-second speeds (km/h) or name (str)
        of cycle e.g., "Urban delivery", "Regional delivery", "Long haul".
    :param cycle_name: name of the driving cycle. Str.
    :type cycle: pandas.Series

    """

    def __init__(self, cycle_name, cycle, mass):

        self.cycle_name = cycle_name
        self.cycle = np.resize(
            cycle,
            (
                cycle.shape[0],
                mass.shape[-1],
                mass.shape[2],
                mass.shape[1],
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

        self.mass = mass.values / 1000  # in tons

    def get_abrasion_emissions(self):

        (
            tire_pm10_urban,
            tire_pm10_rural,
            tire_pm10_motorway,
            tire_pm25_urban,
            tire_pm25_rural,
            tire_pm25_motorway,
        ) = self.get_tire_wear_emissions()

        (
            brake_pm10_urban,
            brake_pm10_rural,
            brake_pm10_motorway,
            brake_pm25_urban,
            brake_pm25_rural,
            brake_pm25_motorway,
        ) = self.get_brake_wear_emissions()

        road_pm10, road_pm25 = self.get_road_wear_emissions()

        dust_pm10, dust_pm25 = self.get_resuspended_road_dust()

        if self.cycle_name == "Urban delivery":
            tire_wear = tire_pm10_urban + tire_pm25_urban
            brake_wear = brake_pm10_urban + brake_pm25_urban

        elif self.cycle_name == "Regional delivery":
            tire_wear = (tire_pm10_urban + tire_pm25_urban) * 0.16
            tire_wear += (tire_pm10_rural + tire_pm25_rural) * 0.32
            tire_wear += (tire_pm10_motorway + tire_pm25_motorway) * 0.52

            brake_wear = (brake_pm10_urban + brake_pm25_urban) * 0.16
            brake_wear += (brake_pm10_rural + brake_pm25_rural) * 0.32
            brake_wear += (brake_pm10_motorway + brake_pm25_motorway) * 0.52

        else:
            tire_wear = tire_pm10_motorway + tire_pm25_motorway
            brake_wear = brake_pm10_motorway + brake_pm25_motorway

        road_wear = road_pm10 + road_pm25

        road_dust = dust_pm10 + dust_pm25

        res = np.vstack(
            (
                tire_wear.sum(axis=2)[None, ...],
                brake_wear.sum(axis=2)[None, ...],
                road_wear.sum(axis=2)[None, ...],
                road_dust.sum(axis=2)[None, ...],
            )
        )

        return res.transpose(1, 2, 0, 3)[..., None]

    def get_tire_wear_emissions(self):
        """
        Returns tire wear emissions.

        :return:
        """

        # converted to kg per vkm
        pm10_urban = 5.8 * np.power(self.mass, 1 / 2.3) / 1e6
        pm25_urban = 8.2 * np.power(self.mass, 1 / 2.3) / 1e6

        pm10_rural = 4.5 * np.power(self.mass, 1 / 2.3) / 1e6
        pm25_rural = 6.4 * np.power(self.mass, 1 / 2.3) / 1e6

        pm10_motorway = 3.8 * np.power(self.mass, 1 / 2.3) / 1e6
        pm25_motorway = 5.5 * np.power(self.mass, 1 / 2.3) / 1e6

        return (
            pm10_urban,
            pm10_rural,
            pm10_motorway,
            pm25_urban,
            pm25_rural,
            pm25_motorway,
        )

    def get_brake_wear_emissions(self):
        """
        Returns brake wear emissions.

        :return:
        """
        # converted to kg per vkm
        pm10_urban = 4.2 * np.power(self.mass, 1 / 1.9) / 1e6
        pm25_urban = 11 * np.power(self.mass, 1 / 1.9) / 1e6

        pm10_rural = 1.8 * np.power(self.mass, 1 / 1.5) / 1e6
        pm25_rural = 4.5 * np.power(self.mass, 1 / 1.5) / 1e6

        pm10_motorway = 0.4 * np.power(self.mass, 1 / 1.3) / 1e6
        pm25_motorway = 1.0 * np.power(self.mass, 1 / 1.3) / 1e6

        return (
            pm10_urban,
            pm10_rural,
            pm10_motorway,
            pm25_urban,
            pm25_rural,
            pm25_motorway,
        )

    def get_road_wear_emissions(self):
        """
        Returns road wear emissions.

        :return:
        """
        # converted to kg per vkm
        pm10 = 2.8 * np.power(self.mass, 1 / 1.5) / 1e6
        pm25 = 5.1 * np.power(self.mass, 1 / 1.5) / 1e6

        return (pm10, pm25)

    def get_resuspended_road_dust(self):
        """
        Returns re-suspended road dust emissions.

        :return:
        """
        # converted to kg per vkm
        pm10 = 2 * np.power(self.mass, 1 / 1.1) / 1e6
        pm25 = 8.2 * np.power(self.mass, 1 / 1.1) / 1e6

        return (pm10, pm25)
