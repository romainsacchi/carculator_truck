import numexpr as ne
import numpy as np


class NoiseEmissionsModel:
    """
    Calculate propulsion and rolling noise emissions for combustion, hybrid and electric trucks, based on CNOSSOS model.

    :param cycle: Driving cycle. Pandas Series of second-by-second speeds (km/h) or name (str)
        of cycle e.g., "WLTC","WLTC 3.1","WLTC 3.2","WLTC 3.3","WLTC 3.4","CADC Urban","CADC Road",
        "CADC Motorway","CADC Motorway 130","CADC","NEDC".
    :type cycle: pandas.Series

    """

    def __init__(self, cycle_name):

        self.cycle_name = cycle_name
        self.cycle_environment = {
            "Urban delivery": {"urban start": 0},
            "Long haul": {"rural start": 0},
            "Regional delivery": {
                "urban start": 0,
                "urban stop": 250,
                "suburban start": 251,
                "suburban stop": 750,
                "rural start": 751,
            },
        }

    def rolling_noise(self, category, cycle):
        """Calculate noise from rolling friction.
        Model from CNOSSOS-EU project
        (http://publications.jrc.ec.europa.eu/repository/bitstream/JRC72550/cnossos-eu%20jrc%20reference%20report_final_on%20line%20version_10%20august%202012.pdf)

        :param category: "medium" or "heavy" duty vehicles.
        :type category: str.

        :returns: A numpy array with rolling noise (dB) for each 8 octaves, per second of driving cycle
        :rtype: numpy.array

        """

        array = np.tile(
            np.log10(cycle / 70, out=np.zeros_like(cycle), where=(cycle != 0)), 8
        ).reshape((8, -1))

        if category == "medium":
            constants = np.array(
                (84, 88.7, 91.5, 96.7, 97.4, 90.9, 83.8, 80.5)
            ).reshape((-1, 1))
            coefficients = np.array(
                (30, 35.8, 32.6, 23.8, 30.1, 36.2, 38.3, 40.1)
            ).reshape((-1, 1))

        else:
            constants = np.array(
                (87, 91.7, 94.1, 100.7, 100.8, 94.3, 87.1, 82.5)
            ).reshape((-1, 1))
            coefficients = np.array(
                (30, 33.5, 31.3, 25.4, 31.8, 37.1, 38.6, 40.6)
            ).reshape((-1, 1))
        array = array * coefficients + constants

        return array

    def propulsion_noise(self, powertrain_type, category, cycle):
        """Calculate noise from propulsion engine and gearbox.
        Model from CNOSSOS-EU project
        (http://publications.jrc.ec.europa.eu/repository/bitstream/JRC72550/cnossos-eu%20jrc%20reference%20report_final_on%20line%20version_10%20august%202012.pdf)

        For electric cars, special coefficients are applied from
        (`Pallas et al. 2016 <https://www.sciencedirect.com/science/article/pii/S0003682X16301608>`_ )

        Also, for electric cars, a warning signal of 56 dB is added when the car drives at 20 km/h or lower.

        Although we deal here with trucks, we reuse the coefficeint for electric cars

        :param powertrain_type:
        :param category: "medium" or "heavy" duty vehicles.
        :type category: str.
        :returns: A numpy array with propulsion noise (dB) for all 8 octaves, per second of driving cycle
        :rtype: numpy.array

        """

        cycle = np.array(cycle)

        # Noise sources are calculated for speeds above 20 km/h.
        if powertrain_type in ("combustion", "electric"):
            if category == "medium":
                array = np.tile((cycle - 70) / 70, 8).reshape((8, -1))

                constants = np.array(
                    (101, 96.5, 98.8, 96.8, 98.6, 95.2, 88.8, 82.7)
                ).reshape((-1, 1))
                coefficients = np.array(
                    (-1.9, 4.7, 6.4, 6.5, 6.5, 6.5, 6.5, 6.5)
                ).reshape((-1, 1))

            if category == "heavy":
                array = np.tile((cycle - 70) / 70, 8).reshape((8, -1))
                constants = np.array(
                    (104.4, 100.6, 101.7, 101, 100.1, 95.9, 91.3, 85.3)
                ).reshape((-1, 1))
                coefficients = np.array((0, 3, 4.6, 5, 5, 5, 5, 5)).reshape((-1, 1))

            array = array * coefficients + constants

            if powertrain_type == "electric":
                # For electric cars, we add correction factors
                # We also add a 56 dB loud sound signal when the speed is below 20 km/h.
                correction = np.array((0, 1.7, 4.2, 15, 15, 15, 13.8, 0)).reshape(
                    (-1, 1)
                )
                array -= correction
                array[:, cycle.reshape(-1) < 20] = 56
            else:
                array[:, cycle.reshape(-1) < 20] = 0
        else:
            # For non plugin-hybrids, apply electric engine noise coefficient up to 30 km/h
            # and combustion engine noise coefficients above 30 km/h
            electric = self.propulsion_noise(
                powertrain_type="electric", category=category, cycle=cycle
            )
            electric_mask = cycle.reshape(-1) < 30

            array = self.propulsion_noise(
                powertrain_type="combustion", category=category, cycle=cycle
            )
            array[:, electric_mask] = electric[:, electric_mask]

        return array

    def get_sound_power_per_compartment(self, powertrain_type, category, cycle):
        """
        Calculate sound energy (in J/s) over the driving cycle duration from sound power (in dB).
        The sound energy sums are further divided into `geographical compartments`: urban, suburban and rural.

        :return: Sound energy (in Joules) per km driven, per geographical compartment.
        :rtype: numpy.array
        """

        if powertrain_type not in ("combustion", "electric", "hybrid"):
            raise TypeError("The powertrain type is not valid.")

        # rolling noise, in dB, for each second of the driving cycle
        if category in ("medium", "heavy"):
            rolling = self.rolling_noise(category, cycle).reshape(
                8, cycle.shape[-1], -1
            )
            # propulsion noise, in dB, for each second of the driving cycle
            propulsion = self.propulsion_noise(
                powertrain_type, category, cycle
            ).reshape(8, cycle.shape[-1], -1)
            c = cycle.T

        else:
            raise TypeError("The category type is not valid.")

        # sum of rolling and propulsion noise sources
        total_noise = ne.evaluate(
            "where(c != 0, 10 * log10((10 ** (rolling / 10)) + (10 ** (propulsion / 10))), 0)"
        )

        # convert dBs to Watts (or J/s)
        sound_power = ne.evaluate("(10 ** -12) * (10 ** (total_noise / 10))")

        # If the driving cycle selected is one of the driving cycles for which carculator has specifications,
        # we use the driving cycle "official" road section types to compartmentalize emissions.
        # If the driving cycle selected is instead specified by the user (passed directly as an array), we used
        # speed levels to compartmentalize emissions.

        if self.cycle_name in self.cycle_environment:
            distance = c.sum(axis=1) / 3600

            if "urban start" in self.cycle_environment[self.cycle_name]:
                start = self.cycle_environment[self.cycle_name]["urban start"]
                stop = self.cycle_environment[self.cycle_name].get(
                    "urban stop", c.shape[-1]
                )
                urban = np.sum(sound_power[:, :, start:stop], axis=2) / distance

            else:
                urban = np.zeros((8, c.shape[0]))

            if "suburban start" in self.cycle_environment[self.cycle_name]:
                start = self.cycle_environment[self.cycle_name]["suburban start"]
                stop = self.cycle_environment[self.cycle_name].get(
                    "suburban stop", c.shape[-1]
                )
                suburban = np.sum(sound_power[:, :, start:stop], axis=2) / distance

            else:
                suburban = np.zeros((8, c.shape[0]))

            if "rural start" in self.cycle_environment[self.cycle_name]:
                start = self.cycle_environment[self.cycle_name]["rural start"]
                stop = self.cycle_environment[self.cycle_name].get(
                    "rural stop", c.shape[-1]
                )
                rural = np.sum(sound_power[:, :, start:stop], axis=2) / distance

            else:
                rural = np.zeros((8, c.shape[0]))

        else:
            distance = c.sum(axis=0) / 3600

            # sum sound power over duration (J/s * s --> J) and divide by distance (--> J / km) and further
            # divide into compartments
            urban = ne.evaluate("sum(where(c <= 50, sound_power, 0), 1)") / distance
            suburban = (
                ne.evaluate("sum(where((c > 50) & (c <= 80), sound_power, 0), 1)")
                / distance
            )
            rural = ne.evaluate("sum(where(c > 80, sound_power, 0), 1)") / distance

        res = np.vstack([urban, suburban, rural]).T
        return res.reshape(-1, 1, 24, 1, 1)
