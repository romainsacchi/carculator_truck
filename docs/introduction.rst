Introduction
============

``carculator_truck`` is a parameterized model that allows to generate and characterize life cycle inventories for different
heavy goods vehicle configurations, according to selected:

* powertrain technologies (9): diesel engine, electric motor, hybrid, plugin-hybrid, etc.,
* year of operation (2): 2000, 2010, 2020, 2030, 2040 and 2050 (with the possibility to interpolate in between)
* and sizes: 3.5t, 7.5t, 18t, 26t, 40t and 60t

The methodology used to develop `carculator_truck` is explained in:
cDoes size matter? The influence of loading factor, trip length and application type on the Life Cycle Assessment of current and future heavy goods vehicles.
Romain Sacchi, Christian Bauer
(2020, in preparation)

At the moment, the tool has a focus on the transport of dry goods.

More specifically, ``carculator_truck`` generates `Brightway2 <https://brightwaylca.org/>`_ inventories, but also directly provides characterized
results against several midpoint and endpoint indicators from the impact assessment method ReCiPe 2008 and ILCD 2.0 2018 as well as life cycle cost indicators.

``carculator_truck`` is a special in the way that it uses time- and energy-scenario-differentiated background inventories for the future,
resulting from the coupling between the `ecoinvent 3.6 database <https://ecoinvent.org>`_ and the scenario outputs of PIK's
integrated assessment model `REMIND <https://www.pik-potsdam.de/research/transformation-pathways/models/remind/remind>`_.
This allows to perform prospective study while consider future expected changes in regard to the production of electricity,
cement, steel, heat, etc.

Objective
---------

The objective is to produce life cycle inventories for vehicles in a transparent, comprehensive and quick manner,
to be further used in prospective LCA of transportation technologies.

Why?
----

Many life cycle assessment (LCA) models of transport vehicles exist. Yet, because LCA of vehicles, particularly for electric battery vehicles,
are sensitive to assumptions made in regards to electricity mix used for charging, lifetime of the battery, load factor, trip length, etc., it has led
to mixed conclusions being published in the scientific literature. Because the underlying calculations are kept undocumented,
it is not always possible to explain the disparity in the results given by these models, which can contribute to adding confusion among the public.

Because ``carculator_truck`` is kept **as open as possible**, the methods and assumptions behind the generation of results are
easily identifiable and adjustable.
Also, there is an effort to keep the different modules (classes) separated, so that improving certain areas of the model is relatively
easy and does not require changing extensive parts of the code. In that regard, contributions are welcome.

Finally, beside being more flexible and transparent, ``carculator_truck`` provides interesting features, such as:

* a stochastic mode, that allows fast Monte Carlo analyses, to include uncertainty at the vehicle level
* possibility to override any or all of the 200+ default input vehicle parameters (e.g., load factor, drag coefficient) but also calculated parameters (e.g., driving mass).
* hot pollutants emissions as a function of the driving cycle, using `HBEFA <https://www.hbefa.net/e/index.html>`_ 4.1 data, further divided between rural, suburban and urban areas
* noise emissions, based on `CNOSSOS-EU <https://ec.europa.eu/jrc/en/publication/reference-reports/common-noise-assessment-methods-europe-cnossos-eu>`_ models for noise emissions and `Noise footprint from personal land‐based mobility by Cucurachi, et al (2019) <https://onlinelibrary.wiley.com/doi/full/10.1111/jiec.12837>`_ for inventory modelling and mid- and endpoint characterization of noise emissions, function of driving cycle and further divided between rural, suburban and urban areas
* export of inventories as an Excel file, to be used with Brightway2 or Simapro (in progress), including uncertainty information. This requires the user to have `ecoinvent 3.6 cutoff` installed on the LCA software the car inventories are exported to.
* export inventories directly into Brightway2, as a LCIImporter object to be registered. Additionally, when run in stochastic mode, it is possible to export arrays of pre-sampled values using the `presamples <https://pypi.org/project/presamples/>`_ library to be used together with the Monte Carlo function of Brightway2.
* development of an online graphical user interface (in progress): `carculator online <https://carculator.psi.ch>`_

How to install this package?
----------------------------

``carculator_truck`` is a Python package, and is primarily to be used from within a Python 3.x environment.
Because ``carculator_truck`` is still at an early development stage, it is a good idea to install it in a separate environment,
such as a conda environment::

    conda create -n <name of the environment> python=3.7

Once your environment created, you should activate it::

    conda activate <name of the environment>

And install the ``carculator_truck`` library in your new environment via Conda::

    pip install carculator_truck

This will install the package and the required dependencies.

How to use it?
--------------

Static vs. Stochastic mode
**************************

Note: many examples are given in this `notebook <https://github.com/romainsacchi/carculator_truck/blob/master/examples/Examples.ipynb>`_ that you can run directly on your computer..

The inventories can be calculated using the most likely value of the given input parameters ("static" mode), but also using
randomly-generated values based on a probability distribution for those ("stochastic" mode).



Custom values for given parameters
**********************************



Inter and extrapolation of parameters
*************************************

``carculator_truck`` creates by default truck models for the year 2000, 2010, 2020, 2030, 2040 and 2050.
It is possible to inter and extrapolate all the parameters to other years simply by writing:

.. code-block:: python

    array = array.interp(year=[2018, 2022, 2035, 2042, 2045, 2048],  kwargs={'fill_value': 'extrapolate'})

However, we do not recommend extrapolating for years before 2000 or beyond 2050.

Changing the driving cycle
**************************

``carculator_truck`` gives the user the possibility to choose between three standarddriving cycles, extracted from the software VECTO.
Driving cycles are determinant in many aspects of the truck model: hot pollutant emissions, noise emissions, tank-to-wheel energy, etc.
Hence, each driving cycle leads to slightly different results. By default, if no driving cycle is specified, the "Urban delivery" driving cycle is used.

Accessing calculated parameters of the car model
************************************************
Hence, the tank-to-wheel energy requirement per km driven per powertrain technology for a 7.5t truck in 2020 can be obtained
from the TruckModel object:

.. code-block:: python

    TtW_energy = tm.array.sel(size='7.5t', year=2020, parameter='TtW energy', value=0) * 1/3600 * 100

    plt.bar(TtW_energy.powertrain, TtW_energy)
    plt.ylabel('kWh/100 km')
    plt.show()



Note that if you call the :meth:`stochastic` method of the :class:`TruckInputParameters`, you would have several values stored for a given calculated parameter
in the array. The number of values correspond to the number of iterations you passed to :meth:`stochastic`.

For example, if you ran the model in stochastic mode with 800 iterations as shown in the section above, instead of one
value for the tank-to-wheel energy, you would have a distribution of values:

.. code-block:: python

    l_powertrains = TtW_energy.powertrain
    [plt.hist(e, bins=50, alpha=.8, label=e.powertrain.values) for e in TtW_energy]
    plt.ylabel('kWh/100 km')
    plt.legend()



Any other attributes of the TruckModel class can be obtained in a similar way.
Hence, the following code lists all direct exhaust emissions included in the inventory of an truck in 2020:

List of all the given and calculated parameters of the truck model:

.. code-block:: python

    list_param = tm.array.coords['parameter'].values.tolist()

Return the parameters concerned with direct exhaust emissions (we remove noise emissions):

.. code-block:: python

    direct_emissions = [x for x in list_param if 'emission' in x and 'noise' not in x]

Finally, return their values and display the first 10 in a table:

.. code-block:: python

    tm.array.sel(parameter=direct_emissions, year=2020, size='7.5t', powertrain='BEV').to_dataframe(name='direct emissions')



Or we could be interested in visualizing the distribution of non-characterized noise emissions, in joules:

.. code-block:: python

    noise_emissions = [x for x in list_param if 'noise' in x]
    data = tm.array.sel(parameter=noise_emissions, year=2020, size='7.5t', powertrain='ICEV-d', value=0)\
        .to_dataframe(name='noise emissions')['noise emissions']
    data[data>0].plot(kind='bar')
    plt.ylabel('joules per km')



Modify calculated parameters
****************************

As input parameters, calculated parameters can also be overridden. For example here, we override the `driving mass`
of 40t diesel truck for 2010 and 2020:

.. code-block:: python

    cm.array.loc['40t','ICEV-d', 'driving mass', [2010, 2020]] = [[25000],[27000]]

Characterization of inventories (static)
****************************************

``carculator_truck`` makes the characterization of inventories easy. You can characterize the inventories directly from
``carculator_truck`` against midpoint and endpoint impact assessment methods.

For example, to obtain characterized results against the midpoint impact assessment method ReCiPe 2008 for all vehicles:

.. code-block:: python

    ic = InventoryCalculation(tm.array, fuel_blend=tm.fuel_blend, country=tm.country)
    results = ic.calculate_impacts()


Hence, to plot the carbon footprint for all 40t trucks in 2020:

.. code-block:: python

    results.sel(size='40t', year=2020, impact_category='climate change', value=0)\
        .to_dataframe('impact').unstack(level=1)['impact'].plot(kind='bar', stacked=True)
    plt.ylabel('kg CO2-eq./ton-km')
    plt.show()



Note that, for now, only the ReCiPe 2008 and ILCD 2.0 methods are available for midpoint characterization. Also, once the instance of the :class:`CarModel`
class has been created, there is no need to re-create it in order to calculate additional environmental impacts (unless you wish to
change values of certain input or calculated parameters, the driving cycle or go from static to stochastic mode).

Characterization of inventories (stochastic)
********************************************

In the same manner, you can obtain distributions of results, instead of one-point values if you have run the model in
stochastic mode (with 500 iterations and the driving cycle "Regional delivery").

.. code-block:: python

    tip = TruckInputParameters()
    tip.stochastic(500)
    dcts, array = fill_xarray_from_input_parameters(cip)
    tm = TruckModel(array, cycle='Regional delivery')
    tm.set_all()
    scope = {
        'powertrain':['BEV', 'PHEV-d'],
    }
    ic = InventoryCalculation(tm.array, scope=scope)

    results = ic.calculate_impacts()

    data_MC = results.sel(impact_category='climate change').sum(axis=3).to_dataframe('climate change')
    plt.style.use('seaborn')
    data_MC.unstack(level=[0,1,2]).boxplot(showfliers=False, figsize=(20,5))
    plt.xticks(rotation=70)
    plt.ylabel('kg CO2-eq./ton-km')



Many other examples are described in a Jupyter Notebook in the ``examples`` folder.

Export of inventories (static)
******************************

Inventories can be exported as:
    * a Python list of exchanges
    * a Brightway2 bw2io.importers.base_lci.LCIImporter object, ready to be imported in a Brigthway2 environment
    * an Excel file, to be imported in a Brigthway2 environment

.. code-block:: python

    ic = InventoryCalculation(tm.array)

    # export the inventories as a Python list
    mylist = ic.export_lci()
    # export the inventories as a Brightway2 object
    import_object = ic.export_lci_to_bw()
    # export the inventories as an Excel file (returns the file path of the created file)
    filepath = ic.export_lci_to_excel()

Export of inventories (stochastic)
**********************************

If you had run the model in stochastic mode, the export functions return in addition an array that contains pre-sampled values
for each parameter of each car, in order to perform Monte Carlo analyses in Brightway2.

.. code-block:: python

    ic = InventoryCalculation(tm.array)

    # export the inventories as a Python list
    mylist, presamples_arr = ic.export_lci()
    # export the inventories as a Brightway2 object
    import_object, presamples_arr = ic.export_lci_to_bw()
    # export the inventories as an Excel file (note that this method does not return the presamples array)
    filepath = ic.export_lci_to_excel()

Import of inventories (static)
******************************

The background inventory is originally a combination between ecoinvent 3.6 and outputs from PIK's REMIND model.
Outputs from PIK's REMIND are used to project expected progress in different sectors into ecoinvent. For example, the efficiency
of electricity-producing technologies as well as the electricity mixes in the future for the main world regions
are built upon REMIND outputs.
The library used to create hybrid versions of the ecoinvent database from PIK's REMIND is called `rmnd_lca <https://github.com/romainsacchi/rmnd-lca>`_.
This means that, as it is, the inventory cannot properly link to ecoinvent 3.6 unless some transformation is performed
before. These transformations are in fact performed by default when exporting the inventory. Hence, when doing:

.. code-block:: python

    ic.export_lci_to_excel()

the resulting inventory should properly link to ecoinvent 3.6. Should you wish to export an inventory to link with a
REMIND-modified version of ecoinvent, just export the inventory with the `ecoinvent_compatibility` argument
set to `False`.

.. code-block:: python

    ic.export_lci_to_excel(ecoinvent_compatibility=False)

In that case, the inventory will only link to a custom ecoinvent database produced by `rmnd_lca`.

But in any case, the following script should successfully import the inventory:

.. code-block:: python

    import brightway2 as bw
    bw.projects.set_current("test_carculator")
    import bw2io
    fp = r"C:\file_path_to_the_inventory\lci-test.xlsx"

    i = bw2io.ExcelImporter(fp)
    i.apply_strategies()

    if 'additional_biosphere' not in bw.databases:
        i.create_new_biosphere('additional_biosphere')
    i.match_database("name_of_the_ecoinvent_db", fields=('name', 'unit', 'location', 'reference product'))
    i.match_database("biosphere3", fields=('name', 'unit', 'categories'))
    i.match_database("additional_biosphere", fields=('name', 'unit', 'categories'))
    i.match_database(fields=('name', 'unit', 'location'))

    i.statistics()
    i.write_database()
