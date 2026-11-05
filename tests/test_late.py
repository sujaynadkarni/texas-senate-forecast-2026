"""Late-count projection: ranked-choice tally and page build (no network)."""
import random, sys, unittest
sys.path.insert(0, "pipeline")
import late_count as L

C = [{"name": "Dem", "party": "D"}, {"name": "Rep", "party": "R"}, {"name": "Rep2", "party": "R"}, {"name": "Ind", "party": "I"}]


class RCV(unittest.TestCase):
    def test_majority_wins_first_round(self):
        w, fin, rounds = L.rcv({"Dem": 60, "Rep": 30, "Rep2": 5, "Ind": 5}, C, random.Random(1))
        self.assertEqual((w, len(rounds)), ("Dem", 1))

    def test_same_party_transfers_can_flip_the_leader(self):
        # Dem leads round one with 40; the two Republicans hold 60 and mostly transfer to each other
        wins = sum(L.rcv({"Dem": 40, "Rep": 35, "Rep2": 25, "Ind": 0}, C, random.Random(i))[0] == "Rep" for i in range(200))
        self.assertGreater(wins, 150)

    def test_votes_never_grow(self):
        w, fin, rounds = L.rcv({"Dem": 45, "Rep": 44, "Rep2": 6, "Ind": 5}, C, random.Random(3))
        self.assertLessEqual(sum(fin.values()), 100 + 1e-9)
        self.assertEqual(len(fin), 2)


if __name__ == "__main__":
    unittest.main()
