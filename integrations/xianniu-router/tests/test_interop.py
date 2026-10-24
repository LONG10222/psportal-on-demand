import asyncio
import base64
import socket
import struct
import unittest

from xianniu_router.protocol import rc4, encode_api, decode_api, read_frame, frame, MAX_FRAME
from xianniu_router.dns import addresses, name_at, AddressBook
from xianniu_router.runtime import Service, NativeUDP


class Codecs(unittest.TestCase):
    def test_rc4_published_vector(self):
        self.assertEqual(rc4(b'Plaintext', b'Key').hex(), 'bbf316e8d940af0ad3')

    def test_shipped_api_synthetic_vector(self):
        self.assertEqual(encode_api({}), b'XCb/nwyDsapjsA==')
        self.assertEqual(decode_api(b'XCb/nwyDsapjsA=='), {})

    def test_api_rejects_decompression_bomb(self):
        with self.assertRaises(ValueError):
            decode_api(encode_api({'oversized': 'a' * (MAX_FRAME + 1)}))

    def test_dns_compressed_answer_and_client_isolation(self):
        question = b'\x03www\x07example\x03com\0\0\1\0\1'
        response = struct.pack('!6H', 1, 0x8180, 1, 1, 0, 0) + question
        response += b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 30, 4) + socket.inet_aton('93.184.216.34')
        self.assertEqual(addresses(response), ('www.example.com', [('93.184.216.34', 30)]))
        book = AddressBook()
        book.learn(response, '192.168.31.112')
        self.assertEqual(book.lookup('192.168.31.112', '93.184.216.34'), 'www.example.com')
        self.assertEqual(book.lookup('192.168.31.10', '93.184.216.34'), '93.184.216.34')

    def test_dns_pointer_loop_and_truncation(self):
        for data in (b'\xc0\0', b'\xc0', b'\x05abc'):
            with self.assertRaises(ValueError):
                name_at(data, 0)


class Streams(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_frame_is_reassembled(self):
        reader = asyncio.StreamReader()
        task = asyncio.create_task(read_frame(reader))
        for value in frame(b'hello'):
            reader.feed_data(bytes([value]))
            await asyncio.sleep(0)
        self.assertEqual(await task, b'hello')

    async def test_invalid_frame_length_is_rejected_before_allocation(self):
        for size in (0, MAX_FRAME + 1):
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack('<I', size))
            with self.assertRaises(ValueError):
                await read_frame(reader)

    async def test_udp_lease_survives_control_tcp_eof(self):
        """The real node closes command-4 TCP immediately; UDP must survive."""
        loop = asyncio.get_running_loop()
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(('127.0.0.1', 0))
        udp.setblocking(False)
        async def server(reader, writer):
            await reader.readexactly(8)
            for _ in range(4):
                size = struct.unpack('<I', await reader.readexactly(4))[0]
                await reader.readexactly(size)
            writer.write(b'\x02\x5a' + struct.pack('<H', udp.getsockname()[1]) + b'\0' * 4)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        tcp = await asyncio.start_server(server, '127.0.0.1', 0)
        config = {'node': {'host': '127.0.0.1', 'port': tcp.sockets[0].getsockname()[1]},
                  'auth': {'u': base64.b64encode(b'test').decode(), 'key': base64.b64encode(b'fake-key').decode(), 'plain_second': True}}
        service = Service(config)
        response = loop.create_future()
        async def delivered(host, port, body):
            if not response.done():response.set_result((host, port, body))
        relay = NativeUDP(service, delivered)
        try:
            await relay.open()
            await asyncio.sleep(.05)
            self.assertFalse(relay.closed)
            await relay.send('8.8.8.8', 53, b'probe')
            packet, peer = await asyncio.wait_for(loop.sock_recvfrom(udp, 4096), 1)
            await loop.sock_sendto(udp, packet, peer)
            self.assertEqual(await asyncio.wait_for(response, 1), ('8.8.8.8', 53, b'probe'))
        finally:
            await relay.close()
            tcp.close()
            await tcp.wait_closed()
            udp.close()


if __name__ == '__main__':
    unittest.main()
