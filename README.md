# ``carculator_truck``

<p align="center">
  <img style="height:130px;" src="https://github.com/romainsacchi/coarse/raw/master/docs/mediumsmall.png">
</p>


<p align="center">
  <a href="https://badge.fury.io/py/carculator-truck" target="_blank"><img src="https://badge.fury.io/py/carculator-truck.svg"></a>
  <a href="https://github.com/romainsacchi/carculator_truck" target="_blank"><img src="https://github.com/romainsacchi/carculator_truck/actions/workflows/main.yml/badge.svg?branch=master"></a>
  <a href="https://ci.appveyor.com/project/romainsacchi/carculator_truck" target="_blank"><img src="https://ci.appveyor.com/api/projects/status/github/romainsacchi/carculator_truck?svg=true"></a>
  <a href="https://coveralls.io/github/romainsacchi/carculator_truck" target="_blank"><img src="https://coveralls.io/repos/github/romainsacchi/carculator_truck/badge.svg"></a>
  <a href="https://carculator_truck.readthedocs.io/en/latest/" target="_blank"><img src="https://readthedocs.org/projects/carculator_truck/badge/?version=latest"></a>
 </p>

Prospective environmental and economic life cycle assessment of medium and heavy duty vehicles.

A fully parameterized Python model developed by the [Technology Assessment group](https://www.psi.ch/en/ta) of the
[Paul Scherrer Institut](https://www.psi.ch/en) to perform life cycle assessments (LCA) of medium and heavy duty trucks.
Based on the Life Cycle Assessment tool for passenger vehicles [carculator](https://github.com/romainsacchi/carculator).

See [the documentation](https://carculator_truck.readthedocs.io/en/latest/index.html) for more detail, validation, etc.

The model has been the subject of a submission to the journal <i>Environmental Science and Technology</i>.

[1] Sacchi R, Bauer C, Cox BL. Does Size Matter? The Influence of Size, Load Factor, Range Autonomy, and Application Type on the Life Cycle Assessment of Current and Future Medium and Heavy-Duty Vehicles.
Environ Sci Technol 2021. [https://doi.org/10.1021/acs.est.0c07773](https://doi.org/10.1021/acs.est.0c07773).

## How to install?

For the latest version, using conda::

    conda install -c romainsacchi carculator_truck

or for a stable release, from Pypi::

    pip install carculator_truck


## What does it do?

<i>carculator_truck</i> allows to model vehicles across:
<ul>
<li>different conventional and alternative powertrains: diesel, compressed natural gas, hybrid-diesel, plugin hybrid, electric, fuel cell</li>
<li>different gross weight cateogries: 3.5t, 7.5t, 18t, 26t, 32t, 40t and 60t</li>
<li>different fuel pathways: conventional fuels, bio-based fuels (biodiesel, biomethane), synthetic fuels
(Fischer-Tropsch-based synthetic diesel, synhtetic methane)</li>
<li>different years: from 2000 to 2050. Technological progress at the vehicle level but also in the rest of the world energy
system (e.g., power generation) is accounted for, using energy scenario-specific IAM-coupled ecoinvent databases produced by
<a href="https://github.com/romainsacchi/premise" target="_blank">premise</a>.</li>
<li>Inventories can be imported into <a href="https://brightway.dev/" target="_blank">Brightway2</a> and
<a href="https://www.simapro.com/" target="_blank">SimaPro 9.x.</a>.</li>
</ul>

<p align="center">
    The energy model of <i>carculator_truck</i> considers the vehicle aerodynamics, the road gradient and other factors.
    It also considers varying efficiencies of the transmission and engine at various load points for each second
    of the driving cycle.
  <img style="height:50px;" src="https://github.com/romainsacchi/carculator_truck/raw/master/docs/energy_model.png">
</p>

<p align="center">
    The energy model and the calculated tank-to-wheel energy consumption is validated against the simulation software
    <a href="https://ec.europa.eu/clima/policies/transport/vehicles/vecto_en" target="_blank">VECTO</a>.
  <img style="height:50px;" src="https://github.com/romainsacchi/carculator_truck/raw/master/docs/vecto_validation.png">
</p>

<p align="center">
    Benefits of hybrid powertrains are fully conidered: the possibility to recuperate braking energy as well as efficiency gains from engine
    downsizing is accounted for.
  <img style="height:50px;" src="https://github.com/romainsacchi/carculator_truck/raw/master/docs/hybrid_efficiency.png">
</p>

<p align="center">
    Global warming potential impacts per ton-km for a 40-t truck, across different powertrain technologies,
    using an urban driving cycle.
  <img style="height:50px;" src="https://github.com/romainsacchi/carculator_truck/raw/master/docs/urban_gwp.png">
</p>

## How to use it?

See the notebook with [examples](https://github.com/romainsacchi/carculator_truck/blob/master/examples/Examples.ipynb).

## Support

Do not hesitate to contact the development team at [carculator@psi.ch](mailto:carculator@psi.ch).

## Maintainers

* [Romain Sacchi](https://github.com/romainsacchi)
* [Chris Mutel](https://github.com/cmutel/)

## Contributing

See [contributing](https://github.com/romainsacchi/carculator_truck/blob/master/CONTRIBUTING.md).

## License

[BSD-3-Clause](https://github.com/romainsacchi/carculator_truck/blob/master/LICENSE). Copyright 2020 Paul Scherrer Institut.
