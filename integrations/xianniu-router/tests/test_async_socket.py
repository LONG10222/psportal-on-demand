import asyncio
import socket
import unittest
from xianniu_router.async_socket import _recvfrom_compat, _sendto_compat


class Python310Datagrams(unittest.IsolatedAsyncioTestCase):
    async def test_compat_waits_and_relays_real_loopback_datagrams(self):
        loop = asyncio.get_running_loop()
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for sock in (receiver, sender):
            sock.bind(('127.0.0.1', 0))
            sock.setblocking(False)
        try:
            task = asyncio.create_task(_recvfrom_compat(loop, receiver, 4096))
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            count = await _sendto_compat(loop, sender, b'compat-datagram', receiver.getsockname())
            self.assertEqual(count, len(b'compat-datagram'))
            data, peer = await asyncio.wait_for(task, 1)
            self.assertEqual(data, b'compat-datagram')
            self.assertEqual(peer, sender.getsockname())
            self.assertFalse(loop.remove_reader(receiver.fileno()))
        finally:
            receiver.close()
            sender.close()

    async def test_cancelled_receive_removes_readiness_watcher(self):
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        sock.setblocking(False)
        try:
            task = asyncio.create_task(_recvfrom_compat(loop, sock, 4096))
            await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(loop.remove_reader(sock.fileno()))
        finally:
            sock.close()


if __name__ == '__main__':
    unittest.main()
