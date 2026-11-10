# Temporary (UI refresh review): fills a throwaway database with sample data for the screenshot workflow. Run with
#   python manage.py shell < .github/screenshots/seed.py
from datetime import date as d
from decimal import Decimal as D

from django.contrib.auth import get_user_model

from accounts.models import Profile
from accounts.profiles import set_user_profile
from accounts.suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS
from diary.sample_data import load_sample_data
from fees.tests import xlsx_support as xs
from investments.models import Broker, Portfolio, Price
from investments.services import masters, prices, transactions as tx

User = get_user_model()
user = User.objects.create_user("shots", password="shots-pass-123", is_superuser=True)

diary = Profile.objects.get(program=KEY_DIARY, name="Main", deleted_at__isnull=True)
set_user_profile(user, diary, "editor")
load_sample_data(diary)

fees = Profile.objects.create(program=KEY_FEES, name="Madon")
set_user_profile(user, fees, "editor", KEY_FEES)
xs.seed_web_data(fees)
xs.statistics_on(fees)

inv = Profile.objects.create(program=KEY_INVESTMENTS, name="Madon")
set_user_profile(user, inv, "editor", KEY_INVESTMENTS)
masters.ensure_default_portfolio(inv)
masters.ensure_builtin_indices()
portfolio = Portfolio.objects.filter(profile=inv).first() or Portfolio.objects.create(profile=inv, name="Main")
zerodha = Broker.objects.create(profile=inv, name="Zerodha")
rel = masters.create_instrument(inv, user, kind="share", name="Reliance Industries", code="RELIANCE.NS", sector="Energy")
tcs = masters.create_instrument(inv, user, kind="share", name="Tata Consultancy Services", code="TCS.NS", sector="IT")
fund = masters.create_instrument(inv, user, kind="fund", name="Parag Parikh Flexi Cap - Direct Growth", code="122639", asset_class="equity")
masters.create_instrument(inv, user, kind="share", name="Infosys (not bought yet)", code="INFY.NS")
for inst, units, cost in ((rel, 300, 1090), (tcs, 120, 3250), (fund, 4820, 52)):
    tx.add_transaction(inv, user, side="buy", instrument=inst, portfolio=portfolio, broker=zerodha, date=d(2024, 4, 15), units=D(units), price=D(cost))
for inst, close in ((rel, 1320), (tcs, 3480), (fund, 81)):
    for n in range(1, 25):
        Price.objects.update_or_create(instrument=inst, date=d(2026, 10, n), defaults={"close": D(close) * (D(1) + D(n) / D(400)), "source": "api"})
    prices.set_manual_price(inv, user, inst, d(2026, 11, 6), str(close))
import json
from django.urls import reverse

urls = {
    "home": reverse("home"), "diary-subjects": reverse("diary_home"), "my-settings": reverse("my_settings") + "?tab=display",
    "fees-dashboard": reverse("fees_dashboard"), "fees-memos": reverse("fees_memos"), "fees-memo-new": reverse("fees_memo_new"),
    "fees-outstanding": reverse("fees_outstanding"), "inv-overview": reverse("investments_dashboard"),
    "inv-holdings": reverse("investments_holdings") + "?status=all", "inv-investment": reverse("investments_investment", args=[rel.pk]),
    "login": reverse("login"),
}
with open("shot-urls.json", "w") as handle:
    json.dump(urls, handle)
print("seeded", urls)
