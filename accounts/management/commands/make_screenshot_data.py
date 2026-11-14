"""Fill a throwaway database with small, seeded demo data so the screenshots workflow has something to photograph.

It is for CI only (``.github/workflows/screenshots.yml``)::

    python manage.py make_screenshot_data > ids.json

It needs the first Admin to exist already (``create_first_admin``). It gives that Admin a Diary, a Fee Register and an
Investments profile, fills each (the Diary sample Subjects, a small fees planning dataset, a small investments bench
dataset), switches the Investments lookup off so no page needs the network, and prints one JSON object of record ids
for ``scripts/screenshots.py``. It refuses to run unless DJANGO_TESTING=1 is set (the workflow sets it), and refuses if
any profile other than the default ones or an earlier "Screenshots ..." one exists. It never prints settings or
environment variables. The lookup switch is suite-wide, which is why the guard comes before anything is written.
"""
import json
import os
import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import ROLE_EDITOR, Profile, User
from accounts.profiles import DEFAULT_PROFILE_NAME, ensure_default_profile, set_user_profiles
from accounts.suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS

SEED = 20260101


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def _guard(self):
        if os.environ.get("DJANGO_TESTING") != "1":
            raise CommandError("This command fills a throwaway database. Set DJANGO_TESTING=1 to confirm that it is one.")
        others = (
            Profile.objects.filter(deleted_at__isnull=True)
            .exclude(name__iexact=DEFAULT_PROFILE_NAME)
            .exclude(name__startswith="Screenshots ")
            .exists()
        )
        if others:
            raise CommandError("Refusing to run: this database has profiles other than the default and Screenshots ones.")

    def handle(self, *args, **options):
        self._guard()
        user = User.objects.filter(is_superuser=True).order_by("pk").first()
        if user is None:
            raise CommandError("Create the first Admin first (create_first_admin).")
        with transaction.atomic():
            ids = {}
            ids.update(self._diary(user))
            ids.update(self._fees(user))
            ids.update(self._investments(user))
            self._colleague_history(user)
        self.stdout.write(json.dumps(ids, sort_keys=True))

    def _profile(self, user, program, name):
        profile = ensure_default_profile(Profile, program, name)
        set_user_profiles(user, {profile: ROLE_EDITOR}, program)
        return profile

    def _colleague_history(self, user):
        """A second user who changed something in each profile, so every History tab shows two people in its Who column."""
        from diary import services as diary_services
        from fees.models import FeesHistory
        from investments.models import Broker, Instrument, Portfolio
        from investments.services import transactions

        colleague = User.objects.filter(username="colleague").first() or User.objects.create_user(username="colleague", first_name="Asha")
        for program, name in ((KEY_DIARY, "Screenshots Diary"), (KEY_FEES, "Screenshots Fees"), (KEY_INVESTMENTS, "Screenshots Investments")):
            profile = Profile.objects.get(name=name, program=program, deleted_at__isnull=True)
            set_user_profiles(colleague, {profile: ROLE_EDITOR}, program)
        diary = Profile.objects.get(name="Screenshots Diary", program=KEY_DIARY, deleted_at__isnull=True)
        diary_services.create(diary, colleague, "subject", name="Added by a colleague")
        fees = Profile.objects.get(name="Screenshots Fees", program=KEY_FEES, deleted_at__isnull=True)
        for action, kind, summary in (("create", "firm", "Added firm Colleague & Co"), ("update", "memo", "Changed memo 2026-27/7"),
                                      ("write_off", "memo", "Wrote off memo 2026-27/3")):
            FeesHistory.objects.create(profile=fees, user=colleague, action=action, object_type=kind, summary=summary)
        FeesHistory.objects.create(profile=fees, user=user, action="create", object_type="payment", summary="Added payment of 25000.00 on 2026-07-20")
        investments = Profile.objects.get(name="Screenshots Investments", program=KEY_INVESTMENTS, deleted_at__isnull=True)
        inst = Instrument.objects.filter(name="Family chit fund").first()
        portfolio = Portfolio.objects.filter(profile=investments).first()
        broker = Broker.objects.filter(profile=investments).first()
        if inst is not None and portfolio is not None and broker is not None:
            from datetime import date
            from decimal import Decimal

            transactions.add_lump_sum_transaction(investments, colleague, side="buy", date=date(2025, 1, 15), amount=Decimal("5000000"),
                                                  instrument=inst, portfolio=portfolio, broker=broker)

    def _diary(self, user):
        from diary.models import Subject
        from diary.sample_data import load_sample_data

        profile = self._profile(user, KEY_DIARY, "Screenshots Diary")
        load_sample_data(profile)
        subject = Subject.objects.filter(profile=profile, deleted_at__isnull=True).order_by("pk").first()
        return {"subject": subject.pk if subject else None}

    def _fees(self, user):
        from fees.models import Firm, Matter, Memo
        from fees.tests.datasets import build_planning_dataset

        profile = self._profile(user, KEY_FEES, "Screenshots Fees")
        build_planning_dataset(profile, memos=60, payments=80, allocations=90, firms=6, years=2, adjustments=False, seed=SEED)
        firm = Firm.objects.filter(profile=profile).order_by("pk").first()
        matter = Matter.objects.filter(profile=profile).order_by("pk").first()
        memo = Memo.objects.filter(profile=profile).order_by("pk").first()
        return {"firm": firm.pk if firm else None, "matter": matter.pk if matter else None, "memo": memo.pk if memo else None}

    def _investments(self, user):
        from investments import bench, bench_data
        from investments.models import Instrument, ProfileInvestment, Transaction
        from investments.services import instrument_search, masters

        profile = self._profile(user, KEY_INVESTMENTS, "Screenshots Investments")
        masters.ensure_default_portfolio(profile)
        masters.ensure_builtin_indices()
        random.seed(SEED)
        ctx = bench.BenchContext(profile=profile, user=user, seed=SEED, size="small")
        bench_data.build(ctx)
        instrument_search.set_lookup_enabled(False)  # the Buy page then never searches the NSE or AMFI lists
        held = Transaction.objects.filter(profile=profile).order_by("instrument_id").values_list("instrument_id", flat=True).first()
        spare = (
            Instrument.objects.filter(code__startswith="BENCH")
            .exclude(pk__in=ProfileInvestment.objects.filter(profile=profile).values("instrument_id"))
            .order_by("pk")
            .values_list("pk", flat=True)
            .first()
        )
        return {"investment": held, "spare_instrument": spare, "lump_investment": self._lump_sum(profile, user)}

    def _lump_sum(self, profile, user):
        """A Lump Sum alternative investment in crores: one purchase, one part sale, so its page, the Holdings row and the Sell page have large amounts."""
        from datetime import date
        from decimal import Decimal

        from investments.models import Broker, Portfolio
        from investments.services import masters, transactions

        inst = masters.create_instrument(profile, user, kind="alternative", name="Family chit fund", asset_class="debt", lump_sum=True, allow_duplicate=True)
        portfolio = Portfolio.objects.filter(profile=profile).first()
        broker = Broker.objects.filter(profile=profile).first() or Broker.objects.create(profile=profile, name="Direct")
        common = dict(instrument=inst, portfolio=portfolio, broker=broker)
        transactions.add_lump_sum_transaction(profile, user, side="buy", date=date(2023, 4, 1), amount=Decimal("125000000"), **common)
        transactions.add_lump_sum_transaction(profile, user, side="sell", date=date(2024, 10, 1), amount=Decimal("30000000"), remaining=Decimal("110000000"), **common)
        return inst.pk
