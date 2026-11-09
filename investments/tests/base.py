"""Helpers shared by the Investments tests."""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase, override_settings

from accounts.models import ROLE_EDITOR, Profile, User
from accounts.profiles import set_user_profile
from accounts.suite import KEY_INVESTMENTS
from investments.models import Broker, Portfolio
from investments.services import masters, transactions as tx

PASSWORD = "pw-for-tests-1"


def make_user(name, role=ROLE_EDITOR, admin=False, profile=None):
    user = User.objects.create_user(username=name, password=PASSWORD, is_superuser=admin)
    profile = profile or Profile.objects.create(name=f"{name}-inv", program=KEY_INVESTMENTS)
    set_user_profile(user, profile, role, KEY_INVESTMENTS)
    return user, profile


@override_settings(INVESTMENTS_ENABLED=True, SECURE_SSL_REDIRECT=False)
class InvTestCase(TestCase):
    """A profile with one portfolio, two brokers and a share and a fund."""

    def setUp(self):
        self.user, self.profile = make_user("owner", admin=True)
        self.portfolio = Portfolio.objects.create(profile=self.profile, name="Main")
        self.zerodha = Broker.objects.create(profile=self.profile, name="Zerodha")
        self.groww = Broker.objects.create(profile=self.profile, name="Groww")
        self.reliance = masters.create_instrument(self.profile, self.user, kind="share", name="Reliance Industries", code="RELIANCE.NS")
        self.fund = masters.create_instrument(self.profile, self.user, kind="fund", name="Parag Parikh Flexi Cap - Direct Growth",
                                              code="122639", asset_class="equity")

    def buy(self, day, units, price, instrument=None, broker=None, **kw):
        return tx.add_transaction(self.profile, self.user, side="buy", instrument=instrument or self.reliance, portfolio=self.portfolio,
                                  broker=broker or self.zerodha, date=day, units=D(units), price=D(price), **kw)

    def sell(self, day, units, price, instrument=None, broker=None, **kw):
        return tx.add_transaction(self.profile, self.user, side="sell", instrument=instrument or self.reliance, portfolio=self.portfolio,
                                  broker=broker or self.zerodha, date=day, units=D(units), price=D(price), **kw)


d = date
