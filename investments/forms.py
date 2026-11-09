"""Django forms for the Investments pages. They only check the shape of the input; every rule lives in the services."""
from datetime import date

from django import forms

from investments.models import (
    ASSET_CLASSES, HOLDABLE_KINDS, KIND_ALTERNATIVE, KIND_FOREIGN, KIND_FUND, KIND_SHARE, Broker, Folio, Instrument, Portfolio,
)


class MoneyField(forms.DecimalField):
    """A decimal that accepts Indian digit grouping (1,23,456.50)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 20)
        kwargs.setdefault("decimal_places", 4)
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(",", "").replace("\u20b9", "").strip()
        return super().to_python(value)


def date_widget():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ProfileForm(forms.Form):
    """Base: remembers the profile and offers its portfolios, brokers and investments."""

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile

    def instruments(self):
        from django.db.models import Q

        return Instrument.objects.filter(Q(profile=None) | Q(profile=self.profile), kind__in=HOLDABLE_KINDS).order_by("name")

    def brokers(self, include_hidden=False):
        qs = Broker.objects.filter(profile=self.profile)
        return qs if include_hidden else qs.filter(hidden=False)


class TransactionForm(ProfileForm):
    """Add or edit one purchase or sale. ``mode``: buy, sell, awaiting_buy, awaiting_sell, edit."""

    date = forms.DateField(widget=date_widget(), label="Date")
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none(), label="Portfolio")
    broker = forms.ModelChoiceField(queryset=Broker.objects.none(), label="Broker", empty_label="Choose a broker")
    folio = forms.ModelChoiceField(queryset=Folio.objects.none(), label="Folio (optional)", required=False)
    new_folio = forms.CharField(label="Or a new folio number", required=False, max_length=60)
    units = MoneyField(label="Units", required=False, min_value=0)
    price = MoneyField(label="Price per unit", required=False, min_value=0)
    charges = MoneyField(label="Charges", required=False, min_value=0, initial=0)
    allotment_date = forms.DateField(widget=date_widget(), label="Allotment date", required=False)
    amount = MoneyField(label="Amount paid", required=False, min_value=0)
    expected_allotment_date = forms.DateField(widget=date_widget(), label="Expected allotment date", required=False)
    reference = forms.CharField(label="Reference", required=False, max_length=80)
    note = forms.CharField(label="Note", required=False, max_length=200)

    def __init__(self, *args, profile=None, mode="buy", **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.mode = mode
        self.fields["instrument"].queryset = self.instruments()
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)
        self.fields["broker"].queryset = self.brokers()
        self.fields["folio"].queryset = Folio.objects.filter(profile=profile).select_related("instrument", "portfolio")
        self.fields["date"].initial = date.today()
        awaiting = mode.startswith("awaiting")
        if mode == "sell":
            self.fields["date"].label = "Date sold"
        if awaiting:
            for name in ("units", "price", "allotment_date"):
                del self.fields[name]
            self.fields["amount"].required = True
            self.fields["amount"].label = "Amount paid" if mode == "awaiting_buy" else "Expected proceeds"
            self.fields["date"].label = "Date paid" if mode == "awaiting_buy" else "Date of the redemption"
        else:
            del self.fields["amount"]
            del self.fields["expected_allotment_date"]
            del self.fields["reference"]
            self.fields["units"].required = True
            self.fields["price"].required = True
            if mode in ("sell", "edit_sell"):
                del self.fields["allotment_date"]
        if mode in ("sell", "awaiting_sell", "edit_sell"):
            del self.fields["new_folio"]
        if mode.startswith("edit"):
            self.fields["instrument"].disabled = False

    def clean(self):
        cleaned = super().clean()
        folio = cleaned.get("folio")
        if folio and cleaned.get("instrument") and (folio.instrument_id != cleaned["instrument"].pk or (cleaned.get("portfolio") and folio.portfolio_id != cleaned["portfolio"].pk)):
            self.add_error("folio", "That folio belongs to a different investment or portfolio.")
        return cleaned


class CompleteForm(forms.Form):
    allotment_date = forms.DateField(widget=date_widget(), label="Allotment date")
    units = MoneyField(label="Units", required=False, min_value=0)
    nav = MoneyField(label="NAV (price per unit)", required=False, min_value=0)
    charges = MoneyField(label="Charges (for example stamp duty)", required=False, min_value=0)
    confirm_difference = forms.BooleanField(label="The difference is right (for example a partial allotment)", required=False)


class OpeningForm(ProfileForm):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none())
    broker = forms.ModelChoiceField(queryset=Broker.objects.none(), empty_label="Choose a broker")
    folio = forms.ModelChoiceField(queryset=Folio.objects.none(), required=False, label="Folio (optional)")

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["instrument"].queryset = self.instruments()
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)
        self.fields["broker"].queryset = self.brokers()
        self.fields["folio"].queryset = Folio.objects.filter(profile=profile)


class TransferForm(ProfileForm):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    date = forms.DateField(widget=date_widget(), initial=date.today)
    units = MoneyField(min_value=0)
    from_portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none(), label="From portfolio")
    from_broker = forms.ModelChoiceField(queryset=Broker.objects.none(), label="From broker")
    from_folio = forms.ModelChoiceField(queryset=Folio.objects.none(), required=False, label="From folio")
    to_portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none(), label="To portfolio")
    to_broker = forms.ModelChoiceField(queryset=Broker.objects.none(), label="To broker")
    to_folio = forms.ModelChoiceField(queryset=Folio.objects.none(), required=False, label="To folio")
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["instrument"].queryset = self.instruments()
        for name in ("from_portfolio", "to_portfolio"):
            self.fields[name].queryset = Portfolio.objects.filter(profile=profile)
        for name in ("from_broker", "to_broker"):
            self.fields[name].queryset = self.brokers()
        for name in ("from_folio", "to_folio"):
            self.fields[name].queryset = Folio.objects.filter(profile=profile)


class SwitchForm(ProfileForm):
    date = forms.DateField(widget=date_widget(), initial=date.today)
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none())
    broker = forms.ModelChoiceField(queryset=Broker.objects.none())
    from_instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Fund sold")
    units_out = MoneyField(label="Units sold", min_value=0)
    price_out = MoneyField(label="NAV sold at", min_value=0)
    charges = MoneyField(required=False, min_value=0, label="Charges")
    to_instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Fund bought")
    units_in = MoneyField(label="Units bought", min_value=0)
    price_in = MoneyField(label="NAV bought at", min_value=0)
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        funds = self.instruments().filter(kind=KIND_FUND)
        self.fields["from_instrument"].queryset = funds
        self.fields["to_instrument"].queryset = funds
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)
        self.fields["broker"].queryset = self.brokers()


KIND_CHOICES = [(KIND_SHARE, "Share or ETF"), ("fund", "Mutual fund"), (KIND_ALTERNATIVE, "Alternative investment"), (KIND_FOREIGN, "Foreign investment")]


class InstrumentForm(forms.Form):
    kind = forms.ChoiceField(choices=KIND_CHOICES)
    name = forms.CharField(max_length=200)
    code = forms.CharField(max_length=60, required=False, label="Code (ticker or AMFI scheme code)")
    isin = forms.CharField(max_length=20, required=False, label="ISIN")
    currency = forms.CharField(max_length=3, initial="INR", required=False)
    asset_class = forms.ChoiceField(choices=ASSET_CLASSES, initial="equity", label="Asset class")
    sector = forms.CharField(max_length=80, required=False)
    interest_rate = forms.DecimalField(max_digits=7, decimal_places=3, required=False, label="Interest rate % (optional)")
    maturity_date = forms.DateField(widget=date_widget(), required=False, label="Maturity date (optional)")

    def clean_currency(self):
        return (self.cleaned_data.get("currency") or "INR").upper()


class PriceForm(forms.Form):
    date = forms.DateField(widget=date_widget(), initial=date.today)
    close = MoneyField(label="Price or NAV", min_value=0)
    note = forms.CharField(required=False, max_length=200)


class AltValueForm(forms.Form):
    date = forms.DateField(widget=date_widget(), initial=date.today)
    total_value = MoneyField(label="Total value", min_value=0)
    nav = MoneyField(label="Unit price (optional)", required=False, min_value=0)
    note = forms.CharField(required=False, max_length=200)


class FolioForm(forms.Form):
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none())
    number = forms.CharField(max_length=60, label="Folio number")
    notes = forms.CharField(required=False, max_length=200)
    confirm_new = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)


class DetailsForm(forms.Form):
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    links = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Website links (one per line: label | address)")


class GeneralSettingsForm(forms.Form):
    sip_mode = forms.ChoiceField(choices=[("pending", "Pending until confirmed (default)"), ("final", "Created as final")], label="SIP entries")
    awaiting_treatment = forms.ChoiceField(choices=[("cost", "Count at cost (default)"), ("leave_out", "Leave out until allotted")], label="Awaiting allotment")
    awaiting_reminder_days = forms.IntegerField(min_value=1, max_value=60, label="Reminder after (days)")
    corporate_action_mode = forms.ChoiceField(choices=[("tag", "Tag and banner (default)"), ("block", "Block until confirmed")], label="Pending corporate actions")
    long_term_days = forms.IntegerField(min_value=1, max_value=3650, label="Long-term after (days held)")
    default_index = forms.ModelChoiceField(queryset=Instrument.objects.filter(kind="index"), required=False, label="Default Index", empty_label="Nifty 50 (default)")
    sectoral_enabled = forms.BooleanField(required=False, label="Use a sectoral index as well")
    include_dividends = forms.BooleanField(required=False, label="Include dividends in XIRR")
    alt_treatment = forms.ChoiceField(choices=[("unchanged", "Unchanged until the next update"), ("averaged", "Averaged out between updates")], label="Alternative investments between updates")
    money_default = forms.ChoiceField(choices=[("auto", "Auto"), ("full", "Full numbers")], label="Starting number display")


class DefaultBrokersForm(forms.Form):
    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Broker.objects.filter(profile=profile, hidden=False)
        for key, label in (("share", "Shares"), ("fund", "Mutual funds"), ("alternative", "Alternative investments"), ("foreign", "Foreign investments")):
            self.fields[f"default_broker_{key}"] = forms.ModelChoiceField(queryset=qs, required=False, label=label, empty_label="None (choose each time)")


class NameForm(forms.Form):
    name = forms.CharField(max_length=80)


class PortfolioForm(forms.Form):
    name = forms.CharField(max_length=80)
    owner_name = forms.CharField(max_length=80, required=False, label="Owner")


class DeleteInstrumentForm(forms.Form):
    confirm_name = forms.CharField(required=False, label="Type the investment's name to confirm")


class PriceUploadForm(forms.Form):
    file = forms.FileField(label="CSV or Excel file (up to 3 MB; bigger files use the import_prices command)")
    basis = forms.ChoiceField(choices=[("", "The file has a basis column"), ("raw", "Raw closes (as traded)"), ("split_adjusted", "Split-adjusted closes")],
                              required=False, label="Price basis for the whole file")
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.filter(profile=None).exclude(kind="alternative"), required=False,
                                        label="Only this investment (optional)")


class CatalogueDetailsForm(forms.Form):
    name = forms.CharField(max_length=200)
    code = forms.CharField(max_length=60, required=False)
    isin = forms.CharField(max_length=20, required=False)
    exchange = forms.CharField(max_length=10, required=False)
    currency = forms.CharField(max_length=3)
    asset_class = forms.ChoiceField(choices=ASSET_CLASSES)
    sector = forms.CharField(max_length=80, required=False)
    price_source = forms.ChoiceField(choices=[("manual", "Entered by hand"), ("yahoo", "Yahoo"), ("amfi", "AMFI"), ("mfapi", "mfapi.in"), ("upload", "Uploaded")])
    fallback_source = forms.ChoiceField(choices=[("", "None"), ("yahoo", "Yahoo"), ("amfi", "AMFI"), ("mfapi", "mfapi.in")], required=False)
    fetch_enabled = forms.BooleanField(required=False, label="Fetch nightly")

    def clean_currency(self):
        return self.cleaned_data["currency"].upper()


class CatalogueNewForm(forms.Form):
    kind = forms.ChoiceField(choices=[("share", "Share"), ("fund", "Mutual fund"), ("foreign", "Foreign"), ("index", "Index")])
    name = forms.CharField(max_length=200)
    code = forms.CharField(max_length=60, required=False)
    isin = forms.CharField(max_length=20, required=False)
    currency = forms.CharField(max_length=3, initial="INR")


class PruningForm(forms.Form):
    prune_live = forms.BooleanField(required=False, label="Prune the live database")
    prune_archive = forms.BooleanField(required=False, label="Prune the price archive")
    years = forms.IntegerField(min_value=2, max_value=50, label="Years kept in full daily detail")
    archive_confirmed = forms.BooleanField(required=False, label="I have downloaded a full price archive and I am keeping it")
