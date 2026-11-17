"""In-line citations as tiles on the reading page (owner round 2026-12): the tile each piece gets from its length."""
from django.test import SimpleTestCase

from diary.reading import TEXT_WIDTH, TILES, tile_for


class TileTests(SimpleTestCase):
    def test_smallest_tile_that_holds_it_else_the_whole_row(self):
        self.assertEqual(tile_for(10), "t1")
        self.assertEqual(tile_for(TILES[0][2] + 1), "t2")
        self.assertEqual(tile_for(TILES[-1][2]), "t4")
        self.assertEqual(tile_for(TILES[-1][2] + 1), "t5")

    def test_item_text_counts_wider_than_a_citation(self):
        # A short Item text keeps a tile beside its citations; a long one takes the whole row with the citations below.
        self.assertEqual(tile_for(len("Trust Deed not arbitrable") * TEXT_WIDTH), "t4")
        self.assertEqual(tile_for(len("Serious issue of fraud involving criminal wrongdoing not arbitrable") * TEXT_WIDTH), "t5")
