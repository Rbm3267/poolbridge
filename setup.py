from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="poolbridge",
    version="0.1.0",
    author="Bennett Moore",
    description="Convert Emlid Reach survey data to Structure Studios Pool Studio DXF format",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/rbm3267/poolbridge",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Scientific/Engineering :: GIS",
        "Topic :: Scientific/Engineering :: Visualization",
    ],
    python_requires=">=3.8",
    install_requires=[
        "ezdxf>=1.1.0",
        "pyproj>=3.4.0",
        "pandas>=1.5.0",
        "pyyaml>=6.0",
        "numpy>=1.23.0",
        "scipy>=1.9.0",
        "pyshp>=2.3.0",
    ],
    extras_require={
        "dev": ["pytest>=7.0"],
    },
    entry_points={
        "console_scripts": [
            "poolbridge=poolbridge.cli:main",
        ],
    },
)
