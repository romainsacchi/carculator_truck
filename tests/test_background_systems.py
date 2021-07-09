from carculator_truck.background_systems import BackgroundSystemModel


def test_size_dictionary():
    bs = BackgroundSystemModel()
    assert len(bs.electricity_mix) == 90
    assert int(bs.electricity_mix.sel(country="FR").values.sum()) == 10
    assert int(bs.electricity_mix.sel(country="FR", year=2015).values.sum()) == 1


def test_cumulative_losses():
    bs = BackgroundSystemModel()
    assert len(bs.losses) == 146
    assert float(bs.losses["AL"]["LV"]) > 1.1


def test_sulfur_content():
    # The sulfur content in European countries should be by law lower than 10 ppm in 2020
    bs = BackgroundSystemModel()
    sulfur = bs.sulfur

    assert sulfur.sel(country="CZ", year=2020, fuel="diesel") <= 10 / 1e6
