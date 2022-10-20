Introduction
============

``carculator_truck`` is a parameterized model that allows to generate and characterize life cycle inventories for different
truck configurations, according to selected:

* powertrain technologies (5): diesel engine, hybrid diesel, plugin-hybrid diesel, battery electric and fuel cell electric,
* year of operation (5): 2000, 2010, 2020, 2040 and 2050,
* and sizes (9): 3.5t, 7.5t, 18t, 26t, 32t, 40t and 60t.

The methodology used to develop ``carculator_truck`` is explained in:

Does Size Matter? The Influence of Size, Load Factor, Range Autonomy, and Application Type on the Life Cycle Assessment of Current and Future Medium- and Heavy-Duty Vehicles
Romain Sacchi, Christian Bauer, and Brian L. Cox
Environmental Science & Technology 2021 55 (8), 5224-5235
DOI: 10.1021/acs.est.0c07773
`https://doi.org/10.1021/acs.est.0c07773 <https://doi.org/10.1021/acs.est.0c07773>`_

The tool has a focus on trucks.

More specifically, ``carculator_truck`` generates `Brightway2 <https://brightwaylca.org/>`_ and `SimaPro <https://simapro.com/>`_ inventories, but also directly provides characterized
results against several midpoint indicators from the impact assessment method ReCiPe, ILCD, as well as life cycle cost indicators.

``carculator_truck`` is a special in the way that it uses time- and energy-scenario-differentiated background inventories for the future,
resulting from the coupling between the `ecoinvent database <https://ecoinvent.org>`_ and the scenario outputs of PIK's
integrated assessment model `REMIND <https://www.pik-potsdam.de/research/transformation-pathways/models/remind/remind>`_.
This allows to perform prospective study and consider future expected changes in regard to the production of electricity,
cement, steel, heat, etc.

Objective
---------

The objective is to produce life cycle inventories for trucks in a transparent, comprehensive and quick manner,
to be further used in prospective LCA of transportation technologies.

Why?
----

Several life cycle assessment (LCA) models of trucks exist. Yet, because LCA of vehicles, particularly for electric battery vehicles,
are sensitive to assumptions made in regards to electricity mix used for charging, lifetime of the battery, etc., it has led
to mixed conclusions being published in the scientific literature. Because the underlying calculations are kept undocumented,
it is not always possible to explain the disparity in the results given by these models, which can contribute to adding confusion among the public.

Because ``carculator_truck`` is kept **as open as possible**, the methods and assumptions behind the generation of results are
easily identifiable and adjustable.
Also, there is an effort to keep the different modules (classes) separated, so that improving certain areas of the model is relatively
easy and does not require changing extensive parts of the code. In that regard, contributions are welcome.

Finally, beside being more flexible and transparent, ``carculator_truck`` provides interesting features, such as:

* a stochastic mode, that allows fast Monte Carlo analyses, to include uncertainty at the vehicle level
* possibility to override any or all of the 200+ default input car parameters (e.g., cargo load, drag coefficient) but also calculated parameters (e.g., driving mass).
* hot pollutants emissions as a function of the driving cycle, using `HBEFA <https://www.hbefa.net/e/index.html>`_ 4.1 data, further divided between rural, suburban and urban areas
* noise emissions, based on `CNOSSOS-EU <https://ec.europa.eu/jrc/en/publication/reference-reports/common-noise-assessment-methods-europe-cnossos-eu>`_ models for noise emissions and `Noise footprint from personal land‐based mobility by Cucurachi, et al (2019) <https://onlinelibrary.wiley.com/doi/full/10.1111/jiec.12837>`_ for inventory modelling and mid- and endpoint characterization of noise emissions, function of driving cycle and further divided between rural, suburban and urban areas
* export of inventories as an Excel/CSV file, to be used with Brightway2 or Simapro, including uncertainty information. This requires the user to have `ecoinvent` installed on the LCA software the trucks inventories are exported to.
* export inventories directly into Brightway2, as a LCIImporter object to be registered. Additionally, when run in stochastic mode, it is possible to export arrays of pre-sampled values using the `presamples <https://pypi.org/project/presamples/>`_ library to be used together with the Monte Carlo function of Brightway2.

How to install this package?
----------------------------

``carculator_truck`` is a Python package, and is meant to be used from within a Python 3.x environment.
Because ``carculator_truck`` is still at an early development stage, it is a good idea to install it in a separate environment,
such as a conda environment::

    conda create -n <name of the environment> python=3.7

Once your environment created, you should activate it::

    conda activate <name of the environment>

And install the ``carculator_truck`` library in your new environment via Conda::

    conda install -c romainsacchi carculator_truck

or via pip::

    pip install carculator_truck

This will install the package and the required dependencies.

How to use it?
--------------

Static vs. Stochastic mode
**************************

Note: many examples are given in this `notebook <https://github.com/romainsacchi/carculator_truck/blob/master/examples/Examples.ipynb>`_ which you can run directly on your computer.

The inventories can be calculated using the most likely value of the given input parameters ("static" mode), but also using
randomly-generated values based on a probability distribution for those ("stochastic" mode).

For example, the aerodynamic drag coefficient of 32t trucks in 2020, across powertrains, is given the most likely value (i.e., the mode) of 0.38,
but with a triangular probability distribution with a minimum and maximum of 0.3 and 0.4, respectively.

Creating car models in static mode will use the most likely value of the given parameters to dimension the vehicles, etc., such as:

.. code-block:: python

   from carculator_truck import *
   tip = TruckInputParameters()
   tip.static()
   dcts, array = fill_xarray_from_input_parameters(tip)
   tm = TruckModel(array)
   tm.set_all()


Alternatively, if one wishes to work with probability distributions as parameter values instead:

.. code-block:: python

   from carculator_truck import *
   tip = TruckInputParameters()
   tip.stochastic(800)
   dcts, array = fill_xarray_from_input_parameters(tip)
   tm = TruckModel(array)
   tm.set_all()


This effectively creates 800 iterations of the same truck models, picking pseudo-random value for the given parameters,
within the probability distributions defined. This allows to assess later the effect of uncertainty propagation on
characterized results.

In both case, a TruckModel object is returned, with a 4-dimensional array `array` to store the generated parameters values, with the following dimensions:

0. Truck sizes (called "size"):
    * 3.5t
    * 7.5t
    * 18t
    * 26t
    * 32t
    * 40t
    * 60t

1. Powertrains:
    * ICEV-d, ICEV-g: vehicles with internal combustion engines running on diesel and compressed gas, respectively.
    * HEV-d: vehicles with internal combustion engines running on diesel, assisted with an electric engine.
    * PHEV-d: vehicles with internal combustion engines running partly on diesel, and partly on electricity (depending on the electric utility factor selected).
    * BEV: battery electric vehicles.
    * FCEV: fuel cell electric vehicles.

2. Year. Anything between 2000 and 2050.

3. Iteration number (length = 1 if static(), otherwise length = number of iterations).


:meth:`tm.set_all()` generates a TruckModel object and calculates the energy consumption,
components mass, as well as exhaust and non-exhaust emissions for all vehicle profiles.

Driving cycles
**************
Three driving cycles, from the European Commission software VECTO, are available:

* Urban delivery
* Regional delivery
* Long haul

If you do not specify one, the default is the Long haul cycle.
The driving cycle is used to calculate the fuel consumption of the vehicle,
as well as the emissions of pollutants and noise.

Hence, to select a driving cycle, you can use the following syntax:

.. code-block:: python

   tm = TruckModel(array, cycle='Urban delivery')

Range
*****

``carculator_truck`` designs the energy storage units (battery, fuel cell, etc.) to cover a given range autonomy of the vehicle.
By default, the range autonomy of the trucks is set to:

* 150 km, when the Urban delivery cycle is selected
* 400 km, when the Regional delivery cycle is selected
* 800 km, when the Long haul cycle is selected

This range can be changed by the user, using the following syntax:

.. code-block:: python

   tm = TruckModel(array, target_range=200)

Cargo load
**********

The cargo load of the trucks is, by default, dependent
on the driving cycle and size of the truck (in kilograms):

  Urban delivery:
    3.5t: 750
    7.5t: 1750
    18t: 2700
    26t: 6300
    32t: 8755
    40t: 8755
    60t: 16400

  Regional delivery:
    3.5t: 750
    7.5t: 1750
    18t: 3200
    26t: 6300
    32t: 10300
    40t: 10300
    60t: 19300

  Long haul:
    3.5t: 1125
    7.5t: 2625
    18t: 7400
    26t: 13400
    32t: 13800
    40t: 13800
    60t: 19300

These can be changed by the user, using the following syntax:

.. code-block:: python

    custom_load = {
        "Long haul": {
            "32t": 10000,
        }
    }

    tm = TruckModel(array, payload=custom_load)

Energy consumption
******************

The energy consumption of the trucks is calculated using the driving cycle and the cargo load.
But, it can also be provided directly by the user, using the following syntax,
in kilojoules per km (kJ/km):

.. code-block:: python

    custom_consumption = {
        ("BEV", "26t", 2020): 23000,
        ("BEV", "32t", 2020): 23000,
        ("BEV", "40t", 2020): 23000,
        ("BEV", "60t", 2020): 23000,
    }

    tm = TruckModel(array, energy_consumption=custom_consumption)

Custom values for given parameters
**********************************

You can pass your own values for the given parameters, effectively overriding the default values.

For example, you may think that the *base mass of the glider* (meaning frame) for 7.5t truck is 2000 kg in 2020,
and not what is initially defined by the default values. It is easy to change this value.

.. code-block:: python

    cip = CarInputParameters()
    cip.static()
    dcts, array = fill_xarray_from_input_parameters(cip)
    array.loc[{'size': '7.5t', 'year': 2020, 'parameter': 'glider base mass'}] = 2000
    cm = CarModel(array, cycle='WLTC')
    cm.set_all()

Alternatively, instead of a Python dictionary, you can pass a file path pointing to an Excel spreadsheet that contains
the values to change, following `this template <https://github.com/romainsacchi/carculator_truck/raw/master/docs/template_workbook.xlsx>`_.

The following probability distributions are accepted:
* "triangular"
* "lognormal"
* "normal"
* "uniform"
* "none"

Inter and extrapolation of parameters
*************************************

``carculator_truck`` creates by default vehicle models for the year 2000, 2010, 2020, 2040 and 2050.
It is possible to inter and extrapolate all the parameters to other years simply by writing:

.. code-block:: python

    array = array.interp(year=[2018, 2022, 2035, 2040, 2045, 2050],  kwargs={'fill_value': 'extrapolate'})

However, we do not recommend extrapolating for years before 2000 or beyond 2050.

Accessing calculated parameters of the truck model
**************************************************

Hence, the tank-to-wheel energy requirement per km driven per powertrain technology
for a 7.5t electric truck in 2020 can be obtained from the TruckModel object
(only possible after calling :meth:`tm.set_all()`):

.. code-block:: python

    TtW_energy = tm.array.sel(size='7.5t', year=2020, parameter='TtW energy')


Note that if you call the :meth:`stochastic` method of the :class:`CarInputParameters`, you would have
several values stored for a given calculated parameter in the array.
The number of values correspond to the number of iterations
you passed to :meth:`stochastic`.


Any other attributes of the TruckModel class can be obtained in a similar way.
Hence, the following code lists all direct exhaust emissions included in the
inventory of an 32t diesel truck in 2030:

List of all the given and calculated parameters of the car model:

.. code-block:: python

    list_param = tm.array.coords['parameter'].values.tolist()

Return the parameters concerned with direct exhaust emissions
(we remove noise emissions):

.. code-block:: python

    direct_emissions = [x for x in list_param if 'emission' in x and 'noise' not in x]

Finally, return their values and display the first 10 in a table:

.. code-block:: python

    tm.array.sel(parameter=direct_emissions, year=2030, size='32t', powertrain='ICEV-d').to_dataframe(name='direct emissions')



Or we could be interested in visualizing the distribution of
non-characterized noise emissions, in joules:

.. code-block:: python

    noise_emissions = [x for x in list_param if 'noise' in x]
    data = tm.array.sel(parameter=noise_emissions, year=2030, size='32t', powertrain='ICEV-d', value=0)\
        .to_dataframe(name='noise emissions')['noise emissions']
    data[data>0].plot(kind='bar')
    plt.ylabel('joules per km')
    plt.show()


Characterization of inventories (static)
****************************************

``carculator_truck`` makes the characterization of inventories easy. You can characterize the inventories directly from
``carculator_truck`` against midpoint impact assessment methods.

For example, to obtain characterized results against the midpoint impact assessment method ReCiPe for all cars:

.. code-block:: python

    ic = InventoryCalculation(tm)
    results = ic.calculate_impacts()


Hence, to plot the carbon footprint for all diesel trucks in 2020:

.. code-block:: python

    results.sel(powertrain="ICEV-d",
                year=2020,
                impact_category='climate change',
                value=0).to_dataframe('impact').unstack(level=1)['impact'].plot(kind='bar',
                stacked=True)
    plt.ylabel('kg CO2-eq./tkm')
    plt.show()



Note that, for now, only the ReCiPe 2008 v.1.13 and ILCD 2018 methods
are available for midpoint characterization.
Also, once the instance of the :class:`TruckModel`
class has been created, there is no need to re-create it
in order to calculate additional environmental impacts (unless you wish to
change values of certain input or calculated parameters,
the driving cycle or go from static to stochastic mode).

Characterization of inventories (stochastic)
********************************************

In the same manner, you can obtain distributions of results,
instead of one-point values if you have run the model in
stochastic mode (with 500 iterations and the driving cycle Long haul).

.. code-block:: python

    tip = TruckInputParameters()
    tip.stochastic(500)
    scope = {
        'powertrain':['BEV', 'PHEV-d'],
    }
    dcts, array = fill_xarray_from_input_parameters(tip, scope=scope)
    tm = TruckModel(array, cycle='WLTC')
    tm.set_all()

    ic = InventoryCalculation(tm)
    results = ic.calculate_impacts()

    data_MC = results.sel(impact_category='climate change').sum(axis=3).to_dataframe('climate change')
    plt.style.use('seaborn')
    data_MC.unstack(level=[0,1,2]).boxplot(showfliers=False, figsize=(20,5))
    plt.xticks(rotation=70)
    plt.ylabel('kg CO2-eq./tkm')
    plt.show()


Many other examples are described in a Jupyter Notebook in the ``examples`` folder.

Export of inventories (static)
******************************

Inventories can be exported as:
    * a Python list of exchanges
    * a Brightway2 bw2io.importers.base_lci.LCIImporter object, ready to be imported in a Brigthway2 environment
    * an Excel file, to be imported in a Brigthway2 environment
    * a CSV file, to be imported in SimaPro 9.x.

.. code-block:: python

    ic = InventoryCalculation(tm)

    # export the inventories as a Python list
    mylist = ic.export_lci()
    # export the inventories as a Brightway2 object
    import_object = ic.export_lci_to_bw()
    # export the inventories as an Excel file (returns the file path of the created file)
    filepath = ic.export_lci_to_excel(software_compatibility="brightway2", ecoinvent_version="3.8")
    filepath = ic.export_lci_to_excel(software_compatibility="simapro", ecoinvent_version="3.6")


Import of inventories (static)
******************************

The inventories will link to the ecoinvent database.

.. code-block:: python

    import brightway2 as bw
    bw.projects.set_current("test_carculator")
    import bw2io
    fp = r"C:\file_path_to_the_inventory\lci-test.xlsx"

    i = bw2io.ExcelImporter(fp)
    i.apply_strategies()

    i.match_database(fields=('name', 'unit', 'location'))
    i.match_database("name_of_the_ecoinvent_db", fields=('name', 'unit', 'location', 'reference product'))
    i.match_database("biosphere3", fields=('name', 'unit', 'categories'))

    i.statistics()

    # if there are some unlinked biosphere flows (e.g., noise) left
    i.add_unlinked_flows_to_biosphere_database()

    i.write_database()
