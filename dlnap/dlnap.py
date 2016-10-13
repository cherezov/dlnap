#!/usr/bin/python

# @file dlnap.py
# @author cherezov.pavel@gmail.com

# Change log:
#   0.1 Initial version

__version__ = "0.1"

import re
import sys
import time
import socket
import select
from contextlib import contextmanager

py3 = sys.version_info[0] == 3
if py3:
   from urllib.request import urlopen
else:
   from urllib2 import urlopen

SSDP_GROUP = ("239.255.255.250", 1900)
URN_AVTransport = "urn:schemas-upnp-org:service:AVTransport:1"

def get_port(location):
   port = re.findall('http://.*:(\d+).*', location)[0]
   return int(port)

def get_control_url(raw):
   url = re.findall('\<serviceType\>{}\</serviceType\>.*\<controlURL\>(.*)\</controlURL\>'.format(re.escape(URN_AVTransport)), raw.replace('\n', ''))
   return url[0] if url else ''

class Device:
   def __init__(self, raw, ip):
      self.__raw = raw.decode()
      self.ip = ip
      self.port = None
      self.control_url = None
      self.name = None
      self.has_av_transport = False

      try:
         for d in self.__raw.split('\r\n'):
            if d.startswith('LOCATION:'):
               self.location = d.replace('LOCATION: ', '')
               break

         self.port = get_port(self.location)

         self.__desc_xml = urlopen(self.location).read().decode()
         self.name = re.findall('\<friendlyName\>(.*)\</friendlyName\>', self.__desc_xml)[0]

         self.has_av_transport = '<serviceType>{}</serviceType>'.format(URN_AVTransport) in self.__desc_xml
         self.control_url = get_control_url(self.__desc_xml)
      except Exception as e:
         print(e)
         print(self.ip)
         print(self.location)

   @contextmanager
   def __send_tcp(self, to, payload):
      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      sock.connect(to)
      sock.sendall(payload.encode())
      yield sock
      sock.close()

   def __repr__(self):
      return '{} @ {}'.format(self.name, self.ip)

   def __eq__(self, d):
      return self.name == d.name and self.ip == d.ip

   def _set_av(self, url, instance_id = 0):
      payload = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
   <s:Body>
      <u:SetAVTransportURI xmlns:u="{}">
         <InstanceID>{}</InstanceID>
         <CurrentURI>{}</CurrentURI>
         <CurrentURIMetaData />
      </u:SetAVTransportURI>
   </s:Body>
</s:Envelope>""".format(URN_AVTransport, instance_id, url)
 
      header = "\r\n".join([
           'POST {} HTTP/1.1'.format(self.control_url),
           'User-Agent: dlnap/0.1',
           'Accept: */*',
           'Content-Type: text/xml; charset="utf-8"',
           'HOST: {}:{}'.format(self.ip, self.port),
           'Content-Length: {}'.format(len(payload)),
           'SOAPACTION: "{}#SetAVTransportURI"'.format(URN_AVTransport),
           'Connection: close',
           '',
           payload,
           ])

      with self.__send_tcp((self.ip, self.port), header):
         pass

   def _play(self, instance_id=0):
      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:Play xmlns:u="{}">
                  <InstanceID>{}</InstanceID>
                  <Speed>1</Speed>
               </u:Play>
            </s:Body>
         </s:Envelope>""".format(URN_AVTransport, instance_id)

      header = "\r\n".join([
           'POST {} HTTP/1.1'.format(self.control_url),
           'User-Agent: dlnap/0.1',
           'Accept: */*',
           'Content-Type: text/xml; charset="utf-8"',
           'HOST: {}:{}'.format(self.ip, self.port),
           'Content-Length: {}'.format(len(payload)),
           'SOAPACTION: "{}#Play"'.format(URN_AVTransport),
           'Connection: close',
           '',
           payload
           ])
      with self.__send_tcp((self.ip, self.port), header):
         pass

   def play(self, url):
      self._set_av(url)
      self._play()

class DLNAPlayer:
   def __init__(self):
      self.name = 'dlnap'

   @contextmanager
   def __send_udp(self, to, payload):
      sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
      sock.sendto(payload.encode(), to)
      yield sock
      sock.close()

   def discover(self, name = '', timeout = 5, st = "ssdp:all", mx = 3):
      payload = "\r\n".join([
                 'M-SEARCH * HTTP/1.1',
                 'HOST: {}:{}'.format(*SSDP_GROUP),
                 'Accept: */*',
                 'MAN: "ssdp:discover"',
                 'ST: {}'.format(st),
                 'MX: {}'.format(mx),
                 '',
                 ''])
      devices = []
      with self.__send_udp(SSDP_GROUP, payload) as sock:
         start = time.time()
         while True:
            if time.time() - start > timeout:
               break
            r, w, x = select.select([sock], [], [sock], 1)
            if sock in r:
                data, addr = sock.recvfrom(1024)
                d = Device(data, addr[0])
                if d not in devices:
                   if not name or name in d.name:
                      devices.append(d)
            elif sock in x:
                raise Exception('Getting response failed')
            else:
                # Nothing to read
                pass
      return devices

if __name__ == '__main__':
   import getopt

   try:
      opts, args = getopt.getopt(sys.argv[1:], "hld:u:t:", ['help', 'list=', 'device=', 'url=', 'timeout='])
   except getopt.GetoptError:
      sys.exit(1)

   name = ''
   url = ''
   timeout = 0.5
   for opt, arg in opts:
      if opt in ('-h', '--help'):
         print('dlna.py [-d <device name>] [-u <url to play>] [-t <timeout>] [-l]')
         sys.exit(0)
      if opt in ('-l', '--list'):
         pass
      elif opt in ('-d', '--device'):
         name = arg
      elif opt in ('-t', '--timeout'):
         timeout = arg
      elif opt in ('-u', '--url'):
         url = arg

   p = DLNAPlayer()
   if not name:
      print('Discovered devices:')
      dd = p.discover(timeout=timeout)
      for d in dd:
         print(' {} {}'.format('+' if d.has_av_transport else '-', d))
   else:
      d = p.discover(name = name, timeout=timeout)
      if not d:
         print('Device not found.')
         sys.exit(1)
      d = d[0]
      print(d)

      if not url:
         print('Please specify url.')
         sys.exit(1)

      d.play(url=url)
