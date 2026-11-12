"""Source-restricted authoritative DNS for the heater's replacement cloud hosts.

No recursive resolver or upstream client is implemented. Unknown names return
NXDOMAIN; IPv6 queries return no address. Both UDP and TCP use the same codec.
"""
import asyncio
import ipaddress
import struct


def response(packet, hosts):
    if not 12 <= len(packet) <= 4096:raise ValueError('Invalid DNS size')
    ident,flags,questions,_,_,_=struct.unpack('!6H',packet[:12])
    if flags & 0xf800 or questions != 1:raise ValueError('Unsupported DNS query')
    labels=[];offset=12
    while True:
        if offset>=len(packet):raise ValueError('Truncated name')
        size=packet[offset];offset+=1
        if size==0:break
        if size>63 or offset+size>len(packet):raise ValueError('Invalid label')
        labels.append(packet[offset:offset+size].decode('ascii'));offset+=size
        if offset-12>254:raise ValueError('Name too long')
    if offset+4>len(packet):raise ValueError('Truncated question')
    kind,cls=struct.unpack('!HH',packet[offset:offset+4]);offset+=4
    name='.'.join(labels).lower()
    if cls!=1:raise ValueError('Unsupported DNS class')
    answer=b'';rcode=0
    if name not in hosts:rcode=3
    elif kind==1:
        answer=b'\xc0\x0c'+struct.pack('!HHIH',1,1,300,4)+ipaddress.IPv4Address(hosts[name]).packed
    header=struct.pack('!6H',ident,0x8400|(flags&0x0100)|rcode,1,int(bool(answer)),0,0)
    return header+packet[12:offset]+answer,name,rcode


class LocalDNS(asyncio.DatagramProtocol):
    def __init__(self, hosts, allowed_peers):
        self.hosts={name.rstrip('.').lower():str(ipaddress.IPv4Address(address)) for name,address in hosts.items()}
        self.allowed_peers=set(allowed_peers);self.transport=None;self.server=None;self.writers=set()
        self.queries=0;self.denied=0;self.invalid=0;self.unknown=0

    def connection_made(self, transport):self.transport=transport

    def reply(self, packet, peer):
        if not peer or peer[0] not in self.allowed_peers:self.denied+=1;return None
        try:body,_,rcode=response(packet,self.hosts)
        except (ValueError,UnicodeError,struct.error):self.invalid+=1;return None
        self.queries+=1;self.unknown+=int(rcode==3)
        return body

    def datagram_received(self, packet, peer):
        body=self.reply(packet,peer)
        if body is not None:self.transport.sendto(body,peer)

    async def tcp(self, reader, writer):
        self.writers.add(writer)
        try:
            peer=writer.get_extra_info('peername')
            if not peer or peer[0] not in self.allowed_peers:self.denied+=1;return
            async with asyncio.timeout(5):
                length=struct.unpack('!H',await reader.readexactly(2))[0]
                if not 12<=length<=4096:self.invalid+=1;return
                body=self.reply(await reader.readexactly(length),peer)
                if body is not None:writer.write(struct.pack('!H',len(body))+body);await writer.drain()
        except (TimeoutError,ConnectionError,asyncio.IncompleteReadError):pass
        finally:
            self.writers.discard(writer);writer.close()
            try:await writer.wait_closed()
            except ConnectionError:pass

    async def start(self, host='0.0.0.0', port=5354):
        try:
            await asyncio.get_running_loop().create_datagram_endpoint(lambda:self,local_addr=(host,port))
            self.server=await asyncio.start_server(self.tcp,host,port,limit=4096)
        except BaseException:await self.stop();raise

    async def stop(self):
        if self.transport:self.transport.close();self.transport=None
        if self.server:self.server.close();await self.server.wait_closed();self.server=None
        for writer in list(self.writers):writer.close()

    def status(self):return {'queries':self.queries,'denied':self.denied,'invalid':self.invalid,'unknown':self.unknown}
