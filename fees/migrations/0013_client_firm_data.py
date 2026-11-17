from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower


def give_each_client_a_firm(apps, schema_editor):
    """Step 2 of 3. A client reaches a firm through the matters that use it.

    * One firm: the client is set to it.
    * Several firms: the original row stays with the firm that has the most of its matters (a tie goes to the lowest firm id); every
      other firm gets a copy of the client, and that firm's matters are pointed at their copy.
    * No matter at all: nothing refers to the client, and a client with no firm cannot exist, so it is deleted.
    """
    Client = apps.get_model("fees", "Client")
    Matter = apps.get_model("fees", "Matter")
    for client in Client.objects.order_by("pk"):
        counts = list(
            Matter.objects.filter(client_id=client.pk).order_by().values("firm_id").annotate(n=Count("pk")).values_list("firm_id", "n")
        )
        if not counts:
            client.delete()
            continue
        counts.sort(key=lambda row: (-row[1], row[0]))
        keep_firm = counts[0][0]
        client.firm_id = keep_firm
        client.save(update_fields=["firm"])
        for firm_id, _n in counts[1:]:
            copy = Client.objects.create(profile_id=client.profile_id, firm_id=firm_id, name=client.name)
            Matter.objects.filter(client_id=client.pk, firm_id=firm_id).update(client_id=copy.pk)


def merge_copies_back(apps, schema_editor):
    """The reverse: clients of one profile with the same name (any case) become the one with the lowest id, and every matter that had a
    copy is pointed at it. A client deleted by the forward step (no matters) is not brought back."""
    Client = apps.get_model("fees", "Client")
    Matter = apps.get_model("fees", "Matter")
    keepers = {}
    for client in Client.objects.annotate(low=Lower("name")).order_by("pk"):
        key = (client.profile_id, client.low)
        keeper = keepers.get(key)
        if keeper is None:
            keepers[key] = client.pk
            continue
        Matter.objects.filter(client_id=client.pk).update(client_id=keeper)
        client.delete()


class Migration(migrations.Migration):
    """Owner round 2026-12, step 2 of 3: every client gets the firm of its matters (see ``give_each_client_a_firm``)."""

    dependencies = [("fees", "0012_client_firm_add")]

    operations = [migrations.RunPython(give_each_client_a_firm, merge_copies_back)]
