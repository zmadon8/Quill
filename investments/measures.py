"""The wording of the three return measures (D185), in one place so every page, report and export says the same thing.

* Return: the plain change in value since the money went in. Not scaled to a year.
* CAGR: the compound yearly growth rate between two dates, used for a single start and end value.
* XIRR: the yearly rate that fits every dated payment in and out (the money-weighted return).
"""

RETURN_TIP = "Return: the plain gain as a percentage of the money put in. It is not scaled to a year."
CAGR_TIP = "CAGR: the compound growth a year between two dates, from one start value and one end value."
XIRR_TIP = "XIRR: the yearly rate that fits every dated purchase, sale and the closing value (the money-weighted return)."
INDEX_XIRR_TIP = "Index XIRR: the XIRR you would have had by putting the same money in the Default Index on the same dates."
ALPHA_TIP = "Alpha: your XIRR less the index's XIRR over the same dates and cash flows."
LEGEND = ("Return is the plain gain since the money went in, with the days it covers shown beside it. CAGR is the same gain as a compound "
          "growth rate a year, used once a holding is a year old. XIRR is a yearly rate that fits all your purchases and sales on their dates.")
TIPS = {"return": RETURN_TIP, "cagr": CAGR_TIP, "xirr": XIRR_TIP, "index_xirr": INDEX_XIRR_TIP, "alpha": ALPHA_TIP, "legend": LEGEND}



def basis(days, annual):
    """The basis of one lot's return figure: "CAGR" when annualised, else "over N days"."""
    if annual:
        return "CAGR"
    return f"over {days} day{'s' if days != 1 else ''}"
