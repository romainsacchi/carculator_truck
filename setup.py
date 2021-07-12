import os

from setuptools import setup

packages = []
root_dir = os.path.dirname(__file__)
if root_dir:
    os.chdir(root_dir)


# Probably should be changed, __init__.py is no longer required for Python 3
for dirpath, dirnames, filenames in os.walk("carculator_truck"):
    # Ignore dirnames that start with '.'
    if "__init__.py" in filenames:
        pkg = dirpath.replace(os.path.sep, ".")
        if os.path.altsep:
            pkg = pkg.replace(os.path.altsep, ".")
        packages.append(pkg)


def package_files(directory):
    paths = []
    for (path, directories, filenames) in os.walk(directory):
        for filename in filenames:
            paths.append(os.path.join("..", path, filename))
    return paths


setup(
    name="carculator_truck",
    version="0.2.3",
    packages=packages,
    author="Romain Sacchi <romain.sacchi@psi.ch>",
    license=open("LICENSE").read(),
    package_data={
        "carculator_truck": package_files(os.path.join("carculator_truck", "data"))
    },
    install_requires=[
        "pandas",
        "xarray <0.18",
        "numpy",
        "klausen",
        "xlrd",
        "numexpr",
        "bw2io",
        "prettytable",
        "wurst",
        "pycountry",
    ],
    url="https://github.com/romainsacchi/carculator_truck",
    description="Prospective environmental and economic life cycle assessment"
    "of medium and heavy goods vehicles",
    classifiers=[
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: BSD License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Topic :: Scientific/Engineering :: Mathematics",
        "Topic :: Scientific/Engineering :: Visualization",
    ],
)
