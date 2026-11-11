"""Planning-dataset builder and the dataset-based operations for ``investments_memory_bench`` (plan 18 phase 0 and 26.1).

Planning size: about 5,000 transactions, 150 instruments and 10 years of daily prices (about 375,000 ``Price`` rows). The
``small`` size is a quick smoke run. Everything is built in the bench's throwaway transaction, which is rolled back.
"""
import datetime
import random
from decimal import Decimal

from investments.bench import operation

SIZES = {"planning": dict(instruments=150, transactions=5000, years=10), "small": dict(instruments=20, transactions=500, years=1)}
BATCH = 500


def _bulk(model, objs):
    for start in range(0, len(objs), BATCH):
        model.objects.bulk_create(objs[start:start + BATCH])


def build(ctx):
    """Create the dataset in ``ctx.profile`` and remember the pieces on ``ctx.extra``."""
    from investments.models import Broker, Instrument, Portfolio, Price, ProfileInvestment, Transaction

    cfg = SIZES.get(ctx.size, SIZES["planning"])
    rng = random.Random(ctx.seed)
    profile = ctx.profile
    portfolios = [Portfolio.objects.create(profile=profile, name=f"Portfolio {i}") for i in range(2)]
    brokers = [Broker.objects.create(profile=profile, name=f"Broker {i}") for i in range(3)]
    kinds = ["share"] * 100 + ["fund"] * 40 + ["foreign"] * 10
    instruments = []
    for i in range(cfg["instruments"]):
        kind = kinds[i % len(kinds)]
        instruments.append(Instrument(profile=None, name=f"Bench {kind} {i}", kind=kind, code=f"BENCH{i}", currency="INR" if kind != "foreign" else "USD"))
    Instrument.objects.bulk_create(instruments)
    instruments = list(Instrument.objects.filter(code__startswith="BENCH").order_by("id"))
    ProfileInvestment.objects.bulk_create([ProfileInvestment(profile=profile, instrument=i) for i in instruments])

    today = datetime.date.today()
    start = today - datetime.timedelta(days=365 * cfg["years"])
    days = [start + datetime.timedelta(days=n) for n in range((today - start).days) if (start + datetime.timedelta(days=n)).weekday() < 5]
    batch = []
    for inst in instruments:
        price = Decimal(rng.randint(50, 3000))
        for day in days:
            price = max(Decimal(1), (price * Decimal(str(1 + rng.uniform(-0.02, 0.0215)))).quantize(Decimal("0.01")))
            batch.append(Price(instrument=inst, date=day, close=price, source="api", basis=""))
            if len(batch) >= 2000:
                Price.objects.bulk_create(batch)
                batch = []
    if batch:
        Price.objects.bulk_create(batch)

    per = max(2, cfg["transactions"] // len(instruments))
    txns = []
    for inst in instruments:
        held = {}
        when = start + datetime.timedelta(days=rng.randint(0, 200))
        for n in range(per):
            when += datetime.timedelta(days=rng.randint(1, max(2, (today - start).days // per)))
            if when >= today:
                break
            pf, br = rng.choice(portfolios), rng.choice(brokers)
            key = (pf.pk, br.pk)
            units_held = held.get(key, Decimal(0))
            if units_held > 5 and rng.random() < 0.3:
                units = (units_held * Decimal(str(rng.uniform(0.2, 0.8)))).quantize(Decimal("0.0001"))
                side = "sell"
                held[key] = units_held - units
            else:
                units = Decimal(rng.randint(1, 200))
                side = "buy"
                held[key] = units_held + units
            txns.append(Transaction(profile=profile, date=when, side=side, status="final", instrument=inst, portfolio=pf, broker=br,
                                    units=units, price=Decimal(rng.randint(50, 3000)), charges=Decimal("10")))
    _bulk(Transaction, txns)
    ctx.extra.update(instruments=instruments, portfolios=portfolios, brokers=brokers, n_transactions=len(txns))
    return len(txns)


@operation("dataset_build", 200.0, needs_dataset=True)
def dataset_build(ctx):
    ctx.extra["built"] = build(ctx)


@operation("dashboard", 25.0, needs_dataset=True)
def dashboard(ctx):
    """The whole Overview as it is first worked out (plan 26.1: 10 to 25 MB): FIFO plus XIRR for every holding, the index comparison,
    the value chart and the standard "Over time" table (whole history, 5, 3 and 1 years). Owner round 2026-11: this used to time only
    the holdings."""
    from investments.services import dashboard as dashboard_service

    data = dashboard_service.compute(ctx.profile)
    ctx.extra["holdings"] = len(data["rows"])
    if not data["rows"]:
        raise RuntimeError("the dataset produced no holdings")


def _get(ctx, path):
    """GET ``path`` as the bench user and render it (the same way ``menu_pages`` does); returns the response."""
    from django.test import RequestFactory, override_settings
    from django.urls import resolve

    plain_static = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    request = RequestFactory().get(path)
    request.user = ctx.user
    request.session = {}
    request.resolver_match = resolve(path)
    with override_settings(STORAGES=plain_static):
        response = request.resolver_match.func(request, *request.resolver_match.args, **request.resolver_match.kwargs)
        if hasattr(response, "render"):
            response.render()
    if response.status_code != 200:
        raise RuntimeError(f"{path} answered {response.status_code}")
    return response


def _forget_figures(ctx):
    """Drop the kept figures, so the next page is a first visit after an edit or a price update."""
    from investments.models import InvestmentsStatsCache

    InvestmentsStatsCache.objects.filter(profile=ctx.profile).delete()


@operation("page_overview_cold", 80.0, needs_dataset=True)
def page_overview_cold(ctx):
    """The Overview page as a first visit (nothing kept): what the person waits for after an edit or the nightly price update."""
    _forget_figures(ctx)
    _get(ctx, "/investments/dashboard/")


@operation("page_overview_warm", 80.0, needs_dataset=True)
def page_overview_warm(ctx):
    """The Overview page again, with the figures kept."""
    _get(ctx, "/investments/dashboard/")


@operation("page_holdings_cold", 80.0, needs_dataset=True)
def page_holdings_cold(ctx):
    """The Holdings page as a first visit (nothing kept)."""
    _forget_figures(ctx)
    _get(ctx, "/investments/holdings/")


@operation("page_holdings_warm", 80.0, needs_dataset=True)
def page_holdings_warm(ctx):
    """The Holdings page again, with the rows kept."""
    _get(ctx, "/investments/holdings/")


@operation("page_investment", 80.0, needs_dataset=True)
def page_investment(ctx):
    """One investment's page (the first instrument of the dataset)."""
    _get(ctx, f"/investments/holdings/{ctx.extra['instruments'][0].pk}/")


@operation("page_transactions", 80.0, needs_dataset=True)
def page_transactions(ctx):
    """The transaction list (first page of 50 of the 5,000)."""
    _get(ctx, "/investments/transactions/")


@operation("page_txn_new", 80.0, needs_dataset=True)
def page_txn_new(ctx):
    """The Add a purchase page (the form with every investment, folio and broker choice)."""
    _get(ctx, "/investments/transactions/buy/")


@operation("page_txn_edit", 80.0, needs_dataset=True)
def page_txn_edit(ctx):
    """The page of one existing transaction (its edit form)."""
    from investments.models import Transaction

    pk = Transaction.objects.filter(profile=ctx.profile).values_list("pk", flat=True).first()
    _get(ctx, f"/investments/transactions/{pk}/edit/")


@operation("sale_recheck", 5.0, needs_dataset=True)
def sale_recheck(ctx):
    """Adding one purchase re-checks the whole history of one investment."""
    from investments.models import Transaction
    from investments.services import transactions as tx

    inst = ctx.extra["instruments"][0]
    tx.add_transaction(ctx.profile, ctx.user, side="buy", instrument=inst, portfolio=ctx.extra["portfolios"][0], broker=ctx.extra["brokers"][0],
                       date=datetime.date.today(), units=Decimal(1), price=Decimal(100))
    Transaction.objects.filter(profile=ctx.profile).count()


@operation("backup_create", 40.0, needs_dataset=True)
def backup_create(ctx):
    """The suite backup now carries the investments tables (plan 26.1: growth of about 1 to 4 MB of JSON)."""
    import io

    from backups import services

    services.write_document(io.BytesIO(), __import__("django.utils.timezone", fromlist=["now"]).now())


@operation("archive_build", 15.0, needs_dataset=True)
def archive_build(ctx):
    """The full price archive, streamed to a temporary file one part at a time (plan 26.1: about 10 to 15 MB)."""
    import shutil

    from investments.services import archive

    paths = archive.build(max_part_bytes=15 * 1024 * 1024)
    ctx.extra["archive_parts"] = len(paths)
    shutil.rmtree(paths[0].parent, ignore_errors=True)


@operation("prune_run", 10.0, needs_dataset=True)
def prune_run(ctx):
    """One pruning run (chunks of about 5,000 rows; plan 26.1: under 10 MB)."""
    from investments.services import pruning

    pruning.configure(ctx.user, prune_live=True, prune_archive=True, years=2, full_archive_confirmed=True)
    ctx.extra["pruned"] = pruning.prune_prices(require_backup=False)


@operation("price_import", 25.0, needs_dataset=True)
def price_import_op(ctx):
    """A history upload of about 60,000 rows through the dry run and the apply (plan 26.1: a 10 MB file under 25 MB)."""
    import tempfile
    from pathlib import Path

    from investments.models import Price
    from investments.services import price_import

    inst = ctx.extra["instruments"][0]
    Price.objects.filter(instrument=inst).delete()
    path = Path(tempfile.mkdtemp()) / "bench.csv"
    start = datetime.date(2000, 1, 1)
    with open(path, "w") as out:
        out.write("symbol,date,close\n")
        for i in range(60000):
            out.write(f"{inst.code},{start + datetime.timedelta(days=i):%Y-%m-%d},{100 + (i % 977) / 7:.2f}\n")
    price_import.apply(path, today=datetime.date(2200, 1, 1))
    path.unlink()


@operation("update_batch", 15.0, needs_dataset=True)
def update_batch(ctx):
    """One Update Prices batch of ten symbols with a recorded Yahoo answer (plan 26.1: 5 to 15 MB)."""
    from unittest import mock

    from investments.adapters import http
    from investments.services import fetch
    from investments.tests.fakehttp import FakeNet, fixture

    net = FakeNet()
    net.add("chart", fixture("yahoo_chart_reliance.json"))
    with mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None):
        ids = [i.pk for i in ctx.extra["instruments"] if i.kind == "share"][:10]
        fetch.fetch_prices(ids=ids, spacing=0, today=datetime.date.today())


@operation("performance_3y", 15.0, needs_dataset=True)
def performance_3y(ctx):
    """The Performance table over three years (plan 26.1: 5 to 15 MB)."""
    from investments.services import performance

    start, end = performance.period_dates(preset=3)
    performance.table(ctx.profile, start=start, end=end)


@operation("chart_portfolio_5y", 15.0, needs_dataset=True)
def chart_portfolio_5y(ctx):
    """Chart A over five years: the value series, read one instrument at a time and sampled (plan 26.1: 5 to 15 MB)."""
    from investments.services import series

    days = series.sample_dates(datetime.date.today() - datetime.timedelta(days=5 * 365), datetime.date.today())
    values, flows = series.portfolio_value_series(ctx.profile, days)
    series.performance_index(values, flows)


@operation("annual_report", 20.0, needs_dataset=True)
def annual_report(ctx):
    """The Annual Report for last financial year (plan 26.1: 10 to 20 MB)."""
    from fees.services.financial_year import recent_financial_years

    from investments.services import annual

    annual.build(ctx.profile, recent_financial_years(2)[1])


@operation("alerts_and_insights", 15.0, needs_dataset=True)
def alerts_and_insights(ctx):
    from investments.services import alerts, insights

    alerts.evaluate(ctx.profile)
    insights.compute(ctx.profile)
