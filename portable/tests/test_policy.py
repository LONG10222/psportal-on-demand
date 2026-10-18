import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, patch

from portalproxy import policy


class PolicyTests(unittest.TestCase):
    def test_allowed_lan(self):
        for address in ("10.20.0.1", "172.16.0.1", "172.31.255.254", "192.168.50.1", "fc12::1", "fd12::1"):
            with self.subTest(address=address):
                self.assertEqual(policy.destination(address), "local")
                self.assertTrue(policy.local_ip(address))

    def test_denied_special_addresses(self):
        for address in ("0.0.0.0", "0.1.2.3", "127.0.0.1", "127.255.255.255", "169.254.169.254",
                        "100.64.0.1", "100.127.255.254", "192.0.0.9", "192.0.2.1", "192.88.99.1",
                        "198.18.0.1", "198.19.255.255", "198.51.100.1", "203.0.113.1", "224.0.0.1",
                        "239.255.255.255", "240.0.0.1", "255.255.255.255", "::", "::1", "fe80::1",
                        "ff02::1", "fec0::1", "::ffff:192.168.1.1", "::ffff:8.8.8.8", "::8.8.8.8",
                        "64:ff9b::808:808", "2001::1", "2001:1ff::1", "2001:db8::1", "2002:808:808::1",
                        "3fff:fff::1", "4000::1", "ffff::1"):
            with self.subTest(address=address):
                self.assertEqual(policy.destination(address), "deny")
                self.assertFalse(policy.local_ip(address))

    def test_external_boundaries(self):
        for address in ("8.8.8.8", "1.1.1.1", "172.15.0.1", "172.32.0.1", "100.63.255.255",
                        "100.128.0.1", "2001:200::1", "2001:4860:4860::8888", "2606:4700:4700::1111",
                        "3fff:1000::1"):
            with self.subTest(address=address):
                self.assertEqual(policy.destination(address), "external")

    def test_names_and_ambiguous_numeric_hosts(self):
        for name in ("example.com", "printer.lan", "fc-example.com", "a", "EXAMPLE.COM.", "123.example"):
            self.assertEqual(policy.destination(name), "name", name)
        for name in ("", "localhost", "a.localhost", "LOCALHOST.", "127.1", "2130706433", "0177.0.0.1",
                     "0x7f000001", "0x7f.1", "1.2.3.4.5", "01.2.3.4", "999.1.2.3", "1..2",
                     ".example.com", "example..com", "foo-", "-foo", "foo_bar", "eä.com", "1.2.3.-1",
                     "fe80::1%eth0", "[::1]", "1:2:3", "::ffff:01.2.3.4", "a" * 64 + ".com"):
            self.assertEqual(policy.destination(name), "deny", name)

    def test_backend_cannot_direct_or_bypass_resolution(self):
        rules = policy.backend_reject_rules()
        self.assertEqual(rules[0], "DOMAIN-SUFFIX,localhost,REJECT")
        for rule in rules:
            self.assertNotIn("DIRECT", rule)
            self.assertNotIn("no-resolve", rule)
        self.assertIn("IP-CIDR,192.168.0.0/16,REJECT", rules)
        self.assertIn("IP-CIDR6,8000::/1,REJECT", rules)


class ResolveTests(unittest.IsolatedAsyncioTestCase):
    def answer(self, address):
        if ":" in address:
            return (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 80, 0, 0))
        return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 80))

    async def resolve(self, *addresses):
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[self.answer(a) for a in addresses])):
            return await policy.resolve_destination("fixture.example", 80)

    async def test_literal_never_resolves(self):
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=AssertionError("DNS called"))):
            self.assertEqual(await policy.resolve_destination("192.168.1.2", 80), policy.Route("local", "192.168.1.2"))
            self.assertEqual(await policy.resolve_destination("8.8.8.8", 443), policy.Route("external"))
            with self.assertRaises(policy.DestinationDenied):
                await policy.resolve_destination("127.0.0.1", 80)

    async def test_all_local_pins_checked_numeric_address(self):
        self.assertEqual(await self.resolve("192.168.1.2", "fd00::1"), policy.Route("local", "192.168.1.2"))

    async def test_public_and_mixed_answers_use_backend(self):
        self.assertEqual(await self.resolve("8.8.8.8"), policy.Route("external"))
        self.assertEqual(await self.resolve("192.168.1.2", "8.8.8.8"), policy.Route("external"))

    async def test_any_denied_answer_fails_closed_regardless_of_order(self):
        for answers in (("8.8.8.8", "127.0.0.1"), ("127.0.0.1", "8.8.8.8"), ("192.168.1.2", "::1"), ("8.8.8.8", "169.254.169.254")):
            with self.subTest(answers=answers):
                with self.assertRaises(policy.DestinationDenied):
                    await self.resolve(*answers)

    async def test_empty_and_failed_resolution_fail_closed(self):
        with self.assertRaises(policy.ResolutionFailed):
            await self.resolve()
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=socket.gaierror("NXDOMAIN"))):
            with self.assertRaises(policy.ResolutionFailed):
                await policy.resolve_destination("fixture.example", 80)

    async def test_malformed_or_scoped_answers_fail_closed(self):
        malformed = [
            (socket.AF_INET,),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 80, 0)),
            (socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 80)),
            (socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("8.8.8.8", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("::1", 80)),
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fd00::1", 80, 0, 4)),
        ]
        for answer in malformed:
            with self.subTest(answer=answer):
                with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[answer])):
                    with self.assertRaises((policy.DestinationDenied, policy.ResolutionFailed)):
                        await policy.resolve_destination("fixture.example", 80)


if __name__ == "__main__":
    unittest.main()
