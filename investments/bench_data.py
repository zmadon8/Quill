"""Planning-dataset builder and the dataset-based operations for ``investments_memory_bench`` (plan 18 phase 0 and 26.1).

Planning size: about 5,000 transactions, 150 instruments and 10 years of daily prices (about 375,000 price rows; the
only price table today is ``ManualPrice``, which stands in for the fetched ``Price`` table of the price phase). The
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
    from investments.models import Broker, Instrument, ManualPrice, Portfolio, ProfileInvestment, Transaction

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
            batch.append(ManualPrice(instrument=inst, date=day, close=price))
            if len(batch) >= 2000:
                ManualPrice.objects.bulk_create(batch)
                batch = []
    if batch:
        ManualPrice.objects.bulk_create(batch)

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
    """FIFO plus XIRR for every holding (plan 26.1: 10 to 25 MB, a few hundred milliseconds of CPU)."""
    from investments.services import holdings

    rows, totals = holdings.compute(ctx.profile)
    ctx.extra["holdings"] = len(rows)
    if not rows:
        raise RuntimeError("the dataset produced no holdings")


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
