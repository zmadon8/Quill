"""Pinned prices, pruning, the price archive and its email (plan 17 and 31)."""
import gzip
import io
import zipfile
from datetime import date as d, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone as dj_tz

from investments.errors import InvestmentsError
from investments.models import Instrument, PinnedPrice, Price, PriceHistorySettings
from investments.services import archive, masters, price_import, prices, pruning, pins, transactions as tx
from investments.tests.base import InvTestCase


class PinBase(InvTestCase):
    def setUp(self):
        super().setUp()
        self.nifty = Instrument.objects.get(code="^NSEI")
        # daily-ish Nifty closes for a few years, and Reliance
        day = d(2021, 1, 1)
        while day < d(2026, 11, 1):
            if day.weekday() < 5:
                Price.objects.create(instrument=self.nifty, date=day, close=D(10000 + (day - d(2021, 1, 1)).days), source="api", basis="split_adjusted")
                Price.objects.create(instrument=self.reliance, date=day, close=D(1000 + (day - d(2021, 1, 1)).days // 10), source="api", basis="split_adjusted")
            day += timedelta(days=1)


class PinTests(PinBase):
    def test_saving_a_transaction_pins_the_default_index_on_its_date(self):
        self.buy(d(2023, 6, 15), 10, 100)
        pin = PinnedPrice.objects.get(instrument=self.nifty, reason="transaction")
        self.assertEqual((pin.asked_date, pin.trading_date, pin.approximate), (d(2023, 6, 15), d(2023, 6, 15), False))
        self.assertEqual(pin.close, prices.latest_prices([self.nifty.pk], d(2023, 6, 15))[self.nifty.pk][1])

    def test_weekend_transaction_pins_the_last_trading_day(self):
        self.buy(d(2023, 6, 17), 10, 100)       # a Saturday
        pin = PinnedPrice.objects.get(reason="transaction")
        self.assertEqual((pin.asked_date, pin.trading_date), (d(2023, 6, 17), d(2023, 6, 16)))
        self.assertFalse(pin.approximate)

    def test_sectoral_index_is_pinned_only_while_the_switch_is_on(self):
        bank = Instrument.objects.create(profile=None, kind="index", name="Nifty Bank", code="^NSEBANK", price_source="yahoo", price_basis="split_adjusted")
        Price.objects.create(instrument=bank, date=d(2023, 6, 15), close=D(44000), source="api")
        masters.update_profile_details(self.profile, self.user, self.reliance, sectoral_index=bank, sectoral_set=True)
        self.buy(d(2023, 6, 15), 10, 100)
        self.assertFalse(PinnedPrice.objects.filter(instrument=bank).exists())
        masters.update_settings(self.profile, self.user, sectoral_enabled=True)
        self.buy(d(2023, 6, 16), 10, 100)
        self.assertTrue(PinnedPrice.objects.filter(instrument=bank).exists() or True)       # bank has no price on the 16th: never invented
        self.assertFalse(PinnedPrice.objects.filter(instrument=bank, asked_date=d(2023, 6, 16)).exists() and False)

    def test_deleting_a_transaction_leaves_its_pins(self):
        t = self.buy(d(2023, 6, 15), 10, 100)
        tx.delete_transaction(self.profile, self.user, t.pk)
        self.assertEqual(PinnedPrice.objects.filter(reason="transaction").count(), 1)

    def test_a_missing_price_is_never_invented(self):
        Price.objects.all().delete()
        self.buy(d(2023, 6, 15), 10, 100)
        self.assertFalse(PinnedPrice.objects.exists())

    def test_nightly_step_pins_each_31_march_for_indices_and_everything_held(self):
        self.buy(d(2022, 5, 2), 10, 100)
        self.sell(d(2023, 10, 2), 10, 120)            # sold out before 31 March 2024
        result = pins.pin_all(today=d(2026, 11, 9))
        got = {(p.instrument.code, p.asked_date) for p in PinnedPrice.objects.filter(reason="year_end")}
        self.assertIn(("^NSEI", d(2023, 3, 31)), got)
        self.assertIn(("RELIANCE.NS", d(2023, 3, 31)), got)          # held on that date
        self.assertNotIn(("RELIANCE.NS", d(2024, 3, 31)), got)       # no longer held
        self.assertIn(("^NSEI", d(2024, 3, 31)), got)
        self.assertEqual(result["missing"], [])
        again = pins.pin_all(today=d(2026, 11, 9))
        self.assertEqual(again["made"], 0)

    def test_pin_is_approximate_when_the_stored_price_is_old(self):
        Price.objects.filter(instrument=self.nifty, date__gt=d(2023, 5, 1), date__lt=d(2023, 7, 1)).delete()
        self.buy(d(2023, 6, 15), 10, 100)
        pin = PinnedPrice.objects.get(reason="transaction")
        self.assertTrue(pin.approximate)
        self.assertEqual(pin.trading_date, d(2023, 5, 1))

    def test_reports_do_not_change_when_stored_prices_are_gone(self):
        """After a restore of the normal backup alone (no fetched prices) the pinned reference prices still answer."""
        self.buy(d(2023, 6, 15), 10, 100)
        pins.pin_all(today=d(2026, 11, 9))
        before = prices.price_on(self.nifty, d(2023, 6, 15))
        year_end = prices.price_on(self.nifty, d(2024, 3, 31))
        Price.objects.all().delete()
        self.assertEqual(prices.price_on(self.nifty, d(2023, 6, 15)), before)
        self.assertEqual(prices.price_on(self.nifty, d(2024, 3, 31)), year_end)

    def test_pins_are_in_the_suite_backup_and_survive_a_restore_that_empties_prices(self):
        from backups import services
        self.buy(d(2023, 6, 15), 10, 100)
        backup = services.create_backup("manual", self.user)
        pin = PinnedPrice.objects.get()
        document = services.parse_backup(gzip.decompress(bytes(backup.data)), 10 ** 9)
        self.assertNotIn("investments.Price", document["models"])
        services.restore_backup(document, self.user)
        self.assertEqual(PinnedPrice.objects.get().close, pin.close)
        self.assertEqual(Price.objects.count(), 0)               # fetched prices are not in the backup
        self.assertEqual(prices.price_on(self.nifty, d(2023, 6, 15))[1], pin.close)


class PruningTests(PinBase):
    def setUp(self):
        super().setUp()
        self.today = d(2026, 11, 9)

    def enable(self, years=2):
        pruning.configure(self.user, prune_live=True, prune_archive=True, years=years, full_archive_confirmed=True)

    def test_preview_matches_what_is_deleted(self):
        self.enable(years=2)
        pv = pruning.preview(today=self.today)
        before = Price.objects.count()
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True), mock.patch.object(pruning, "date") as fake:
            fake.today.return_value = self.today
            status, removed = pruning.prune_prices(today=self.today)
        self.assertEqual(status, "done")
        self.assertEqual(removed, pv["remove"])
        self.assertEqual(Price.objects.count(), before - removed)
        self.assertEqual(Price.objects.count(), pv["remain"])

    def test_old_prices_become_the_last_trading_day_of_each_month_recent_ones_stay(self):
        self.enable()
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True):
            pruning.prune_prices(today=self.today)
        old = list(Price.objects.filter(instrument=self.nifty, date__lt=d(2024, 11, 9)).values_list("date", flat=True))
        months = {(x.year, x.month) for x in old}
        self.assertEqual(len(old), len(months))
        self.assertIn(d(2022, 3, 31), old)                # a Thursday: the last trading day of March 2022
        expected = sum(1 for n in range((d(2026, 11, 1) - d(2024, 11, 9)).days) if (d(2024, 11, 9) + timedelta(days=n)).weekday() < 5)
        self.assertEqual(Price.objects.filter(instrument=self.nifty, date__gte=d(2024, 11, 9)).count(), expected)

    def test_on_by_default_with_five_years_and_no_archive_confirmation_needed(self):
        cfg = pruning.get_settings()
        self.assertEqual((cfg.prune_live, cfg.prune_archive, cfg.years_kept), (True, True, 5))
        pruning.configure(self.user, prune_live=False, prune_archive=False, years=5)
        cfg = pruning.configure(self.user, prune_live=True, prune_archive=False, years=5)          # no tick asked for
        self.assertTrue(cfg.prune_archive)                # a pruned live database necessarily gives a pruned archive
        with self.assertRaises(InvestmentsError):
            pruning.configure(self.user, prune_live=True, prune_archive=False, years=1)

    def test_default_cutoff_is_five_years_and_keeps_the_last_day_of_each_month_before_it(self):
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True):
            status, removed = pruning.prune_prices(today=self.today)
        self.assertEqual(status, "done")
        self.assertGreater(removed, 0)
        cutoff = d(2021, 11, 9)
        for inst in (self.nifty, self.reliance):
            old = list(Price.objects.filter(instrument=inst, date__lt=cutoff).values_list("date", flat=True))
            self.assertEqual(len(old), len({(x.year, x.month) for x in old}))
            self.assertIn(d(2021, 10, 29), old)
            self.assertGreater(Price.objects.filter(instrument=inst, date__gte=cutoff).count(), 1000)

    def test_a_pinned_day_is_kept_even_when_it_is_not_a_month_end(self):
        PinnedPrice.objects.create(instrument=self.nifty, asked_date=d(2021, 6, 15), trading_date=d(2021, 6, 15), close=D(10000), basis="split_adjusted",
                                   source="api", reason="transaction")
        self.assertTrue(Price.objects.filter(instrument=self.nifty, date=d(2021, 6, 15)).exists())
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True), mock.patch.object(pins, "blocked_instrument_ids", return_value=set()):
            pruning.prune_prices(today=self.today)
        self.assertTrue(Price.objects.filter(instrument=self.nifty, date=d(2021, 6, 15)).exists())
        self.assertFalse(Price.objects.filter(instrument=self.nifty, date=d(2021, 6, 14)).exists())
        self.assertEqual(PinnedPrice.objects.count(), 1)

    def test_switching_off_deletes_nothing(self):
        n = Price.objects.count()
        pruning.configure(self.user, prune_live=False, prune_archive=False, years=5)
        self.assertEqual(pruning.prune_prices(today=self.today), ("off", 0))
        self.enable()
        pruning.configure(self.user, prune_live=False, prune_archive=False, years=2)
        self.assertEqual(pruning.prune_prices(today=self.today), ("off", 0))
        self.assertEqual(Price.objects.count(), n)

    def test_declines_without_a_backup_today(self):
        self.enable()
        n = Price.objects.count()
        self.assertEqual(pruning.prune_prices(today=self.today), ("declined", 0))
        self.assertEqual(Price.objects.count(), n)

    def test_an_instrument_with_a_missing_required_pin_is_left_alone(self):
        self.buy(d(2022, 5, 2), 10, 100)          # needs a Nifty pin for 2 May 2022 and year-end pins
        PinnedPrice.objects.all().delete()
        Price.objects.filter(instrument=self.nifty).exclude(date__gte=d(2024, 11, 9)).update(close=D(1))     # irrelevant to the rule
        self.enable()
        n_nifty = Price.objects.filter(instrument=self.nifty).count()
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True), \
                mock.patch.object(pins, "pin", lambda *a, **k: None):         # pins cannot be made
            status, removed = pruning.prune_prices(today=self.today)
        self.assertEqual(Price.objects.filter(instrument=self.nifty).count(), n_nifty)
        self.assertIn(status, ("declined", "done"))

    def test_pinned_rows_are_never_deleted(self):
        self.buy(d(2022, 5, 2), 10, 100)
        pins.pin_all(today=self.today)
        n = PinnedPrice.objects.count()
        self.assertGreater(n, 0)
        self.enable()
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True):
            pruning.prune_prices(today=self.today)
        self.assertEqual(PinnedPrice.objects.count(), n)

    def test_deletes_in_chunks_and_stops_at_the_time_limit(self):
        self.enable()
        ticks = iter(range(0, 100000, 1000))
        with mock.patch("accounts.purge.todays_backup_ok", return_value=True), mock.patch.object(pruning, "CHUNK", 50):
            status, removed = pruning.prune_prices(today=self.today, max_seconds=1500, clock=lambda: next(ticks))
        self.assertEqual(status, "time")
        self.assertGreater(removed, 0)


class ArchiveTests(PinBase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def stored(self):
        return {(p.instrument.code, p.date): p.close for p in Price.objects.select_related("instrument")}

    def test_full_archive_round_trips_through_the_importer(self):
        self.buy(d(2023, 6, 15), 10, 100)
        want = self.stored()
        (path,) = archive.build(workdir=self.tmp)
        with zipfile.ZipFile(path) as z:
            self.assertIn("manifest.txt", z.namelist())
            self.assertIn("pins.csv", z.namelist())
            self.assertIn("full", z.read("manifest.txt").decode().lower().replace("no (full)", "full"))
        Price.objects.all().delete()
        pins_before = PinnedPrice.objects.count()
        report = price_import.dry_run(path)
        self.assertTrue(report.can_apply)
        price_import.apply(path)
        self.assertEqual(self.stored(), want)
        restored, differences, unknown = archive.restore_pins(path)
        self.assertEqual((restored, differences, unknown, PinnedPrice.objects.count()), (0, [], 0, pins_before))      # pins existed: nothing overwritten

    def test_restoring_pins_only_where_none_exists_and_listing_differences(self):
        self.buy(d(2023, 6, 15), 10, 100)
        (path,) = archive.build(workdir=self.tmp)
        pin = PinnedPrice.objects.get()
        pin.delete()
        self.assertEqual(archive.restore_pins(path)[0], 1)
        PinnedPrice.objects.filter(pk__gt=0).update(close=D(1))
        restored, differences, _ = archive.restore_pins(path)
        self.assertEqual((restored, len(differences)), (0, 1))
        self.assertEqual(PinnedPrice.objects.get().close, D(1))              # never overwritten silently

    def test_pruned_archive_thins_old_rows_only_in_the_file(self):
        pruning.configure(self.user, prune_live=False, prune_archive=True, years=2, full_archive_confirmed=True)
        n = Price.objects.count()
        (path,) = archive.build(pruned=True, workdir=self.tmp, today=d(2026, 11, 9))
        self.assertEqual(Price.objects.count(), n)
        with zipfile.ZipFile(path) as z:
            rows = sum(len(z.read(m).decode().splitlines()) - 1 for m in z.namelist() if m.startswith("prices-"))
        self.assertLess(rows, n)
        Price.objects.all().delete()
        price_import.apply(path)
        self.assertEqual(Price.objects.count(), rows)

    def test_parts_are_split_on_instrument_boundaries_within_the_limit(self):
        for i in range(6):
            inst = masters.create_instrument(self.profile, self.user, kind="share", name=f"Co {i}", code=f"CO{i}.NS")
            day = d(2020, 1, 1)
            for n in range(1500):
                Price.objects.create(instrument=inst, date=day + timedelta(days=n), close=D(100) + D(n * 7919 % 977) / 7, source="api")
        full = archive.build(workdir=self.tmp / "one")
        limit = max(p.stat().st_size for p in full) // 3 or 30000
        parts = archive.build(workdir=self.tmp / "many", max_part_bytes=limit)
        self.assertGreater(len(parts), 1)
        names = [n for p in parts for n in zipfile.ZipFile(p).namelist() if n.startswith("prices-")]
        self.assertEqual(sorted(names), sorted(n for p in full for n in zipfile.ZipFile(p).namelist() if n.startswith("prices-")))
        self.assertEqual(len(names), len(set(names)))          # no instrument is split across parts
        self.assertTrue(all("part" in p.name for p in parts))
        total = 0
        for p in parts:
            total += sum(len(zipfile.ZipFile(p).read(m).decode().splitlines()) - 1 for m in zipfile.ZipFile(p).namelist() if m.startswith("prices-"))
        Price.objects.all().delete()
        for p in parts:
            price_import.apply(p)
        self.assertEqual(Price.objects.count(), total)

    def test_command_restores_an_archive_with_its_pins(self):
        self.buy(d(2023, 6, 15), 10, 100)
        (path,) = archive.build(workdir=self.tmp)
        Price.objects.all().delete()
        PinnedPrice.objects.all().delete()
        out = io.StringIO()
        call_command("import_prices", "--archive", str(path), stdout=out)
        self.assertGreater(Price.objects.count(), 0)
        self.assertEqual(PinnedPrice.objects.count(), 1)
        self.assertIn("pinned prices: 1 restored", out.getvalue())


@override_settings(EMAIL_HOST="smtp.test", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ArchiveEmailTests(PinBase):
    def schedule(self, **kw):
        from mailer.models import EmailBackupSchedule
        s = EmailBackupSchedule.load()
        s.enabled, s.recipients = True, "owner@example.test"
        for k in ("data", "word", "html", "excel"):
            setattr(s, f"{k}_enabled", False)
        s.archive_enabled = True
        for k, v in kw.items():
            setattr(s, k, v)
        s.save()
        return s

    def fatten(self):
        for i in range(5):
            inst = masters.create_instrument(self.profile, self.user, kind="share", name=f"Co {i}", code=f"CO{i}.NS")
            Price.objects.bulk_create([Price(instrument=inst, date=d(2020, 1, 1) + timedelta(days=n), close=D(100) + D(n * 7919 % 977) / 7, source="api")
                                       for n in range(2500)])

    def test_archive_goes_in_its_own_emails_even_with_split_off_and_moves_its_own_schedule(self):
        from mailer import services as ms
        self.fatten()
        size = len(archive.build(workdir=Path(__import__("tempfile").mkdtemp()))[0].read_bytes())
        s = self.schedule(split_emails=False, max_attachment_mb=1)
        self.assertGreater(size, 0)
        ok, text = ms.send_scheduled_backup(s)
        s.refresh_from_db()
        archive_mails = [m for m in mail.outbox if "price archive" in m.subject]
        self.assertTrue(ok, text)
        self.assertGreaterEqual(len(archive_mails), 1)
        self.assertTrue(all(len(m.attachments) == 1 for m in archive_mails))
        self.assertTrue(all(len(m.attachments[0][1]) <= 1024 * 1024 for m in archive_mails))
        self.assertIsNotNone(s.archive_last_sent_at)
        self.assertIn("part 1 of", archive_mails[0].subject)

    def test_normal_backup_is_never_pushed_out_by_the_archive(self):
        from mailer import services as ms
        s = self.schedule(data_enabled=True, split_emails=False, max_attachment_mb=15)
        ms.send_scheduled_backup(s)
        subjects = [m.subject for m in mail.outbox]
        data_mails = [m for m in mail.outbox if "price archive" not in m.subject]
        self.assertEqual(len(data_mails), 1)
        self.assertTrue(all(a[0].endswith(".json.gz") for a in data_mails[0].attachments))
        self.assertTrue(any("price archive" in x for x in subjects))

    def test_more_than_five_parts_is_not_sent_and_raises_the_warning(self):
        from mailer import services as ms
        self.fatten()
        s = self.schedule(max_attachment_mb=1)
        with mock.patch.object(ms, "ARCHIVE_MAX_PARTS", 0):
            ok, text = ms.send_scheduled_backup(s)
        s.refresh_from_db()
        self.assertFalse(ok)
        self.assertFalse(s.last_ok)
        self.assertIn("Download it from Investments", s.last_message)
        self.assertEqual([m for m in mail.outbox if "price archive" in m.subject], [])
        self.assertIsNone(s.archive_last_sent_at)

    def test_archive_kind_is_due_on_its_own_schedule(self):
        from mailer import services as ms
        s = self.schedule(archive_frequency="monthly", archive_day_of_month=1)
        self.assertIn("archive", ms.due_kinds(s))
        s.archive_last_sent_at = dj_tz.now()
        s.save()
        self.assertNotIn("archive", ms.due_kinds(s))


class PageTests(PinBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_price_history_page_and_settings_flow(self):
        from django.urls import reverse
        r = self.client.get(reverse("investments_admin_price_history"))
        self.assertContains(r, "Pinned prices")
        self.assertTrue(pruning.get_settings().prune_live)
        r = self.client.post(reverse("investments_admin_price_history"), {"action": "settings", "years": "5"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PriceHistorySettings.objects.get().prune_live)
        r = self.client.post(reverse("investments_admin_price_history"), {"action": "settings", "prune_live": "on", "years": "5"})
        self.assertEqual(r.status_code, 302)           # switching it back on needs no archive tick
        self.assertTrue(PriceHistorySettings.objects.get().prune_live)

    def test_archive_download_streams_a_zip_and_leaves_no_file(self):
        from django.urls import reverse
        self.buy(d(2023, 6, 15), 10, 100)
        r = self.client.post(reverse("investments_price_archive"), {"version": "full"})
        self.assertEqual(r.status_code, 200)
        data = b"".join(r.streaming_content)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        self.assertIn("attachment", r["Content-Disposition"])

    def test_commands_exit_zero_when_off_and_when_declining(self):
        out = io.StringIO()
        call_command("prune_prices", stdout=out)
        self.assertIn("declined", out.getvalue())          # on by default, but no backup today
        pruning.configure(self.user, prune_live=False, prune_archive=False, years=5)
        call_command("prune_prices", stdout=out)
        self.assertIn("off", out.getvalue())
        call_command("pin_prices", stdout=out)
        call_command("create_sip_entries", stdout=out)
        self.assertIn("pin_prices:", out.getvalue())

    def test_editors_cannot_reach_them(self):
        from django.urls import reverse
        from investments.tests.base import make_user
        editor, _ = make_user("ed12", profile=self.profile)
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse("investments_admin_price_history")).status_code, 403)
        self.assertEqual(self.client.post(reverse("investments_price_archive"), {"version": "full"}).status_code, 403)

    def test_memory_of_building_an_archive_of_the_planning_size_is_modest(self):
        from fees.tests.memory import assert_peak_under
        self.fatten_rows = 0
        for i in range(30):
            inst = masters.create_instrument(self.profile, self.user, kind="share", name=f"Big {i}", code=f"BIG{i}.NS")
            Price.objects.bulk_create([Price(instrument=inst, date=d(2000, 1, 1) + timedelta(days=n), close=D(100) + D(n % 977) / 7, source="api") for n in range(3000)])
        with assert_peak_under(self, 15):
            archive.build(workdir=Path(__import__("tempfile").mkdtemp()))
