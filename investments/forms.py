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
    sectoral_index = forms.ModelChoiceField(queryset=Instrument.objects.none(), required=False, empty_label="None (the Default Index only)",
                                            label="Sector index",
                                            help_text="The index this investment is also compared with, while sector comparisons are on (Settings > General). "
                                                      "Add more in Settings > Indices.")
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    links = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Website links (one per line: label | address)")

    def __init__(self, *args, with_sector=True, **kwargs):
        super().__init__(*args, **kwargs)
        if with_sector:
            self.fields["sectoral_index"].queryset = Instrument.objects.filter(profile=None, kind="index").order_by("name")
        else:
            del self.fields["sectoral_index"]


class GeneralSettingsForm(forms.Form):
    sip_mode = forms.ChoiceField(choices=[("pending", "Pending until confirmed (default)"), ("final", "Created as final")], label="SIP entries")
    awaiting_treatment = forms.ChoiceField(choices=[("cost", "Count at cost (default)"), ("leave_out", "Leave out until allotted")], label="Awaiting allotment")
    awaiting_reminder_days = forms.IntegerField(min_value=1, max_value=60, label="Reminder after (days)")
    corporate_action_mode = forms.ChoiceField(choices=[("tag", "Tag and banner (default)"), ("block", "Block until confirmed")], label="Pending corporate actions")
    long_term_days = forms.IntegerField(min_value=1, max_value=3650, label="Long-term after (days held)")
    default_index = forms.ModelChoiceField(queryset=Instrument.objects.filter(kind="index"), required=False, label="Default Index", empty_label="Nifty 50 (default)")
    sectoral_enabled = forms.BooleanField(required=False, label="Use a sectoral index as well",
                                          help_text="Compare each investment with its own sector index too. Choose them, and add indices, in Settings > Indices.")
    include_dividends = forms.BooleanField(required=False, label="Include dividends in XIRR")
    alt_treatment = forms.ChoiceField(choices=[("unchanged", "Unchanged until the next update"), ("averaged", "Averaged out between updates")], label="Alternative investments between updates")
    money_default = forms.ChoiceField(choices=[("auto", "Short (Thousand, Lac, Crore)"), ("full", "Full Figures")], label="Starting number display")


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
    fallback_source = forms.ChoiceField(choices=[("", "None"), ("yahoo", "Yahoo"), ("amfi", "AMFI"), ("mfapi", "mfapi.in"), ("twelvedata", "Twelve Data")], required=False)
    fetch_enabled = forms.BooleanField(required=False, label="Fetch nightly")
    next_results_date = forms.DateField(required=False, widget=date_widget(), label="Next results date (optional)")

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


class DividendForm(ProfileForm):
    date = forms.DateField(widget=date_widget(), initial=date.today, label="Date received")
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none())
    broker = forms.ModelChoiceField(queryset=Broker.objects.none(), empty_label="Choose a broker")
    folio = forms.ModelChoiceField(queryset=Folio.objects.none(), required=False, label="Folio (optional)")
    amount = MoneyField(label="Amount received (Rs, after tax deducted)", min_value=0)
    tax_deducted = MoneyField(label="Tax deducted (optional)", required=False, min_value=0)
    note = forms.CharField(required=False, max_length=200)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["instrument"].queryset = self.instruments().exclude(kind="alternative")
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)
        self.fields["broker"].queryset = self.brokers()
        self.fields["folio"].queryset = Folio.objects.filter(profile=profile)


class CorporateActionForm(ProfileForm):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    ex_date = forms.DateField(widget=date_widget(), label="Ex-date (or allotment date for a bonus)")
    kind = forms.ChoiceField(choices=[("split", "Split"), ("bonus", "Bonus"), ("other", "Other (merger, demerger)")])
    ratio_old = forms.DecimalField(required=False, min_value=0, decimal_places=4, max_digits=12, label="For every (old shares)")
    ratio_new = forms.DecimalField(required=False, min_value=0, decimal_places=4, max_digits=12, label="New shares (split: becomes; bonus: free)")
    notes = forms.CharField(required=False, max_length=300)
    apply_now = forms.BooleanField(required=False, initial=True, label="Apply it to this profile now")

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["instrument"].queryset = self.instruments().exclude(kind="alternative")


class GuardrailForm(ProfileForm):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none())
    kind = forms.ChoiceField(choices=[("target_gain", "Target gain %"), ("stop_loss", "Stop-loss % below cost"), ("price_above", "Price at or above"),
                                      ("price_below", "Price at or below"), ("fall_from_peak", "Fall from peak since purchase %")])
    value = MoneyField(min_value=0)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["instrument"].queryset = self.instruments()
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)


class AlertSettingsForm(forms.Form):
    rule_a_enabled = forms.BooleanField(required=False, label="Rule A: against the previous close")
    rule_a_fall_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Fall in a day %")
    rule_a_rise_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Rise in a day %")
    rule_a_window_days = forms.IntegerField(min_value=2, max_value=365, label="Over this many days")
    rule_a_window_fall_pct = forms.DecimalField(required=False, min_value=0, max_digits=6, decimal_places=2, label="Fall over those days % (blank: off)")
    rule_b_enabled = forms.BooleanField(required=False, label="Rule B: against your cost")
    rule_b_loss_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Below cost %")
    rule_b_gain_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Above cost %")
    guardrail_replaces_global = forms.BooleanField(required=False, label="A guardrail on a holding replaces the global rules for it")
    maturity_alert_days = forms.IntegerField(min_value=0, max_value=365, label="Warn before a maturity date (days)")
    alert_email = forms.BooleanField(required=False, label="Email me alerts that triggered overnight")


class SipForm(ProfileForm):
    amount = MoneyField(min_value=0, label="Amount each month (Rs)")
    day_of_month = forms.IntegerField(min_value=1, max_value=31, label="Day of the month")
    portfolio = forms.ModelChoiceField(queryset=Portfolio.objects.none())
    broker = forms.ModelChoiceField(queryset=Broker.objects.none(), empty_label="Choose a broker")
    folio = forms.ModelChoiceField(queryset=Folio.objects.none(), required=False, label="Folio (optional)")
    start_date = forms.DateField(widget=date_widget(), label="First SIP on or after")
    end_date = forms.DateField(widget=date_widget(), required=False, label="Last date (optional)")

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["portfolio"].queryset = Portfolio.objects.filter(profile=profile)
        self.fields["broker"].queryset = self.brokers()
        self.fields["folio"].queryset = Folio.objects.filter(profile=profile)


class DisplaySettingsForm(forms.Form):
    my_money = forms.ChoiceField(choices=[("auto", "Short (Thousand, Lac, Crore)"), ("full", "Full Figures")], label="Number display for you")
    money_default = forms.ChoiceField(choices=[("auto", "Short (Thousand, Lac, Crore)"), ("full", "Full Figures")], label="Starting choice for new people in this profile")
    compact_tables = forms.BooleanField(required=False, label="Compact tables")
    units_decimals = forms.TypedChoiceField(choices=[("", "Standard (as many as needed, up to 4)"), ("0", "0"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4")],
                                            coerce=int, empty_value=None, required=False, label="Decimals in units",
                                            help_text="How many decimals units show (for example 4,820.512 or 4,820.51). Display only: units are kept exact.")
    rupee_decimals = forms.TypedChoiceField(choices=[("", "Standard (paise only when there are some; short figures up to 2)"), ("0", "0"), ("1", "1"), ("2", "2")],
                                            coerce=int, empty_value=None, required=False, label="Decimals in rupee figures",
                                            help_text="Full figures show exactly this many decimals; short figures (lac, cr) show up to this many. "
                                                      "Display only: Excel exports and every calculation keep the exact amount.")
    column_picker = forms.BooleanField(required=False, label="Column picker",
                                       help_text="A Columns menu above each table, as in the Fee Register, to choose the columns you see. "
                                                 "Your choice is remembered in this browser, table by table.")
    default_exchange = forms.ChoiceField(choices=[("NS", "NSE (.NS)"), ("BO", "BSE (.BO)")], label="Exchange for new shares")
