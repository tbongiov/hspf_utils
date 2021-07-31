# -*- coding: utf-8 -*-

import os
import re
import sys
import warnings

import numpy as np
import pandas as pd
from mando import command, main
from tabulate import simple_separated_format, tabulate
from tstoolbox import tsutils

docstrings = {
    "hbn": r"""hbn : str
        This is the binary output file containing PERLND and IMPLND
        information.  This should be the binary output file created by the
        `uci` file.""",
    "uci": r"""uci
        [optional, defaults to None]

        This uci file will be read to determine all of the areas and other
        aspects of the model.  If available it will read the land cover names
        from the PERLND GEN-INFO table.  Required if you want the water balance
        area-weighted between land covers.""",
    "year": r"""year
        [optional, defaults to None]

        If None the water balance would cover the period of simulation.
        Otherwise the year for the water balance.""",
    "ofilename": r"""ofilename
        [optional, defaults to '']

        If empty string '', then prints to stdout, else prints to
        `ofilename`.""",
    "modulus": r"""modulus : int
        [optional, defaults to 20]

        Usual setup of a HSPF model has PERLND 1, 21, 41, ...etc. represent
        land cover 1 in different sub-watersheds and 2, 22, 42, ...etc
        represent land cover 2 in different sub-watersheds, ...etc.

        The remainder of the PERLND label divided by the modulus is the land
        cover number.""",
    "tablefmt": r"""tablefmt : str
        [optional, default is 'cvs_nos']

        The table format.  Can be one of 'csv', 'tsv', 'csv_nos', 'tsv_nos',
        'plain', 'simple', 'github', 'grid', 'fancy_grid', 'pipe', 'orgtbl',
        'jira', 'presto', 'psql', 'rst', 'mediawiki', 'moinmoin', 'youtrack',
        'html', 'latex', 'latex_raw', 'latex_booktabs' and
        'textile'.""",
    "index_prefix": r"""index_prefix
        [optional, defaults to '']

        A string prepended to the PERLND code, which would allow being
        run on different models and collected into one dataset by
        creating a unique ID.""",
    "index_delimiter": r"""index_delimiter
        [optional, defaults to '-']

        Useful to separate the `index_prefix` from the PERLND/IMPLND number.
        """,
}


@command()
def about():
    """Display version number and system information."""
    tsutils.about(__name__)


def _give_negative_warning(df):
    testpdf = df < 0
    if testpdf.any(None):
        warnings.warn(
            f"""
This may be OK, but FYI there are negative values at:

{df.loc[testpdf.any(1), testpdf.any(0)]}

                                            """
        )


def process(uci, hbn, pwbe, year, ofilename, modulus, tablefmt, float_format=".2f"):

    from hspfbintoolbox.hspfbintoolbox import extract

    if ofilename:
        sys.stdout = open(ofilename, "w")

    try:
        year = int(year)
    except TypeError:
        pass

    lcnames = dict(zip(range(modulus + 1, 1), zip(range(modulus + 1, 1))))
    inverse_lcnames = dict(zip(range(modulus + 1, 1), zip(range(modulus + 1, 1))))
    inverse_lc = {}

    lnds = {}

    if uci is not None:
        with open(uci) as fp:
            content = fp.readlines()

        if not os.path.exists(hbn):
            raise ValueError(
                """
*
*   File {} does not exist.
*
""".format(
                    hbn
                )
            )

        content = [i[:80] for i in content]
        content = [i.rstrip() for i in content]

        schematic_start = content.index("SCHEMATIC")
        schematic_end = content.index("END SCHEMATIC")
        schematic = content[schematic_start : schematic_end + 1]

        perlnd_start = content.index("PERLND")
        perlnd_end = content.index("END PERLND")
        perlnd = content[perlnd_start : perlnd_end + 1]

        pgeninfo_start = perlnd.index("  GEN-INFO")
        pgeninfo_end = perlnd.index("  END GEN-INFO")
        pgeninfo = perlnd[pgeninfo_start : pgeninfo_end + 1]

        masslink_start = content.index("MASS-LINK")
        masslink_end = content.index("END MASS-LINK")
        masslink = content[masslink_start : masslink_end + 1]

        lcnames = {}
        inverse_lcnames = {}
        inverse_lc = {}
        for line in pgeninfo[1:-1]:
            if "***" in line:
                continue
            if "" == line.strip():
                continue
            try:
                _ = int(line[5:10])
                continue
            except ValueError:
                pass
            lcnames.setdefault(line[10:30].strip(), []).append(int(line[:5]))
            inverse_lcnames[int(line[:5])] = line[10:30].strip()
            inverse_lc[int(line[:5]) % modulus] = line[10:30].strip()

        masslink = [i for i in masslink if "***" not in i]
        masslink = [i for i in masslink if len(i.strip()) > 0]
        masslink = " ".join(masslink)
        mlgroups = re.findall(
            r"  MASS-LINK +?([0-9]+).*?LND     [PI]WATER [PS][EU]RO.*?  END MASS-LINK +?\1 ",
            masslink,
        )

        for line in schematic[3:-1]:
            if "***" in line:
                continue
            if "" == line:
                continue
            words = line.split()
            if words[0] in ["PERLND", "IMPLND"] and words[5] in mlgroups:
                lnds[(words[0], int(words[1]))] = lnds.setdefault(
                    (words[0], int(words[1])), 0.0
                ) + float(words[2])

    try:
        pdf = extract(hbn, "yearly", ",,,")
    except ValueError:
        raise ValueError(
            tsutils.error_wrapper(
                f"""
The binary file "{hbn}" does not have consistent ending months between PERLND and
IMPLND.  This could be caused by the BYREND (Binary YeaR END) being set
differently in the PERLND:BINARY-INFO and IMPLND:BINARY-INFO, or you could
have the PRINT-INFO bug.  To work around the PRINT-INFO bug, add a PERLND
PRINT-INFO block, setting the PYREND here will actually work in the
BINARY-INFO block.
"""
            )
        )

    if year is not None:
        pdf = pd.DataFrame(pdf.loc["{}-01-01".format(year), :]).T
    pdf = pdf[[i for i in pdf.columns if "PERLND" in i or "IMPLND" in i]]

    mindex = [i.split("_") for i in pdf.columns]
    mindex = [(i[0], int(i[1]), i[2], int(i[1]) % modulus) for i in mindex]
    mindex = pd.MultiIndex.from_tuples(mindex, names=["op", "number", "wbt", "lc"])
    pdf.columns = mindex
    pdf = pdf.sort_index(axis="columns")
    mindex = pdf.columns
    aindex = [(i[0], i[1]) for i in pdf.columns]
    mindex = [
        (
            i[0],
            int(i[1]),
            i[2],
            int(i[1]) % modulus,
            float(lnds.setdefault(j, 0.0)),
            str(inverse_lcnames.setdefault(int(i[1]), "")),
        )
        for i, j in zip(mindex, aindex)
    ]
    mindex = pd.MultiIndex.from_tuples(
        mindex, names=["op", "number", "wbt", "lc", "area", "lcname"]
    )
    pdf.columns = mindex

    nsum = {}
    areas = {}
    namelist = {}
    setl = [i[1] for i in pwbe]
    setl = [item for sublist in setl for item in sublist]
    for lue in ["PERLND", "IMPLND"]:
        for wbterm in [i[0] for i in setl if i[0]]:
            for lc in list(range(1, modulus + 1)):
                try:
                    subset = pdf.loc[
                        :, (lue, slice(None), wbterm, lc, slice(None), slice(None))
                    ]
                except KeyError:
                    continue

                _give_negative_warning(subset)

                if uci is None:
                    if subset.empty is True:
                        nsum[(lue, lc, wbterm)] = 0.0
                        if (lue, lc) not in namelist:
                            namelist[(lue, lc)] = ""
                    else:
                        nsum[(lue, lc, wbterm)] = subset.mean(axis="columns").mean()
                        namelist[(lue, lc)] = inverse_lc.setdefault(lc, lc)
                else:
                    sareas = subset.columns.get_level_values("area")
                    ssareas = sum(sareas)
                    if (lue, lc) not in areas:
                        areas[(lue, lc)] = ssareas

                    if subset.empty is True or ssareas == 0:
                        nsum[(lue, lc, wbterm)] = 0.0
                        if (lue, lc) not in namelist:
                            namelist[(lue, lc)] = ""
                    else:
                        fa = sareas / areas[(lue, lc)]
                        nsum[(lue, lc, wbterm)] = (
                            (subset * fa).sum(axis="columns").mean()
                        )
                        namelist[(lue, lc)] = inverse_lc.setdefault(lc, lc)

    newnamelist = []
    for key, value in sorted(namelist.items()):
        if key[0] != "PERLND":
            continue
        if key[1] == value:
            newnamelist.append("{}".format(key[1]))
        else:
            newnamelist.append("{}-{}".format(key[1], value))

    printlist = []
    printlist.append([" "] + newnamelist + ["ALL"])

    mapipratio = {}
    mapipratio["PERLND"] = 1.0
    mapipratio["IMPLND"] = 1.0

    if uci is not None:
        pareas = []
        pnl = []
        iareas = []
        for nloper, nllc in namelist:
            if nloper == "PERLND":
                pnl.append((nloper, nllc))
                pareas.append(areas[("PERLND", nllc)])
        # If there is a PERLND there must be a IMPLND.
        for ploper, pllc in pnl:
            try:
                iareas.append(areas[("IMPLND", pllc)])
            except KeyError:
                iareas.append(0.0)
        ipratio = np.array(iareas) / (np.array(pareas) + np.array(iareas))
        ipratio = np.nan_to_num(ipratio)
        ipratio = np.pad(ipratio, (0, len(pareas) - len(iareas)), "constant")
        sumareas = sum(pareas) + sum(iareas)

        percent_areas = {}
        percent_areas["PERLND"] = np.array(pareas) / sumareas * 100
        percent_areas["IMPLND"] = np.array(iareas) / sumareas * 100
        percent_areas["COMBINED"] = percent_areas["PERLND"] + percent_areas["IMPLND"]

        printlist.append(["PERVIOUS"])
        printlist.append(
            ["AREA(acres)"]
            + [str(i) if i > 0 else "" for i in pareas]
            + [str(sum(pareas))]
        )

        printlist.append(
            ["AREA(%)"]
            + [str(i) if i > 0 else "" for i in percent_areas["PERLND"]]
            + [str(sum(percent_areas["PERLND"]))]
        )

        printlist.append([])
        printlist.append(["IMPERVIOUS"])
        printlist.append(
            ["AREA(acres)"]
            + [str(i) if i > 0 else "" for i in iareas]
            + [str(sum(iareas))]
        )

        printlist.append(
            ["AREA(%)"]
            + [str(i) if i > 0 else "" for i in percent_areas["IMPLND"]]
            + [str(sum(percent_areas["IMPLND"]))]
        )
        printlist.append([])

        mapipratio["PERLND"] = 1.0 - ipratio
        mapipratio["IMPLND"] = ipratio

    mapr = {}
    mapr["PERLND"] = 1.0
    mapr["IMPLND"] = 1.0

    for term, op in pwbe:
        if not term:
            printlist.append([])
            continue

        test = [i[1] for i in op]
        if "IMPLND" in test and "PERLND" in test:
            maprat = mapipratio
            sumop = "COMBINED"
        else:
            maprat = mapr
            sumop = test[0]

        te = [0.0]
        for sterm, operation in op:
            try:
                tmp = np.array(
                    [nsum[(*i, sterm)] for i in sorted(namelist) if i[0] == operation]
                )
                if uci is not None:
                    tmp = (
                        np.pad(tmp, (0, len(pareas) - len(tmp)), "constant")
                        * maprat[operation]
                    )
                te = te + tmp
            except KeyError:
                pass
        if uci is None:
            te = (
                [term]
                + [str(i) if i > 0 else "" for i in te]
                + [str(sum(te) / len(te))]
            )
        else:
            nte = np.pad(te, (0, len(iareas) - len(te)), "constant")
            te = (
                [term]
                + [str(i) if i > 0 else "" for i in nte]
                + [str(sum(nte * percent_areas[sumop]) / 100)]
            )
        printlist.append(te)

    if tablefmt in ["csv", "tsv", "csv_nos", "tsv_nos"]:
        sep = {"csv": ",", "tsv": "\\t", "csv_nos": ",", "tsv_nos": "\\t"}[tablefmt]
        fmt = simple_separated_format(sep)
    else:
        fmt = tablefmt
    if tablefmt in ["csv_nos", "tsv_nos"]:
        print(
            re.sub(
                " *, *", ",", tabulate(printlist, tablefmt=fmt, floatfmt=float_format)
            )
        )
    else:
        print(tabulate(printlist, tablefmt=fmt, floatfmt=float_format))


@command(doctype="numpy")
@tsutils.doc(docstrings)
def detailed(
    hbn,
    uci=None,
    year=None,
    ofilename="",
    modulus=20,
    tablefmt="csv_nos",
    float_format=".2f",
):
    """Develops a detailed water balance.

    Parameters
    ----------
    {hbn}
    {uci}
    {year}
    {ofilename}
    {modulus}
    {tablefmt}
    {float_format}
    """

    if uci is None:
        pwbe = (
            ["SUPY", [("SUPY", "PERLND")]],
            ["SURLI", [("SURLI", "PERLND")]],
            ["UZLI", [("UZLI", "PERLND")]],
            ["LZLI", [("LZLI", "PERLND")]],
            ["", [("", "")]],
            ["SURO: PERVIOUS", [("SURO", "PERLND")]],
            ["SURO: IMPERVIOUS", [("SURO", "IMPLND")]],
            ["IFWO", [("IFWO", "PERLND")]],
            ["AGWO", [("AGWO", "PERLND")]],
            ["", [("", "")]],
            ["AGWI", [("AGWI", "PERLND")]],
            ["IGWI", [("IGWI", "PERLND")]],
            ["", [("", "")]],
            ["CEPE", [("CEPE", "PERLND")]],
            ["UZET", [("UZET", "PERLND")]],
            ["LZET", [("LZET", "PERLND")]],
            ["AGWET", [("AGWET", "PERLND")]],
            ["BASET", [("BASET", "PERLND")]],
            ["SURET", [("SURET", "PERLND")]],
            ["", [("", "")]],
            ["PERO", [("PERO", "PERLND")]],
            ["IGWI", [("IGWI", "PERLND")]],
            ["TAET: PERVIOUS", [("TAET", "PERLND")]],
            ["IMPEV: IMPERVIOUS", [("IMPEV", "IMPLND")]],
            ["", [("", "")]],
            ["PET", [("PET", "PERLND")]],
            ["", [("", "")]],
            ["PERS", [("PERS", "PERLND")]],
        )
    else:
        pwbe = (
            ["SUPY", [("SUPY", "PERLND"), ("SUPY", "IMPLND"), ("IRRAPP6", "PERLND")]],
            ["SURLI", [("SURLI", "PERLND")]],
            ["UZLI", [("UZLI", "PERLND")]],
            ["LZLI", [("LZLI", "PERLND")]],
            ["", [("", "")]],
            ["SURO: PERVIOUS", [("SURO", "PERLND")]],
            ["SURO: IMPERVIOUS", [("SURO", "IMPLND")]],
            ["SURO: COMBINED", [("SURO", "PERLND"), ("SURO", "IMPLND")]],
            ["IFWO", [("IFWO", "PERLND")]],
            ["AGWO", [("AGWO", "PERLND")]],
            ["", [("", "")]],
            ["AGWI", [("AGWI", "PERLND")]],
            ["IGWI", [("IGWI", "PERLND")]],
            ["", [("", "")]],
            ["CEPE", [("CEPE", "PERLND")]],
            ["UZET", [("UZET", "PERLND")]],
            ["LZET", [("LZET", "PERLND")]],
            ["AGWET", [("AGWET", "PERLND")]],
            ["BASET", [("BASET", "PERLND")]],
            ["SURET", [("SURET", "PERLND")]],
            ["", [("", "")]],
            ["PERO", [("PERO", "PERLND")]],
            ["IGWI", [("IGWI", "PERLND")]],
            ["TAET: PERVIOUS", [("TAET", "PERLND")]],
            ["IMPEV: IMPERVIOUS", [("IMPEV", "IMPLND")]],
            ["ET: COMBINED", [("TAET", "PERLND"), ("IMPEV", "IMPLND")]],
            ["", [("", "")]],
            ["PET", [("PET", "PERLND"), ("PET", "IMPLND")]],
            ["", [("", "")]],
            ["PERS", [("PERS", "PERLND")]],
        )
    process(
        uci, hbn, pwbe, year, ofilename, modulus, tablefmt, float_format=float_format
    )


@command(doctype="numpy")
@tsutils.doc(docstrings)
def summary(
    hbn,
    uci=None,
    year=None,
    ofilename="",
    modulus=20,
    tablefmt="csv_nos",
    float_format=".2f",
):
    """Develops a summary water balance.

    Parameters
    ----------
    {hbn}
    {uci}
    {year}
    {ofilename}
    {modulus}
    {tablefmt}
    {float_format}

    """
    if uci is None:
        pwbe = (
            [
                "Rainfall and irrigation",
                [
                    ("SUPY", "PERLND"),
                    ("SUPY", "IMPLND"),
                    ("IRRAPP6", "PERLND"),
                ],
            ],
            ["", [("", "")]],
            [
                "Runoff:Pervious",
                [("PERO", "PERLND")],
            ],
            ["Runoff:Impervious", [("SURO", "IMPLND")]],
            ["", [("", "")]],
            ["Deep recharge", [("IGWI", "PERLND")]],
            ["", [("", "")]],
            ["Evaporation:Pervious", [("TAET", "PERLND")]],
            ["Evaporation:Impervious", [("IMPEV", "IMPLND")]],
        )
    else:
        pwbe = (
            [
                "Rainfall and irrigation",
                [
                    ("SUPY", "PERLND"),
                    ("SUPY", "IMPLND"),
                    ("SURLI", "PERLND"),
                    ("UZLI", "PERLND"),
                    ("LZLI", "PERLND"),
                ],
            ],
            ["", [("", "")]],
            [
                "Runoff:Pervious",
                [("PERO", "PERLND")],
            ],
            ["Runoff:Impervious", [("SURO", "IMPLND")]],
            [
                "Runoff:Combined",
                [
                    ("PERO", "PERLND"),
                    ("SURO", "IMPLND"),
                ],
            ],
            ["", [("", "")]],
            ["Deep recharge", [("IGWI", "PERLND")]],
            ["", [("", "")]],
            ["Evaporation:Pervious", [("TAET", "PERLND")]],
            ["Evaporation:Impervious", [("IMPEV", "IMPLND")]],
            ["Evaporation:Combined", [("TAET", "PERLND"), ("IMPEV", "IMPLND")]],
        )
    process(
        uci, hbn, pwbe, year, ofilename, modulus, tablefmt, float_format=float_format
    )


@command(doctype="numpy")
@tsutils.doc(docstrings)
def mapping(
    hbn, year=None, ofilename="", tablefmt="csv_nos", index_prefix="", float_format="g"
):
    """Develops a csv file appropriate for joining to a GIS layer.

    Parameters
    ----------
    {hbn}

    {year}

    {ofilename}

    {tablefmt}

    {index_prefix}
        [optional, defaults to '']

        A string prepended to the PERLND code, which would allow being
        run on different models and collected into one dataset by
        creating a unique ID.

    {float_format}

    """
    from hspfbintoolbox.hspfbintoolbox import extract

    if ofilename:
        sys.stdout = open(ofilename, "w")

    try:
        pdf = extract(hbn, "yearly", ",,,")
    except ValueError:
        raise ValueError(
            """
*
*   The binary file does not have consistent ending months between PERLND and
*   IMPLND.  This could be caused by the BYREND (Binary YeaR END) being set
*   differently in the PERLND:BINARY-INFO and IMPLND:BINARY-INFO, or you could
*   have the PRINT-INFO bug.  To work around the PRINT-INFO bug, add a PERLND
*   PRINT-INFO block, setting the PYREND here will actually work in the
*   BINARY-INFO block.
*
"""
        )

    if year is not None:
        pdf = pd.DataFrame(pdf.loc["{}-01-01".format(year), :]).T
    pdf = pdf[[i for i in pdf.columns if "PERLND" in i or "IMPLND" in i]]

    mindex = [i.split("_") for i in pdf.columns]
    mindex = [(i[0][0], int(i[1]), i[2]) for i in mindex]
    mindex = pd.MultiIndex.from_tuples(mindex, names=["op", "number", "wbt"])
    pdf.columns = mindex

    _give_negative_warning(pdf)

    pdf = pdf.mean(axis="index").to_frame()

    mindex = [("_".join([i[0], i[2]]), i[1]) for i in pdf.index]
    mindex = pd.MultiIndex.from_tuples(mindex, names=["wbt", "number"])
    pdf.index = mindex
    pdf = pdf.unstack("wbt")

    mindex = [i[1] for i in pdf.columns]
    pdf.columns = mindex

    pdf.index.name = "lue"

    if index_prefix:
        pdf.index = [index_prefix + str(i) for i in pdf.index]

    if tablefmt in ["csv", "tsv", "csv_nos", "tsv_nos"]:
        sep = {"csv": ",", "tsv": "\\t", "csv_nos": ",", "tsv_nos": "\\t"}[tablefmt]
        fmt = simple_separated_format(sep)
    else:
        fmt = tablefmt
    if tablefmt in ["csv_nos", "tsv_nos"]:
        print(
            re.sub(
                " *, *",
                ",",
                tabulate(
                    pdf, tablefmt=fmt, headers="keys", floatfmt=float_format
                ).replace("nan", ""),
            )
        )
    else:
        print(
            tabulate(pdf, tablefmt=fmt, headers="keys", floatfmt=float_format).replace(
                "nan", ""
            )
        )


@command(doctype="numpy")
@tsutils.doc(docstrings)
def parameters(
    uci,
    index_prefix="",
    index_delimiter="",
    modulus=20,
    tablefmt="csv_nos",
    float_format="g",
):
    """Develops a table of parameter values.

    Parameters
    ----------
    {uci}
    {index_prefix}
    {index_delimiter}
    {modulus}
    {tablefmt}
    {float_format}

    """
    blocklist = ["PWAT-PARM2", "PWAT-PARM3", "PWAT-PARM4"]  # , 'PWAT-STATE1']

    params = {}
    params["PWAT-PARM2"] = [
        "FOREST",
        "LZSN",
        "INFILT",
        "LSUR",
        "SLSUR",
        "KVARY",
        "AGWRC",
    ]
    params["PWAT-PARM3"] = [
        "PETMAX",
        "PETMIN",
        "INFEXP",
        "INFILD",
        "DEEPFR",
        "BASETP",
        "AGWETP",
    ]
    params["PWAT-PARM4"] = ["CEPSC", "UZSN", "NSUR", "INTFW", "IRC", "LZETP"]
    #    params['PWAT-STATE1'] = ['CEPS',   'SURS',   'UZS',    'IFWS',   'LZS',    'AGWS',   'GWVS']

    defaults = {}
    defaults["FOREST"] = 0.0
    defaults["KVARY"] = 0.0

    defaults["PETMAX"] = 40.0
    defaults["PETMIN"] = 35.0
    defaults["INFEXP"] = 2.0
    defaults["INFILD"] = 2.0
    defaults["DEEPFR"] = 0.0
    defaults["BASETP"] = 0.0
    defaults["AGWETP"] = 0.0

    defaults["CEPSC"] = 0.0
    defaults["NSUR"] = 0.1
    defaults["LZETP"] = 0.0

    # defaults['CEPS'] = 0.0
    # defaults['SURS'] = 0.0
    # defaults['UZS'] = 0.001
    # defaults['IFWS'] = 0.0
    # defaults['LZS'] = 0.001
    # defaults['AGWS'] = 0.0
    # defaults['GWVS'] = 0.0

    with open(uci) as fp:
        content = fp.readlines()

    content = [i[:81].rstrip() for i in content if "***" not in i]
    content = [i.rstrip() for i in content if i]

    files_start = content.index("FILES")
    files_end = content.index("END FILES")
    files = content[files_start + 1 : files_end]

    supfname = ""
    for line in files:
        words = line.split()
        if words[0] == "PESTSU":
            supfname = words[2]
    if supfname:
        ucipath = os.path.dirname(uci)
        with open(os.path.join(ucipath, supfname)) as sfp:
            supfname = sfp.readlines()
            supfname = [i.strip() for i in supfname if "***" not in i]
            supfname = [i.strip() for i in supfname if i]

        supfname = {
            key.split()[0]: [float(i) for i in value.split()]
            for key, value in zip(supfname[:-1:2], supfname[1::2])
        }

    rngdata = []
    order = []
    for blk in blocklist:
        start = content.index("  {}".format(blk))
        end = content.index("  END {}".format(blk))
        block_lines = content[start + 1 : end]

        order.extend(params[blk])

        for line in block_lines:
            rngstrt = int(line[:5])
            try:
                rngend = int(line[5:10]) + 1
            except ValueError:
                rngend = rngstrt + 1
            tilde = re.match("~([0-9][0-9]*)~", line[10:])
            if tilde:
                tilde = tilde[0][1:-1]
            for rng in list(range(rngstrt, rngend)):
                for index, par in enumerate(params[blk]):
                    if tilde:
                        rngdata.append(
                            [
                                index_prefix + index_delimiter + str(rng),
                                par,
                                supfname[tilde][index],
                            ]
                        )
                    else:
                        start = (index + 1) * 10
                        rngdata.append(
                            [
                                index_prefix + index_delimiter + str(rng),
                                par,
                                float(line[start : start + 10]),
                            ]
                        )

    df = pd.DataFrame(rngdata)
    df.columns = ["lue", "term", "val"]
    df = df.pivot(index="lue", columns="term")
    df.columns = [i[1] for i in df.columns]
    df = df.loc[:, order]
    if index_prefix:
        spliton = index_prefix[-1]
    if index_delimiter:
        spliton = index_delimiter
    if index_prefix or index_delimiter:
        df = df.reindex(
            index=df.index.to_series()
            .str.rsplit(spliton)
            .str[-1]
            .astype(int)
            .sort_values()
            .index
        )
    else:
        df.index = df.index.astype(int)
        df = df.sort_index()

    if tablefmt in ["csv", "tsv", "csv_nos", "tsv_nos"]:
        sep = {"csv": ",", "tsv": "\t", "csv_nos": ",", "tsv_nos": "\t"}[tablefmt]
        fmt = simple_separated_format(sep)
    else:
        fmt = tablefmt

    if tablefmt == "csv_nos":
        print(
            re.sub(
                " *, *",
                ",",
                tabulate(df, headers="keys", tablefmt=fmt, floatfmt=float_format),
            )
        )
    elif tablefmt == "tsv_nos":
        print(
            re.sub(
                " *\t *",
                "\t",
                tabulate(df, headers="keys", tablefmt=fmt, floatfmt=float_format),
            )
        )
    else:
        print(tabulate(df, headers="keys", tablefmt=fmt, floatfmt=float_format))


if __name__ == "__main__":
    main()
