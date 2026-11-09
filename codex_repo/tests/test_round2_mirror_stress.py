import unittest
from scripts.round2_mirror_stress import mirror_row


class MirrorStressTests(unittest.TestCase):
    def test_involution_and_preserved_execution_fields(self):
        row=dict(Time='1.25',Operation='Insert',OrderId='7',Side='B',Volume='100',Price='10010')
        mirrored=mirror_row(row)
        self.assertEqual(mirrored['Side'],'A')
        self.assertEqual(mirrored['Price'],'9990')
        self.assertEqual(mirrored['Time'],row['Time'])
        self.assertEqual(mirrored['Volume'],row['Volume'])
        self.assertEqual(mirror_row(mirrored),row)

    def test_empty_cancel_fields_stay_empty(self):
        row=dict(Time='1.3',Operation='Cancel',OrderId='7',Side='',Volume='',Price='')
        self.assertEqual(mirror_row(row),row)


if __name__=='__main__':unittest.main()
