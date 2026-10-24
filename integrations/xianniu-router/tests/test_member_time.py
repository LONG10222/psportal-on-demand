import unittest
from xianniu_router.member_time import balances,seconds


class DurationCounters(unittest.TestCase):
    def test_seconds_accept_valid_zero_and_numeric_string_without_guessing_units(self):
        for value in (0,3600,'7200',3600.0):self.assertEqual(seconds(value),int(value))
        for value in (True,None,-1,'2030-01-01','3600ms','1.5',float('nan'),float('inf')):
            self.assertIsNone(seconds(value))

    def test_trial_is_separate_and_expiry_is_not_converted_into_balance(self):
        value=balances({'total_datetime':7261,'free_datetime':3600,'expired_datetime':'2030-01-01 00:00:00'})
        self.assertEqual(value['remaining_seconds'],7261)
        self.assertEqual(value['trial_seconds'],3600)
        self.assertEqual(value['time_unit'],'seconds')
        self.assertIsNone(balances({})['remaining_seconds'])
