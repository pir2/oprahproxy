#!/usr/bin/env python3
import asyncio
from vpn import get_proxy

proxy = port = auth = None
pool = asyncio.Queue(5)
psize = 0

async def process_client(client_reader, client_writer, *, CHUNK=4096):
    global psize
    client_name = client_writer.get_extra_info('peername')
    print('Client connected:', client_name)

    try:
        remote_reader, remote_writer = pool.get_nowait()
    except asyncio.QueueEmpty:
        if psize < pool.maxsize:
            psize += 1
            print('new remote connection:', psize)
            remote_reader, remote_writer = await asyncio.open_connection(
                host=proxy, port=port, ssl=True, server_hostname='ca.opera-proxy.net')
        else:
            remote_reader, remote_writer = await pool.get()

    headers = []
    content_length = 0
    while True:
        line = await client_reader.readline()
        if line.startswith(b'Content-Length'):
            content_length = int(line.split(b' ')[1])
        if line == b'\r\n':
            break
        headers.append(line)
    headers = b''.join(headers) + auth + b'\r\n'
    # print(headers)
    remote_writer.write(headers)

    # HTTPS tunnel
    if headers.startswith(b'CONNECT'):
        async def forward():
            while True:
                req = await client_reader.read(CHUNK)
                # print('> ', req)
                if not req:
                    break
                remote_writer.write(req)
        async def backward():
            while True:
                res = await remote_reader.read(CHUNK)
                # print('< ', res)
                if not res:
                    break
                client_writer.write(res)
        await asyncio.wait([asyncio.ensure_future(forward()),
                            asyncio.ensure_future(backward())])
        print('tunnel done:', client_name)

    else:  # plain HTTP data

        sent = 0
        while sent < content_length:
            req = await client_reader.read(CHUNK)
            sent += len(req)
            # print('> ', req)
            remote_writer.write(req)
        await remote_writer.drain()

        while True:
            res = await remote_reader.read(CHUNK)
            # print('< ', res)
            client_writer.write(res)
            if len(res) < CHUNK:
                break

    await client_writer.drain()
    client_writer.close()
    await pool.put((remote_reader, remote_writer))
    print('Client finished:', client_name)


def client_handler(client_reader, client_writer):
    asyncio.ensure_future(process_client(client_reader, client_writer))

if __name__ == '__main__':
    auth, proxy, port = get_proxy()
    auth = 'Proxy-Authorization: BASIC {}\r\n'.format(auth).encode('ascii')
    loop = asyncio.get_event_loop()
    server = loop.run_until_complete(asyncio.start_server(client_handler, port=8888))
    print('Started HTTP proxy at', server.sockets[0].getsockname())
    loop.run_forever()
