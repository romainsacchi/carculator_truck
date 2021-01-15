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

More specifically, ``carculator_truck`` generates `Brightway2 <https://brightwaylca.org/>`_ and
`SimaPro <https://www.simapro.com/>`_ compatible inventories, but also directly provides characterized results against
several midpoint and endpoint indicators from the impact assessment method:
* ReCiPe 2008 (mid- and endpoint)
* and ILCD 2.0 2018 (only midpoint)

as well as life cycle cost indicators.

``carculator_truck`` differentiates itself from other truck LCA models as it uses time- and energy-scenario-differentiated
background inventories for the future, resulting from the coupling between the `ecoinvent database <https://ecoinvent.org>`_
and the scenario outputs of PIK's integrated assessment model `REMIND <https://www.pik-potsdam.de/research/transformation-pathways/models/remind/remind>`_,
using the `premise <https://github.com/romainsacchi/premise>`_ library.
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
* export of inventories as an Excel file, to be used with Brightway2 or Simapro 9, including uncertainty information. This requires the user to have `ecoinvent 3.6 cutoff` installed on the LCA software the car inventories are exported to.
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

    conda install -c romainsacchi carculator_truck

This will install the package and the required dependencies.

Or a stable release from Pypi::

    pip install carculator_truck

How to update this package?
---------------------------

Within the conda environment, type::

    conda update carculator_truck

Or from Pypi using pip::

    pip install carculator_truck --upgrade

How to use it?
--------------

Note: many examples are given in this `notebook <https://github.com/romainsacchi/carculator_truck/blob/master/examples/Examples.ipynb>`_ that you can run directly on your computer..

Static vs. Stochastic mode vs. Sensitivity mode
***********************************************

The inventories can be calculated using the most likely value of the given input parameters ("static" mode), but also using
randomly-generated values based on a probability distribution for those ("stochastic" mode). Additionally, the tool can run
one-at-a-time sensitivity analyses by quantifying the effect of incrementing each input parameter value by 10% on the end-results.

Retrospective and Prospective analyses
**************************************

By default, the tool produces results across thea year 2000, 2010, 2020, 2030, 2040 and 2050.
It does so by adjusting efficiencies at the vehicle level, but also by adjusting certain aspects of the background inventories.
The latter is done by linking the vehicles' inventories to energy scenario-specific ecoinvent databases produced by ``premise``.

Export of inventories
*********************

The library allows to export inventories in different formats, to be consumed by different tools and link to various databases.
Among the formats available, ``carculator_truck`` can export inventories as:

* Brightway2-compatible Excel file
* Simapro-compatible CSV file
* Brightway2 LCIImporter object
* Python dictionary

The inventories cna be made compatible for:
* ecoinvent 3.5 and 3.6, cut-off
* REMIND-ecoinvent produced with ``premise``
* UVEK-ecoinvent 2.2 database
