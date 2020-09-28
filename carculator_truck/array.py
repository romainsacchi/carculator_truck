from .truck_input_parameters import TruckInputParameters as t_i_p
import numpy as np
import pandas as pd
import stats_arrays as sa
import xarray as xr


def fill_xarray_from_input_parameters(tip, sensitivity=False):
    """Create an `xarray` labeled array from the sampled input parameters.


    This function extracts the parameters' names and values contained in the
    `parameters` attribute of the :class:`CarInputParameters` class in :mod:`car_input_parameters` and insert them into a
    multi-dimensional numpy-like array from the *xarray* package
    (http://xarray.pydata.org/en/stable/).


    :param sensitivity:
    :param tip: Instance of the :class:`TruckInputParameters` class in :mod:`truck_input_parameters`.
    :returns: `tuple`, `xarray.DataArray`
    - tuple (`size_dict`, `powertrain_dict`, `parameter_dict`, `year_dict`)
    - array

    Dimensions of `array`:

        0. Vehicle size, e.g. "3.5t", "7.5t", etc. str.
        1. Powertrain, e.g. "ICE-d", "BEV". str.
        2. Year. int.
        3. Samples.

    """

    # Check whether the argument passed is an instance of :class:`TruckInputParameters`
    if not isinstance(tip, t_i_p):
        raise TypeError(
            "The argument passed is not an object of the TruckInputParameter class"
        )
    # if the purpose is not to do a sensitivity analysis
    # the dimension `value` of the array is as large as the number of iterations to perform
    # that is, 1 in `static` mode, or several in `stochastic` mode.
    if not sensitivity:
        array = xr.DataArray(
            np.zeros(
                (
                    len(tip.sizes),
                    len(tip.powertrains),
                    len(tip.parameters),
                    len(tip.years),
                    tip.iterations or 1,
                )
            ),
            coords=[
                tip.sizes,
                tip.powertrains,
                tip.parameters,
                tip.years,
                np.arange(tip.iterations or 1),
            ],
            dims=["size", "powertrain", "parameter", "year", "value"],
        ).astype("float32")
    # if the purpose is ot do a sensitivity analysis
    # then the length of the dimensions `value` equals the number of parameters
    else:
        params = ["reference"]
        params.extend([a for a in tip.input_parameters])
        array = xr.DataArray(
            np.zeros(
                (
                    len(tip.sizes),
                    len(tip.powertrains),
                    len(tip.parameters),
                    len(tip.years),
                    len(params),
                )
            ),
            coords=[tip.sizes, tip.powertrains, tip.parameters, tip.years, params, ],
            dims=["size", "powertrain", "parameter", "year", "value"],
        ).astype("float32")

    size_dict = {k: i for i, k in enumerate(tip.sizes)}
    powertrain_dict = {k: i for i, k in enumerate(tip.powertrains)}
    year_dict = {k: i for i, k in enumerate(tip.years)}
    parameter_dict = {k: i for i, k in enumerate(tip.parameters)}

    if not sensitivity:
        for param in tip:
            # try:
            array.loc[
                dict(
                    powertrain=tip.metadata[param]["powertrain"],
                    size=tip.metadata[param]["sizes"],
                    year=tip.metadata[param]["year"],
                    parameter=tip.metadata[param]["name"],
                )
            ] = tip.values[param]

    else:
        # if `sensitivity` == True, the values of each parameter is
        # incremented by 10% when `value` == `parameter`
        for param in tip.input_parameters:
            names = [n for n in tip.metadata if tip.metadata[n]["name"] == param]

            for name in names:
                vals = [
                    tip.values[name] for _ in range(0, len(tip.input_parameters) + 1)
                ]
                vals[tip.input_parameters.index(param) + 1] *= 1.1

                array.loc[
                    dict(
                        powertrain=tip.metadata[name]["powertrain"],
                        size=tip.metadata[name]["sizes"],
                        year=tip.metadata[name]["year"],
                        parameter=tip.metadata[name]["name"],
                    )
                ] = vals

    return (size_dict, powertrain_dict, parameter_dict, year_dict), array


def modify_xarray_from_custom_parameters(fp, array):
    """
    Override default parameters values in `xarray` based on values provided by the user.

    This function allows to override one or several default parameter values by providing either:

        * a file path to an Excel workbook that contains the new values
        * or a dictionary

    The dictionary must be of the following format:

    .. code-block:: python

            {
                (parameter category,
                    powertrain,
                    size,
                    parameter name,
                    uncertainty type): {
                                        (year, 'loc'): value,
                                        (year, 'scale'): value,
                                        (year, 'shape'): value,
                                        (year, 'minimum'): value,
                                        (year, 'maximum'): value
                }

            }

    For example:

    .. code-block:: python

            {
                ('Driving',
                'all',
                'all',
                'lifetime kilometers',
                'none'): {
                    (2018, 'loc'): 150000, (2040, 'loc'): 150000
                    }

            }

    Or:

    .. code-block:: python

            {
                ('Driving',
                ('3.5t','7.5t'),
                ('ICEV-d','FCEV'),
                'lifetime kilometers',
                'none'): {
                    (2018, 'loc'): 150000, (2040, 'loc'): 150000
                    }

            }

    :param array:
    :param fp: File path of workbook with new values or dictionary.
    :type fp: str or dict

    """

    # If a string is passed, then it is a file path to an Excel file
    # if not, then it is directly the dictionary
    if isinstance(fp, str):
        try:
            d = pd.read_excel(
                fp,
                header=[0, 1],
                index_col=[0, 1, 2, 3, 4],
                sheet_name="Custom_parameters",
            ).to_dict(orient="index")
        except:
            raise FileNotFoundError("Custom parameters file not found.")
    elif isinstance(fp, dict):
        d = fp
    else:
        print("The format passed as parameter is not valid.")
        raise

    # Parameters for these categories are ignored and cannot be modified here.
    FORBIDDEN_KEYS = ["Driving cycle", "Background", "Functional unit"]

    for k in d:
        if k[0] not in FORBIDDEN_KEYS:
            if not isinstance(k[1], str):
                pt = [p.strip() for p in k[1] if p]
                pt = [p for p in pt if p]
                pt = list(pt)
            elif k[1] == "all":
                pt = array.coords["powertrain"].values
            else:
                if k[1] in array.coords["powertrain"].values:
                    pt = [k[1]]
                else:
                    print(
                        "{} is not a recognized powertrain. It will be skipped.".format(
                            k[1]
                        )
                    )
                    continue

            # if a sequence of sizes is passed
            if not isinstance(k[2], str):
                sizes = [s.strip() for s in k[2] if s]
                sizes = [s for s in sizes if s]
                sizes = list(sizes)
            # of if it concerns all sizes
            elif k[2] == "all":
                sizes = array.coords["size"].values
            # of if one size is passed, as a string
            else:
                if k[2] in array.coords["size"].values:
                    sizes = [k[2]]

                # if the size class is not among the available size classes
                else:
                    print(
                        "{} is not a recognized size category. It will be skipped.".format(
                            k[2]
                        )
                    )
                    continue
            param = k[3]

            # if `parameter` is not among the existing parameters
            if not param in array.coords["parameter"].values:
                print(
                    "{} is not a recognized parameter. It will be skipped.".format(
                        param
                    )
                )
                # we skip it and inform the user
                continue

            val = d[k]

            distr_dic = {
                "triangular": 5,
                "lognormal": 2,
                "normal": 3,
                "uniform": 4,
                "none": 1,
            }
            distr = distr_dic[k[4]]

            year = set([v[0] for v in val])

            # Stochastic mode
            if array.sizes["value"] > 1:
                for y in year:
                    # No uncertainty parameters given
                    if distr == 1:
                        # There should be at least a `loc`
                        if ~np.isnan(val[(y, "loc")]):
                            for s in sizes:
                                for p in pt:
                                    array.loc[
                                        dict(
                                            powertrain=p,
                                            size=s,
                                            year=y,
                                            parameter=param,
                                        )
                                    ] = val[(y, "loc")]
                        # Otherwise warn
                        else:
                            print(
                                "`loc`parameter missing for {} in {}.".format(param, y)
                            )
                            continue

                    elif distr in [2, 3, 4, 5]:

                        # Check if the correct parameters are present
                        # Triangular

                        if distr == 5:
                            if (
                                    np.isnan(val[(y, "loc")])
                                    or np.isnan(val[(y, "minimum")])
                                    or np.isnan(val[(y, "maximum")])
                            ):
                                print(
                                    "One or more parameters for the triangular distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        # Lognormal
                        if distr == 2:
                            if np.isnan(val[(y, "loc")]) or np.isnan(val[(y, "scale")]):
                                print(
                                    "One or more parameters for the lognormal distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        # Normal
                        if distr == 3:
                            if np.isnan(val[(y, "loc")]) or np.isnan(val[(y, "scale")]):
                                print(
                                    "One or more parameters for the normal distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        # Uniform
                        if distr == 4:
                            if np.isnan(val[(y, "minimum")]) or np.isnan(
                                    val[(y, "maximum")]
                            ):
                                print(
                                    "One or more parameters for the uniform distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        a = sa.UncertaintyBase.from_dicts(
                            {
                                "loc": val[y, "loc"],
                                "scale": val[y, "scale"],
                                "shape": val[y, "shape"],
                                "minimum": val[y, "minimum"],
                                "maximum": val[y, "maximum"],
                                "uncertainty_type": distr,
                            }
                        )

                        rng = sa.MCRandomNumberGenerator(a)

                        for s in sizes:
                            for p in pt:
                                array.loc[
                                    dict(powertrain=p, size=s, year=y, parameter=param)
                                ] = rng.generate(array.sizes["value"]).reshape((-1,))

                    else:
                        print(
                            "The uncertainty type is not recognized for {} in {}.\n The parameter is skipped and default value applies".format(
                                param, y
                            )
                        )
                        continue

            # Static mode
            else:
                for y in year:
                    if distr == 1:
                        # There should be at least a `loc`
                        if ~np.isnan(val[(y, "loc")]):
                            for s in sizes:
                                for p in pt:
                                    array.loc[
                                        dict(
                                            powertrain=p,
                                            size=s,
                                            year=y,
                                            parameter=param,
                                        )
                                    ] = val[(y, "loc")]
                        # Otherwise warn
                        else:
                            print(
                                "`loc`parameter missing for {} in {}.".format(param, y)
                            )
                            continue

                    elif distr in [2, 3, 4, 5]:

                        # Check if the correct parameters are present
                        # Triangular

                        if distr == 5:
                            if (
                                    np.isnan(val[(y, "loc")])
                                    or np.isnan(val[(y, "minimum")])
                                    or np.isnan(val[(y, "maximum")])
                            ):
                                print(
                                    "One or more parameters for the triangular distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        # Lognormal
                        if distr == 2:
                            if np.isnan(val[(y, "loc")]) or np.isnan(val[(y, "scale")]):
                                print(
                                    "One or more parameters for the lognormal distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        # Normal
                        if distr == 3:
                            if np.isnan(val[(y, "loc")]) or np.isnan(val[(y, "scale")]):
                                print(
                                    "One or more parameters for the normal distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        # Uniform
                        if distr == 4:
                            if np.isnan(val[(y, "minimum")]) or np.isnan(
                                    val[(y, "maximum")]
                            ):
                                print(
                                    "One or more parameters for the uniform distribution is/are missing for {} in {}.\n The parameter is skipped and default value applies".format(
                                        param, y
                                    )
                                )
                                continue

                        a = sa.UncertaintyBase.from_dicts(
                            {
                                "loc": val[y, "loc"],
                                "scale": val[y, "scale"],
                                "shape": val[y, "shape"],
                                "minimum": val[y, "minimum"],
                                "maximum": val[y, "maximum"],
                                "uncertainty_type": distr,
                            }
                        )

                        dist = sa.uncertainty_choices[distr]
                        median = float(dist.ppf(a, np.array((0.5,))))

                        for s in sizes:
                            for p in pt:
                                array.loc[
                                    dict(powertrain=p, size=s, year=y, parameter=param)
                                ] = median

                    else:
                        print(
                            "The uncertainty type is not recognized for {} in {}.\n The parameter is skipped and default value applies".format(
                                param, y
                            )
                        )
                        continue
