from django.core.management.base import BaseCommand, CommandError

from fees.exports import pdf_graph


class Command(BaseCommand):
    help = ("Renew the Microsoft 365 sign-in used for memo PDFs and remove Word files older than an hour from its OneDrive app folder "
            "(docs/FEES_PDF_EXPORT.md). Run nightly; does nothing while PDF export is not set up or not connected.")

    def handle(self, *args, **options):
        if not pdf_graph.available():
            self.stdout.write("PDF export is not set up or not connected.")
            return
        try:
            removed = pdf_graph.keep_alive()
        except pdf_graph.PdfError as err:
            pdf_graph._record_error(err.message)
            raise CommandError(f"PDF export sign-in could not be renewed: {err.message}") from None
        self.stdout.write(self.style.SUCCESS(f"PDF export sign-in renewed; {removed} leftover file(s) removed."))
