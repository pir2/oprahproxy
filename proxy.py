#!/usr/bin/env python3
import asyncio
import logging
import random
import os.path
import base64
import csv
import oprahproxy
#from vpn import get_proxy


log = logging.getLogger(__name__)

mycountries = ['CA','US']

auth = proxies = proxy = port = country = None

pool = asyncio.Queue()
psize = 0

logging.basicConfig(format='%(asctime)s %(message)s')
log = logging.getLogger()

async def process_client(client_reader, client_writer, *, CHUNK=4096):
    global psize
    client_name = client_writer.get_extra_info('peername')
    print('Client connected:', client_name)
    log.info('Client connected: %s', client_name)

    try:
        remote_reader, remote_writer = pool.get_nowait()
    except asyncio.QueueEmpty:
        if True: #psize < pool.maxsize:
            psize += 1
            print('new remote connection:', psize)
            log.info('new remote connection: %s', psize)
            random_int = random.randint(1,len(proxies))-1
            country, proxy, port = proxies[random_int]
            print('COUNTRY %s IP %s PORT %s' % (country, proxy, port))
            log.info('COUNTRY %s IP %s PORT %s' % (country, proxy, port))
            remote_reader, remote_writer = await asyncio.open_connection(
                host=proxy, port=port, ssl=True, server_hostname=country+'.opera-proxy.net')
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
   #print(headers)
    remote_writer.write(headers)

    # HTTPS tunnel
    if headers.startswith(b'CONNECT'):
        async def forward():
            while True:
                req = await client_reader.read(CHUNK)
                #print('> ', req)
                if not req:
                    break
                remote_writer.write(req)
        async def backward():
            while True:
                res = await remote_reader.read(CHUNK)
                #print('< ', res)
                if not res:
                    break
                client_writer.write(res)
        await asyncio.wait([asyncio.ensure_future(forward()),
                            asyncio.ensure_future(backward())],timeout=30)
        print('tunnel done:', client_name)

    else:  # plain HTTP data

        sent = 0
        while sent < content_length:
            req = await client_reader.read(CHUNK)
            sent += len(req)
            #print('> ', req)
            remote_writer.write(req)
        await remote_writer.drain()

        while True:
            res = await remote_reader.read(CHUNK)
            #print('< ', res)
            client_writer.write(res)
            if len(res) < CHUNK:
                break

    await client_writer.drain()
    client_writer.close()
    pool.put((remote_reader, remote_writer))
    print('Client finished:', client_name)
    log.info('Client finished: %s', client_name)


def client_handler(client_reader, client_writer):
    asyncio.ensure_future(process_client(client_reader, client_writer))


def check_proxy():
    global proxies auth
    if os.path.isfile('proxylist.csv'):
        with open('proxylist.csv', newline='') as csvfile:
            i = csv.reader(csvfile, delimiter=',')
            proxylist = [proxylist for proxylist in i] 
        proxies = [p for p in proxylist if p[0] in mycountries]
    else:
        proxies = [['68.71.61.22','443'],['162.253.131.60','80']]

    if os.path.exists('secret') and os.path.exists('creds'):
        print('secret exists')
        device_id, device_password = open('secret').read().split()
        email, password = open('creds').read().split()
        didp = device_id + ":" + device_password
        auth = base64.b64encode(didp.encode('ascii')).decode('ascii')
    else:
        auth = None
    
    return auth


def get_proxy():
    print('Attempting to get proxies.')
    you_get_a_proxy = oprahproxy.OprahProxy('se0306',
          '7502E43F3381C82E571733A350099BB5D449DD48311839C099ADC4631BA0CC04')
    you_get_a_proxy.everybody_gets_a_proxy()
    

if __name__ == '__main__':
    while not check_proxy():
        print('No proxy information found.')
        get_proxy()
    auth = 'Proxy-Authorization: BASIC {}\r\n'.format(auth).encode('ascii')
    loop = asyncio.get_event_loop()
    server = loop.run_until_complete(asyncio.start_server(client_handler, port=8888))
    print('Started HTTP proxy at', server.sockets[0].getsockname())
    log.info('Started HTTP proxy at %s', server.sockets[0].getsockname())
    loop.run_forever()
