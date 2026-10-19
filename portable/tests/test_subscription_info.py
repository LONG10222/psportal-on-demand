import unittest
from portalproxy.subscription_info import from_headers, display, usage_percent


class SubscriptionAccountingTests(unittest.TestCase):
    def test_remaining_and_expiry_are_derived_only_from_real_header_values(self):
        info = from_headers({'subscription-userinfo':'upload=1000000000; download=2000000000; total=10000000000; expire=2000000000'}, 'https://provider.example/private-token')
        self.assertEqual(info['source'], 'provider.example')
        self.assertNotIn('private-token', str(info))
        self.assertIn('6.52 GiB', display(info, 'en'))
        self.assertIn('剩余', display(info, 'zh'))
        self.assertIn('2033-', display(info, 'zh'))
        self.assertEqual(usage_percent(info), 30)

    def test_unknown_fields_are_not_zero_or_unlimited(self):
        info = from_headers({}, 'https://provider.example')
        value = display(info, 'zh')
        self.assertIn('未提供', value)
        self.assertNotIn('0.00', value)
        self.assertNotIn('无限', value)
        self.assertIn('Not provided', display({'upload':1,'total':10}, 'en'))
        self.assertIsNone(usage_percent(info))

    def test_invalid_values_are_ignored_and_overuse_clamps_to_zero(self):
        info = from_headers({'subscription-userinfo':'upload=-1; download=NaN; total=999999999999999999999999; expire=99999999999999'})
        self.assertFalse(any(k in info for k in ('upload','download','total','expire')))
        self.assertIn('Remaining: 0.00 B', display({'upload':20,'download':80,'total':50}, 'en'))
        self.assertIn('Not provided', display({'upload':10**1000,'download':0,'total':10**1000}, 'en'))
        self.assertEqual(usage_percent({'upload':20,'download':80,'total':50}),100)
        self.assertIn('Not provided', display({'expire':253402300799,'updated_at':253402300799}, 'en'))
