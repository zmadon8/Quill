from django.test import SimpleTestCase

from backups import services


class RemovedPriceSourceTests(SimpleTestCase):
    def test_old_twelvedata_instruments_get_the_default_source(self):
        models = {
            "investments.Instrument": [
                {"model": "investments.instrument", "pk": 1, "fields": {"kind": "share", "price_source": "twelvedata", "price_basis": "raw", "fallback_source": ""}},
                {"model": "investments.instrument", "pk": 2, "fields": {"kind": "share", "price_source": "yahoo", "price_basis": "split_adjusted", "fallback_source": "twelvedata"}},
            ],
            "investments.DataSourceFormat": [{"pk": 1, "fields": {"key": "twelvedata"}}, {"pk": 2, "fields": {"key": "yahoo"}}],
        }
        services._drop_removed_price_source(models)
        first, second = (r["fields"] for r in models["investments.Instrument"])
        self.assertEqual((first["price_source"], first["price_basis"]), ("yahoo", "split_adjusted"))
        self.assertEqual((second["price_source"], second["fallback_source"]), ("yahoo", ""))
        self.assertEqual([r["pk"] for r in models["investments.DataSourceFormat"]], [2])
