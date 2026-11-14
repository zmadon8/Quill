"""Django forms for the Investments pages. They only check the shape of the input; every rule lives in the services."""
from datetime import date

from django import forms

from investments.models import (
    ASSET_CLASSES, CA_BONUS, CA_DEMERGER, CA_SPLIT, HOLDABLE_KINDS, KIND_ALTERNATIVE, KIND_FOREIGN, KIND_FUND, KIND_SHARE, ORIGIN_PURCHASE, ORIGINS,
    CORPORATE_AUTO_KINDS, ZERO_PRICE_ORIGINS, Broker, CorporateAction, Folio, Instrument, Portfolio,
)


#: Applying a bonus or split: the program adds the units, the person records or imports them, or the program creates the transactions now.
CHOICES_FOR_UNITS = [("auto", "Automatic: the program adds the units"), ("link", "I will record or import the units as transactions"),
                     ("create", "Create the transactions for me now (editable)")]


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


class HeldSelect(forms.Select):
    """A drop-down whose options carry ``data-held="1"`` when the investment is held now, so the page can filter them (the "Held only" tick box)."""

    def __init__(self, *args, held_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.held_ids = set(held_ids)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        raw = getattr(value, "value", value)
        if raw not in (None, "") and str(raw).isdigit() and int(raw) in self.held_ids:
            option["attrs"]["data-held"] = "1"
        return option


class ProfileForm(forms.Form):
    """Base: remembers the profile and offers its portfolios, brokers and investments."""

    #: Investment fields that get a "Held only" tick box, and whether it starts ticked (set by ``mark_held``).
    held_fields = ()
    held_default = True
    #: Fields tucked under a "More" fold on the page (see ``_form.html``); it opens when one of them holds a value or an error.
    more_fields = ()
    more_label = "More"
    #: Names of the "More" fields that make up its first line (their notes are gathered in one paragraph below it, the rest follow on one line).
    more_first = ()
    #: Fields that start a new line of the form (a row break is drawn before them).
    break_before = ()

    def __init__(self, *args, profile=None, held_units=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        #: ``{instrument id: units}`` held now; a view with several forms computes it once and passes it to each.
        self.held_units = held_units
        #: The stored NSE / AMFI record picked in the Investment box and not yet an Instrument (see ``add_pick_fields``); made at save.
        self.new_pick = None

    def add_pick_fields(self):
        """Let the Investment box pick a share or fund from the NSE / AMFI lists: two hidden fields carry the source and code, and the
        investment itself becomes optional while a pick is present (``clean_pick`` checks one or the other)."""
        self.fields["new_source"] = forms.CharField(required=False, max_length=10, widget=forms.HiddenInput)
        self.fields["new_code"] = forms.CharField(required=False, max_length=60, widget=forms.HiddenInput)
        self.fields["instrument"].required = False
        self.has_pick = True

    has_pick = False

    def clean_pick(self, cleaned):
        """Resolve the picked code against the stored lists (never trusting a posted name); a code not in them is a form error."""
        if not self.has_pick:
            return
        from investments.services import instrument_search

        source, code = (cleaned.get("new_source") or "").strip(), (cleaned.get("new_code") or "").strip()
        if cleaned.get("instrument"):
            return   # a chosen investment wins over a stale pick
        if source or code:
            self.new_pick = instrument_search.lookup_record(source, code)
            if self.new_pick is None:
                self.add_error("instrument", "That share or fund is not in the NSE / AMFI list. Search and choose it again.")
        elif "instrument" not in self.errors:
            self.add_error("instrument", "This field is required.")

    @property
    def pick_name(self):
        """The stored name of the NSE / AMFI investment posted in ``new_source`` / ``new_code``, so a page shown again after an error names
        it instead of its code. Empty when nothing was picked, an investment was chosen instead, or the code is not in the stored lists."""
        if not (self.has_pick and self.is_bound) or self["instrument"].value():
            return ""
        from investments.services import instrument_search

        record = instrument_search.lookup_record(self["new_source"].value(), self["new_code"].value())
        return record["name"] if record else ""

    @property
    def pick_line(self):
        """The "Share/Fund · code · ISIN · plan · option" hint for the posted NSE / AMFI pick (as the box shows it after choosing), else empty.
        For an existing fund chosen in the box it is "code · ISIN · plan · option" (no "New")."""
        if not (self.has_pick and self.is_bound):
            return ""
        from investments.services import instrument_search

        chosen = self["instrument"].value()
        if chosen:
            inst = self.fields["instrument"].queryset.filter(pk=chosen).first() if str(chosen).isdigit() else None
            if inst is None or inst.kind != "fund":
                return ""
            plan, option = instrument_search.fund_plans([inst.code]).get(inst.code, ("", ""))
            bits = [inst.code, inst.isin, plan and f"{plan} Plan", option and f"{option} Option"]
            return " \u00b7 ".join(b for b in bits if b)

        r = instrument_search.lookup_record(self["new_source"].value(), self["new_code"].value())
        if not r:
            return ""
        bits = ["Fund" if r["kind"] == "fund" else "Share", r["code"], r["isin"], r["plan"] and f"{r['plan']} Plan", r["option"] and f"{r['option']} Option"]
        return "New \u00b7 " + " \u00b7 ".join(b for b in bits if b)

    @property
    def more_open(self):
        for name in self.more_fields:
            if name not in self.fields:
                continue
            if self.errors.get(name):
                return True
            value = self[name].value()
            if value not in (None, "", 0, "0") and str(value) != str(self.fields[name].initial or ""):
                return True
        return False

    def mark_held(self, *names, default=True):
        """Mark each named investment field's options held or not (``data-held``) and ask for a "Held only" tick box beside it. The field's
        queryset is unchanged, so every investment is still accepted when the form is posted."""
        from investments.services import holdings

        if self.held_units is None:
            self.held_units = holdings.held_units(self.profile)
        held = set(self.held_units)
        for name in names:
            field = self.fields[name]
            widget = HeldSelect(attrs=field.widget.attrs, held_ids=held)
            widget.is_required = field.required
            field.widget = widget
            widget.choices = field.choices
        self.held_fields = tuple(names)
        self.held_default = bool(default)
        return held

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
    new_folio = forms.CharField(label="New Folio Number", required=False, max_length=60)
    units = MoneyField(label="Units", required=False, min_value=0)
    origin = forms.ChoiceField(choices=ORIGINS, initial=ORIGIN_PURCHASE, required=False, label="How were these units acquired?",
                               help_text="Bonus shares, split units and shares received on a demerger need no price: they are added at a cost of 0. A demerger's cost comes from the parent's shares, not from this entry.")
    corporate_action = forms.ModelChoiceField(queryset=CorporateAction.objects.none(), required=False, label="Corporate action (bonus, split or demerger)")
    price = MoneyField(label="Price per unit", required=False, min_value=0)
    lump_amount = MoneyField(label="Amount", required=False, min_value=0, help_text="Lump Sum investment: the money paid or received")
    remaining = MoneyField(label="Amount remaining after this sale", required=False, min_value=0,
                           help_text="What you still hold of this investment after the sale (0 if all of it is sold)")
    charges = MoneyField(label="Charges", required=False, min_value=0, initial=0)
    allotment_date = forms.DateField(
        widget=date_widget(), label="Allotment date", required=False,
        help_text="When the units were credited to you, if later than Date. It starts the holding period and the order units are sold in. Leave blank if the same as Date.")
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
        # Lump Sum investments are asked for an amount (and, on a sale, what remains) instead of units and price. The page shows these two
        # fields, and hides Units and Price, once such an investment is chosen; clean() enforces whichever set applies.
        if mode not in ("buy", "sell"):
            del self.fields["lump_amount"]
        if mode != "sell":
            del self.fields["remaining"]
        if awaiting:
            for name in ("units", "price", "allotment_date", "origin", "corporate_action"):
                del self.fields[name]
            self.fields["amount"].required = True
            self.fields["amount"].label = "Amount paid" if mode == "awaiting_buy" else "Expected proceeds"
            self.fields["date"].label = "Date paid" if mode == "awaiting_buy" else "Date of the redemption"
        else:
            del self.fields["amount"]
            del self.fields["expected_allotment_date"]
            del self.fields["reference"]
            self.fields["units"].required = mode not in ("buy", "sell")   # buy and sell check it in clean(): a Lump Sum asks for an amount instead
            if mode in ("sell", "edit_sell"):
                del self.fields["allotment_date"]
                del self.fields["origin"]
                del self.fields["corporate_action"]
                self.fields["price"].required = mode != "sell"
            else:
                # A purchase needs its price; bonus and split units and shares received on a demerger do not (checked in clean()).
                self.fields["corporate_action"].queryset = self.actions()
                self.fields["corporate_action"].label_from_instance = lambda a: f"{a.instrument.name}: {a.describe()} ({a.ex_date:%d %b %Y})"
        if mode in ("sell", "awaiting_sell", "edit_sell"):
            del self.fields["new_folio"]
            # A sale can only be of what is held (an edit also keeps the entry's own investment); there is no "Held only" box to untick.
            from investments.services import holdings

            if self.held_units is None:
                self.held_units = holdings.held_units(self.profile)
            held = set(self.held_units)
            # Back-dated sales are allowed, so investments sold out since (any purchase, opening or transfer-in on record) are offered too, in
            # their own group. One cheap query; the real check is on the sale's date (see clean()).
            from investments.models import STATUS_FINAL, Transaction

            history = set(Transaction.objects.filter(profile=self.profile, status=STATUS_FINAL, side="buy").values_list("instrument_id", flat=True).distinct())
            own = set()
            if mode == "edit_sell" or (mode == "awaiting_sell" and self.initial.get("instrument")):
                own.add(getattr(self.initial.get("instrument"), "pk", self.initial.get("instrument")))
            sold_out = (history | own) - held
            qs = self.fields["instrument"].queryset.filter(pk__in=held | sold_out)
            self.fields["instrument"].queryset = qs
            self.fields["instrument"].error_messages["invalid_choice"] = "Choose an investment you hold, or held in the past, from the list."
            names = [(i.pk, str(i), i.pk in sold_out) for i in qs]
            self.fields["instrument"].choices = [("", "---------")] + [(pk, label) for pk, label, old in names if not old] + (
                [("Sold out (for back-dated sales)", [(pk, label) for pk, label, old in names if old])] if sold_out and any(n[2] for n in names) else [])
            self.break_before = ("units",)
            # A sale asks for the date, investment, where it was held, units and price; charges and a note sit under "More".
            self.more_fields = tuple(n for n in ("charges", "note") if n in self.fields)
            self.more_label = "Charges and note"
        elif mode in ("buy", "edit"):
            # A purchase asks for the date, investment, where it goes, units and price; the rest sits under "More".
            self.more_fields = tuple(n for n in ("folio", "new_folio", "origin", "allotment_date", "charges", "corporate_action", "note") if n in self.fields)
            self.more_label = "Allotment date, charges, folio and more"
            self.more_first = tuple(n for n in ("folio", "new_folio", "origin") if n in self.fields)
        elif awaiting:
            self.more_fields = tuple(n for n in ("charges", "note") if n in self.fields)
            self.more_label = "Charges and note"
        if mode.startswith("edit"):
            self.fields["instrument"].disabled = False
        if mode in ("buy", "awaiting_buy"):
            self.add_pick_fields()
        # "Held only" starts ticked on every form; an edit of an entry for something no longer held starts unticked so the chosen investment shows.
        held = self.mark_held("instrument", default=True)
        if mode in ("sell", "awaiting_sell", "edit_sell"):
            self.held_fields = ()
        if mode.startswith("edit") or "instrument" in self.initial:
            chosen = getattr(self.initial.get("instrument"), "pk", self.initial.get("instrument"))
            if self.held_default and chosen and chosen not in held:
                self.held_default = False

    def clean_amounts(self, cleaned, inst):
        """Units and price are required on a plain buy or sale unless the investment is a Lump Sum, which needs its amount (and, when sold, what
        remains) instead. A Lump Sum purchase is recorded as units = amount at a price of 1; a sale's units and price are worked out when it is saved."""
        if inst and inst.lump_sum:
            need = ("lump_amount", "remaining") if self.mode == "sell" else ("lump_amount",)
            for name in need:
                if cleaned.get(name) is None and name not in self.errors:
                    self.add_error(name, "This field is required.")
            if cleaned.get("lump_amount") is not None and cleaned["lump_amount"] <= 0:
                self.add_error("lump_amount", "The amount must be above zero.")
        elif cleaned.get("units") is None and "units" not in self.errors:
            self.add_error("units", "This field is required.")
        if self.mode == "sell" and not (inst and inst.lump_sum) and cleaned.get("price") is None and "price" not in self.errors:
            self.add_error("price", "This field is required.")

    def actions(self):
        """The bonuses, splits and demergers the person may link units to: those on investments they can see (a demerger also by its new company)."""
        from django.db.models import Q

        visible = Q(instrument__profile=None) | Q(instrument__profile=self.profile)
        return CorporateAction.objects.filter(visible, kind__in=(CA_BONUS, CA_SPLIT, CA_DEMERGER)).select_related("instrument", "target_instrument").order_by("-ex_date")

    def clean(self):
        cleaned = super().clean()
        self.clean_pick(cleaned)
        inst, day = cleaned.get("instrument"), cleaned.get("date")
        if self.mode in ("sell", "awaiting_sell") and inst and day:
            from investments.services import transactions as tx

            if not tx.available_by_bucket(self.profile, inst, day):
                self.add_error("instrument", f"You held none of this investment on {day.day} {day:%b %Y}.")
        if self.mode in ("buy", "sell"):
            self.clean_amounts(cleaned, inst)
        folio = cleaned.get("folio")
        if folio and self.new_pick:
            self.add_error("folio", "Choose a folio after the investment has been added.")
        if folio and cleaned.get("instrument") and (folio.instrument_id != cleaned["instrument"].pk or (cleaned.get("portfolio") and folio.portfolio_id != cleaned["portfolio"].pk)):
            self.add_error("folio", "That folio belongs to a different investment or portfolio.")
        if "origin" in self.fields and not (inst and inst.lump_sum):
            origin = cleaned["origin"] = cleaned.get("origin") or ORIGIN_PURCHASE
            if origin == ORIGIN_PURCHASE:
                if cleaned.get("price") is None and "price" not in self.errors:
                    self.add_error("price", "This field is required.")
            elif origin in ZERO_PRICE_ORIGINS:
                cleaned["price"] = 0
            elif cleaned.get("price") is None:
                cleaned["price"] = 0
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
        self.add_pick_fields()
        self.mark_held("instrument", default=True)

    def clean(self):
        cleaned = super().clean()
        self.clean_pick(cleaned)
        if cleaned.get("folio") and self.new_pick:
            self.add_error("folio", "Choose a folio after the investment has been added.")
        return cleaned


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
        self.mark_held("instrument", default=True)


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
        self.mark_held("from_instrument", default=True)


KIND_CHOICES = [(KIND_SHARE, "Share or ETF"), ("fund", "Mutual fund"), (KIND_ALTERNATIVE, "Alternative investment"), (KIND_FOREIGN, "Foreign investment")]


class InstrumentForm(forms.Form):
    kind = forms.ChoiceField(choices=KIND_CHOICES)
    name = forms.CharField(max_length=200)
    code = forms.CharField(max_length=60, required=False, label="Code (ticker or AMFI scheme code)")
    isin = forms.CharField(max_length=20, required=False, label="ISIN")
    currency = forms.CharField(max_length=3, initial="INR", required=False)
    asset_class = forms.ChoiceField(choices=ASSET_CLASSES, initial="equity", label="Asset class")
    sector = forms.CharField(max_length=80, required=False)
    interest_rate = forms.DecimalField(max_digits=7, decimal_places=3, min_value=0, max_value=1000, required=False, label="Interest rate % (optional)")
    interest_type = forms.ChoiceField(choices=[("compound", "Compound interest (yearly)"), ("simple", "Simple interest")], initial="compound", required=False,
                                      label="Interest type")
    maturity_date = forms.DateField(widget=date_widget(), required=False, label="Maturity date (optional)")
    taxed_as_interest = forms.BooleanField(required=False, label="Taxed as Interest",
                                           help_text="Profit or loss on sales is reported as Interest Income, not Capital Gains")
    lump_sum = forms.BooleanField(required=False, label="Lump Sum (alternative investments only)",
                                  help_text="Bought and sold in lump sums of money: no units or price per unit are asked for. Cannot be changed once there are transactions.")

    # The kinds each optional field is asked for. A field not asked for is removed from the form, so it is neither shown nor read from a
    # POST; the view and masters.create_instrument fill in the default for it.
    FIELD_KINDS = {
        "isin": (KIND_SHARE, "fund"),
        "currency": (KIND_FOREIGN,),
        "asset_class": ("fund", KIND_ALTERNATIVE),
        "sector": (KIND_SHARE,),
        "interest_rate": (KIND_ALTERNATIVE,),
        "interest_type": (KIND_ALTERNATIVE,),
        "maturity_date": (KIND_ALTERNATIVE,),
        "taxed_as_interest": (KIND_ALTERNATIVE,),
        "lump_sum": (KIND_ALTERNATIVE,),
    }

    def __init__(self, *args, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        data = args[0] if args and args[0] is not None else kwargs.get("data")
        kind = kind or (data.get("kind") if data else None) or (kwargs.get("initial") or {}).get("kind")
        if kind in dict(KIND_CHOICES):
            for name, kinds in self.FIELD_KINDS.items():
                if kind not in kinds:
                    del self.fields[name]

    def clean_currency(self):
        return (self.cleaned_data.get("currency") or "INR").upper()

    def clean_interest_type(self):
        return self.cleaned_data.get("interest_type") or "compound"


class OwnInstrumentForm(InstrumentForm):
    """Edit an investment the profile owns (an alternative investment): the same fields and limits as adding one, without the kind."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, kind=KIND_ALTERNATIVE, **kwargs)
        del self.fields["kind"]


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

    interest_rate = forms.DecimalField(max_digits=7, decimal_places=3, min_value=0, max_value=1000, required=False, label="Interest rate % (optional)")
    interest_type = forms.ChoiceField(choices=[("compound", "Compound interest (yearly)"), ("simple", "Simple interest")], initial="compound", required=False,
                                      label="Interest type")
    maturity_date = forms.DateField(widget=date_widget(), required=False, label="Maturity date (optional)")

    def __init__(self, *args, with_sector=True, **kwargs):
        super().__init__(*args, **kwargs)
        if with_sector:
            self.fields["sectoral_index"].queryset = Instrument.objects.filter(profile=None, kind="index").order_by("name")
            for name in ("interest_rate", "interest_type", "maturity_date"):
                del self.fields[name]
        else:
            del self.fields["sectoral_index"]

    def clean_interest_type(self):
        return self.cleaned_data.get("interest_type") or "compound"


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # One choice for each kind of corporate action: logged without asking, or waiting for the person to approve it (the default).
        for key, label in CORPORATE_AUTO_KINDS:
            self.fields[f"auto_{key}"] = forms.ChoiceField(choices=[("ask", "Ask me to approve"), ("auto", "Log automatically")], required=False,
                                                           label=label, initial="ask")

    def corporate_auto(self, current=None):
        """The ``corporate_auto`` setting from the cleaned choices; a kind left out of the form keeps its current value."""
        out = dict(current or {})
        for key, _label in CORPORATE_AUTO_KINDS:
            choice = self.cleaned_data.get(f"auto_{key}")
            if choice:
                out[key] = choice == "auto"
        return out


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
    archive_confirmed = forms.BooleanField(required=False, label="I have downloaded a full price archive and I am keeping it (optional note)")


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
        self.mark_held("instrument", default=True)


class CorporateActionForm(ProfileForm):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), label="Investment")
    ex_date = forms.DateField(widget=date_widget(), label="Ex-date (or allotment date for a bonus)")
    kind = forms.ChoiceField(choices=[("split", "Split"), ("bonus", "Bonus"), ("demerger", "Demerger (shares in a new company)"),
                                      ("other", "Other (merger, ...)")])
    ratio_old = forms.DecimalField(required=False, min_value=0, decimal_places=4, max_digits=12, label="For every (old shares)")
    ratio_new = forms.DecimalField(required=False, min_value=0, decimal_places=4, max_digits=12,
                                   label="New shares (split: becomes; bonus: free; demerger: new company shares received)")
    target_instrument = forms.ModelChoiceField(queryset=Instrument.objects.none(), required=False, label="Demerger: the new company",
                                               help_text="Add the new company under Investments first if it is not listed.")
    cost_percent_to_target = forms.DecimalField(required=False, min_value=0, max_value=100, decimal_places=4, max_digits=7,
                                                label="Demerger: percent of the cost that moves to the new company",
                                                help_text="From the company's notice. Your CA should confirm it. The parent's shares keep the rest. 0 leaves all the cost with the parent's shares; "
                                                          "100 moves all of it. You can change it later.")
    notes = forms.CharField(required=False, max_length=300)
    apply_now = forms.BooleanField(required=False, initial=True, label="Apply it to this profile now")
    choice = forms.ChoiceField(choices=CHOICES_FOR_UNITS, required=False, initial="auto", label="Bonus or split: who adds the units?")
    inherit_dates = forms.BooleanField(required=False, initial=False, label="Demerger: the new shares keep the parent shares' purchase dates")

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.fields["instrument"].queryset = self.instruments().exclude(kind="alternative")
        self.fields["target_instrument"].queryset = self.instruments()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == "demerger":
            if not cleaned.get("target_instrument"):
                self.add_error("target_instrument", "Choose the new company whose shares are received.")
            if cleaned.get("cost_percent_to_target") is None:
                self.add_error("cost_percent_to_target", "Enter the percentage of the cost that moves, from 0 to 100.")
        return cleaned


class CorporateActionEditForm(CorporateActionForm):
    """Change a recorded action: its date, ratio, notes and, for a demerger, the new company and the cost split. The investment and the kind stay."""

    def __init__(self, *args, profile=None, action=None, **kwargs):
        super().__init__(*args, profile=profile, **kwargs)
        self.action = action
        for name in ("instrument", "kind", "apply_now", "choice", "inherit_dates"):
            del self.fields[name]
        if action.kind != "demerger":
            del self.fields["target_instrument"]
            del self.fields["cost_percent_to_target"]
        if action.kind == "other":
            del self.fields["ratio_old"]
            del self.fields["ratio_new"]

    def clean(self):
        cleaned = forms.Form.clean(self)
        if self.action.kind == "demerger":
            if not cleaned.get("target_instrument"):
                self.add_error("target_instrument", "Choose the new company whose shares are received.")
            if cleaned.get("cost_percent_to_target") is None:
                self.add_error("cost_percent_to_target", "Enter the percentage of the cost that moves, from 0 to 100.")
        return cleaned


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
    """One switch per kind of alert, each next to its threshold. Insights (Settings > Insights) are separate and are not alerts."""
    rule_a_fall_enabled = forms.BooleanField(required=False, label="Alert me when an investment falls in a day")
    rule_a_fall_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Fall in a day %")
    rule_a_rise_enabled = forms.BooleanField(required=False, label="Alert me when an investment rises in a day")
    rule_a_rise_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Rise in a day %")
    rule_a_window_enabled = forms.BooleanField(required=False, label="Alert me when an investment falls over several days")
    rule_a_window_days = forms.IntegerField(min_value=2, max_value=365, label="Over this many days")
    rule_a_window_fall_pct = forms.DecimalField(required=False, min_value=0, max_digits=6, decimal_places=2, label="Fall over those days % (blank: off)")
    rule_b_loss_enabled = forms.BooleanField(required=False, label="Alert me when a holding is below what I paid")
    rule_b_loss_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Below cost %")
    rule_b_gain_enabled = forms.BooleanField(required=False, label="Alert me when a holding is above what I paid")
    rule_b_gain_pct = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Above cost %")
    guardrails_enabled = forms.BooleanField(required=False, label="Alert me when a guardrail I set is reached")
    guardrail_replaces_global = forms.BooleanField(required=False, label="A guardrail on a holding replaces the daily and cost alerts for it")
    maturity_enabled = forms.BooleanField(required=False, label="Alert me before an alternative investment matures")
    maturity_alert_days = forms.IntegerField(min_value=0, max_value=365, label="Warn before a maturity date (days)")
    source_problems_enabled = forms.BooleanField(required=False, label="Warn me on the Alerts page when a price or list source cannot be read")
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
    rupee_decimals = forms.TypedChoiceField(choices=[("", "Standard (paise only when there are some)"), ("0", "0"), ("1", "1"), ("2", "2")],
                                            coerce=int, empty_value=None, required=False, label="Decimals in full rupee figures",
                                            help_text="Full figures show exactly this many decimals; short figures (k, lac, cr) always show up to 2. "
                                                      "Display only: Excel exports and every calculation keep the exact amount.")
    column_picker = forms.BooleanField(required=False, label="Column picker",
                                       help_text="A Columns menu above each table, as in the Fee Register, to choose the columns you see. "
                                                 "Your choice is remembered in this browser, table by table.")
    default_exchange = forms.ChoiceField(choices=[("NS", "NSE (.NS)"), ("BO", "BSE (.BO)")], label="Exchange for new shares")
