#!/usr/bin/env python3
"""Read classic Ethernet/Linux-cooked PCAP files and summarize ANS UDP payloads.

Optional --keys is a private JSON list of base64 keys. Only the first 16 decoded
bytes are used, matching the documented agent. Keys and DSNs are never printed.
"""
import argparse
import base64
import ipaddress
import json
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from custom_components.icomm_local.ans import decode_datagram


def packets(path):
    with path.open('rb') as stream:
        header=stream.read(24)
        if len(header)!=24:raise ValueError('Incomplete PCAP header')
        byte_order={b'\xd4\xc3\xb2\xa1':'<',b'\xa1\xb2\xc3\xd4':'>',
                    b'\x4d\x3c\xb2\xa1':'<',b'\xa1\xb2\x3c\x4d':'>'}.get(header[:4])
        if not byte_order:raise ValueError('Expected classic PCAP')
        nano=header[:4] in (b'\x4d\x3c\xb2\xa1',b'\xa1\xb2\x3c\x4d')
        link=struct.unpack(byte_order+'I',header[20:24])[0]
        while raw:=stream.read(16):
            if len(raw)!=16:break
            seconds,fraction,size,_=struct.unpack(byte_order+'IIII',raw)
            if size>16_000_000:raise ValueError('Oversized capture record')
            data=stream.read(size)
            if len(data)!=size:break
            if link==1:
                if len(data)<14:continue
                kind=int.from_bytes(data[12:14],'big');offset=14
                while kind in (0x8100,0x88A8) and len(data)>=offset+4:
                    kind=int.from_bytes(data[offset+2:offset+4],'big');offset+=4
            elif link==113:
                if len(data)<16:continue
                kind=int.from_bytes(data[14:16],'big');offset=16
            elif link==276:
                if len(data)<20:continue
                kind=int.from_bytes(data[:2],'big');offset=20
            else:raise ValueError(f'Unsupported PCAP link type {link}')
            data=data[offset:]
            if kind!=0x800 or len(data)<20 or data[0]>>4!=4 or data[9]!=17:continue
            ip_header=(data[0]&15)*4
            if ip_header<20 or len(data)<ip_header+8 or int.from_bytes(data[6:8],'big')&0x3FFF:continue
            source=str(ipaddress.IPv4Address(data[12:16]));destination=str(ipaddress.IPv4Address(data[16:20]))
            sport,dport,length,_=struct.unpack('>HHHH',data[ip_header:ip_header+8])
            if not any(55055<=port<=55057 for port in (sport,dport)):continue
            if length<8 or len(data)<ip_header+length:continue
            yield {'time':seconds+fraction/(1e9 if nano else 1e6),'source':source,
                   'destination':destination,'source_port':sport,'destination_port':dport},data[ip_header+8:ip_header+length]


def summarize(path,keys=()):
    rows=[]
    for metadata,payload in packets(path):
        decoded=None
        for index,key in enumerate(keys):
            try:decoded=decode_datagram(payload,key)
            except ValueError:continue
            if decoded.get('encrypted') and decoded.get('crc_valid'):
                decoded['key_index']=index
                break
        if decoded is None:
            try:decoded=decode_datagram(payload)
            except ValueError:decoded={'format':payload[0] if payload else None,'length':len(payload),'unrecognized':True}
        rows.append(dict(metadata,**decoded))
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pcap',type=Path);parser.add_argument('--keys',type=Path)
    args=parser.parse_args()
    keys=[base64.b64decode(v,validate=True)[:16] for v in json.loads(args.keys.read_text())] if args.keys else []
    print(json.dumps(summarize(args.pcap,keys),indent=2))
