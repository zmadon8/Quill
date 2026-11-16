"""A firm with one partner named after it: what ``create_firm`` used to make before a matter could have no partner (owner round
2026-11). Tests about other things use it so their setup is unchanged."""
from fees.services import firms


def firm_with_partner(profile, name):
    firm = firms.create_firm(profile, name)
    firms.add_group(profile, firm.pk, firm.name)
    return firm
