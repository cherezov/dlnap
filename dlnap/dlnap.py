#!/usr/bin/python

# @file dlnap.py
# @author cherezov.pavel@gmail.com
# @brief Python over the network media player to playback on DLNA UPnP devices.

# Change log:
#   0.1 initial version.
#   0.2 device renamed to DlnapDevice; DLNAPlayer is disappeared.
#   0.3 debug output is added. Extract location url fixed.
#   0.4 compatible discover mode added.
#   0.5 xml parser introduced for device descriptions
#   0.6 xpath introduced to navigate over xml dictionary
#   0.7 device ip argument introduced
#   0.8 debug output is replaced with standard logging

__version__ = "0.8"

import re
import sys
import time
import socket
import select
import logging
import traceback
from contextlib import contextmanager

import os

py3 = sys.version_info[0] == 3
if py3:
   from urllib.request import urlopen
else:
   from urllib2 import urlopen

SSDP_GROUP = ("239.255.255.250", 1900)
URN_AVTransport = "urn:schemas-upnp-org:service:AVTransport:1"
SSDP_ALL = "ssdp:all"

def _get_port(location):
   """ Extract port number from url.

   location -- string like http://anyurl:port/whatever/path
   return -- port number
   """
   port = re.findall('http://.*?:(\d+).*', location)
   return int(port[0]) if port else 80

def _get_tag_value(x, i = 0):
   """ Get the nearest to 'i' position xml tag name.

   x -- xml string
   i -- position to start searching tag from
   return -- (tag, value) pair.
      e.g
         <d>
            <e>value4</e>
         </d>
      result is ('d', '<e>value4</e>')
   """
   x = x.strip()
   value = ''
   tag = ''

   # skip <? > tag
   if x[i:].startswith('<?'):
      i += 2
      while i < len(x) and x[i] != '<':
         i += 1

   # check for empty tag like '</tag>'
   if x[i:].startswith('</'):
      i += 2
      in_attr = False
      while i < len(x) and x[i] != '>':
         if x[i] == ' ':
            in_attr = True
         if not in_attr:
            tag += x[i]
         i += 1
      return (tag, '', x[i+1:])

   # not an xml, treat like a value
   if not x[i:].startswith('<'):
      return ('', x[i:], '')

   i += 1 # <

   # read first open tag
   in_attr = False
   while i < len(x) and x[i] != '>':
      # get rid of attributes
      if x[i] == ' ':
         in_attr = True
      if not in_attr:
         tag += x[i]
      i += 1

   i += 1 # >

   while i < len(x):
      value += x[i]
      if x[i] == '>' and value.endswith('</' + tag + '>'):
         # Note: will not work with xml like <a> <a></a> </a>
         close_tag_len = len(tag) + 2 # />
         value = value[:-close_tag_len]
         break
      i += 1
   return (tag, value[:-1], x[i+1:])

def _xml2dict(s):
   """ Convert xml to dictionary.

   <?xml version="1.0"?>
   <a any_tag="tag value">
      <b> <bb>value1</bb> </b>
      <b> <bb>value2</bb> </b>
      </c>
      <d>
         <e>value4</e>
      </d>
      <g>value</g>
   </a>

   =>

   { 'a':
     {
         'b': [ {'bb':value1}, {'bb':value2} ],
         'c': [],
         'd':
         {
           'e': [value4]
         },
         'g': [value]
     }
   }
   """
   d = {}
   while s:
      tag, value, s = _get_tag_value(s)
      value = value.strip()
      isXml, dummy, dummy2 = _get_tag_value(value)
      if tag not in d:
         d[tag] = []
      if not isXml:
         if not value:
            continue
         d[tag].append(value.strip())
      else:
         if tag not in d:
            d[tag] = []
         d[tag].append(_xml2dict(value))
   return d

s = """
   <?xml version="1.0"?>
   <a any_tag="tag value">
      <b><bb>value1</bb></b>
      <b><bb>value2</bb> <v>value3</v></b>
      </c>
      <d>
         <e>value4</e>
      </d>
      <g>value</g>
   </a>
"""

def _xpath(d, path):
   """ Return value from xml dictionary at path.

   d -- xml dictionary
   path -- string path like root/device/serviceList/service@serviceType=URN_AVTransport/controlURL
   return -- value at path or None if path not found
   """

   for p in path.split('/'):
      tag_attr = p.split('@')
      tag = tag_attr[0]
      if tag not in d:
         return None

      attr = tag_attr[1] if len(tag_attr) > 1 else ''
      if attr:
         a, aval = attr.split('=')
         for s in d[tag]:
            if s[a] == [aval]:
               d = s
               break
      else:
         d = d[tag][0]
   return d

def _get_control_url(xml):
   """ Extract AVTransport contol url from device description xml

   xml -- device description xml
   return -- control url or empty string if wasn't found
   """
   return _xpath(xml, 'root/device/serviceList/service@serviceType={}/controlURL'.format(URN_AVTransport))

@contextmanager
def _send_udp(to, payload):
   """ Send UDP message to group

   to -- (host, port) group to send to payload to
   payload -- message to send
   """
   sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
   sock.sendto(payload.encode(), to)
   yield sock
   sock.close()

def _send_tcp(to, payload):
   """ Send TCP message to group

   to -- (host, port) group to send to payload to
   payload -- message to send
   """
   try:
      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      sock.connect(to)
      sock.sendall(payload.encode())
   finally:
      sock.close()

def _get_location_url(raw):
   """ Extract device description url from discovery response

   raw -- raw discovery response
   return -- location url string
   """
   for d in raw.split('\r\n'):
      if d.lower().startswith('location:'):
         return re.findall('location:\s*(.*)\s*', d, re.I)[0]
   return ''

def _get_friendly_name(xml):
   """ Extract device name from description xml

   xml -- device description xml
   return -- device name
   """
   return _xpath(xml, 'root/device/friendlyName')

class DlnapDevice:
   """ Represents DLNA/UPnP device.
   """

   def __init__(self, raw, ip):
      self.__logger = logging.getLogger(self.__class__.__name__)
      self.__logger.info('=> New DlnapDevice (ip = {}) initialization..'.format(ip))

      self.__raw = raw.decode()
      self.ip = ip
      self.port = None
      self.control_url = None
      self.name = 'Unknown'
      self.has_av_transport = False

      try:
         self.location = _get_location_url(self.__raw)
         self.__logger.info('location: {}'.format(self.location))

         self.port = _get_port(self.location)
         self.__logger.info('port: {}'.format(self.port))

         raw_desc_xml = urlopen(self.location).read().decode()

         self.__desc_xml = _xml2dict(raw_desc_xml)
         self.__logger.debug('description xml: {}'.format(self.__desc_xml))

         self.name = _get_friendly_name(self.__desc_xml)
         self.__logger.info('friendlyName: {}'.format(self.name))

         self.control_url = _get_control_url(self.__desc_xml)
         self.__logger.info('control_url: {}'.format(self.control_url))

         self.has_av_transport = self.control_url is not None
         self.__logger.info('=> Initialization completed'.format(ip))
      except Exception as e:
         self.__logger.warning('DlnapDevice (ip = {}) init exception:\n{}'.format(ip, traceback.format_exc()))

   def __repr__(self):
      return '{} @ {}'.format(self.name, self.ip)

   def __eq__(self, d):
      return self.name == d.name and self.ip == d.ip

   def _create_packet(self, action, payload):
      """ Create packet to send to device control url.

      action -- control action
      payload -- xml to send to device
      """
      header = "\r\n".join([
         'POST {} HTTP/1.1'.format(self.control_url),
         'User-Agent: {}/{}'.format(__file__, __version__),
         'Accept: */*',
         'Content-Type: text/xml; charset="utf-8"',
         'HOST: {}:{}'.format(self.ip, self.port),
         'Content-Length: {}'.format(len(payload)),
         'SOAPACTION: "{}#{}"'.format(URN_AVTransport, action),
         'Connection: close',
         '',
         payload,
         ])

      return header

   def set_current(self, url, instance_id = 0):
      """ Set media to playback.

      url -- media url
      instance_id -- device instance id
      """
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

      packet = self._create_packet('SetAVTransportURI', payload)
      _send_tcp((self.ip, self.port), packet)

   def play(self, instance_id=0):
      """ Play media that was already set as current.

      instance_id -- device instance id
      """
      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:Play xmlns:u="{}">
                  <InstanceID>{}</InstanceID>
                  <Speed>1</Speed>
               </u:Play>
            </s:Body>
         </s:Envelope>""".format(URN_AVTransport, instance_id)

      packet = self._create_packet('Play', payload)
      _send_tcp((self.ip, self.port), packet)

   def pause(self):
      pass

   def stop(self):
      pass

   def set_next(self, url):
      pass

   def next(self):
      pass

def discover(name = '', ip = '', timeout = 1, st = SSDP_ALL, mx = 3):
   """ Discover UPnP devices in the local network.

   name -- name or part of the name to filter devices
   timeout -- timeout to perform discover
   st -- st field of discovery packet
   mx -- mx field of discovery packet
   return -- list of DlnapDevice
   """
   payload = "\r\n".join([
              'M-SEARCH * HTTP/1.1',
              'User-Agent: {}/{}'.format(__file__, __version__),
              'HOST: {}:{}'.format(*SSDP_GROUP),
              'Accept: */*',
              'MAN: "ssdp:discover"',
              'ST: {}'.format(st),
              'MX: {}'.format(mx),
              '',
              ''])
   devices = []
   with _send_udp(SSDP_GROUP, payload) as sock:
      start = time.time()
      while True:
         if time.time() - start > timeout:
            # timed out
            break
         r, w, x = select.select([sock], [], [sock], 1)
         if sock in r:
             data, addr = sock.recvfrom(1024)
             if ip and addr[0] != ip:
                continue

             d = DlnapDevice(data, addr[0])
             if d not in devices:
                if not name or name.lower() in d.name.lower():
                   devices.append(d)

             if ip:
                # no need in further searching by ip
                break
         elif sock in x:
             raise Exception('Getting response failed')
         else:
             # Nothing to read
             pass
   return devices

if __name__ == '__main__':
   import getopt

   def usage():
      print('{} [--list]  [--ip <device ip>] [-d[evice] <name>] [--all] [-t[imeout] <seconds>] [--play <url>]'.format(__file__))

   def version():
      print(__version__)

   try:
      opts, args = getopt.getopt(sys.argv[1:], "hvd:t:i:", ['help', 'version', 'log=', 'ip=', 'play=', 'pause', 'stop', 'list', 'device=', 'timeout=', 'all'])
   except getopt.GetoptError:
      usage()
      sys.exit(1)

   device = ''
   url = ''
   timeout = 0.5
   action = ''
   logLevel = logging.WARN
   compatibleOnly = True
   ip = ''
   for opt, arg in opts:
      if opt in ('-h', '--help'):
         usage()
         sys.exit(0)
      elif opt in ('-v', '--version'):
         version()
         sys.exit(0)
      elif opt in ('--log'):
         if arg.lower() == 'debug':
             logLevel = logging.DEBUG
         elif arg.lower() == 'info':
             logLevel = logging.INFO
         elif arg.lower() == 'warn':
             logLevel = logging.WARN
      elif opt in ('--all'):
         compatibleOnly = False
      elif opt in ('-d', '--device'):
         device = arg
      elif opt in ('-t', '--timeout'):
         timeout = float(arg)
      elif opt in ('-i', '--ip'):
         ip = arg
         compatibleOnly = False
         timeout = 10
      elif opt in ('--list'):
         action = 'list'
      elif opt in ('--play'):
         action = 'play'
         url = arg
      elif opt in ('--pause'):
         action = 'pause'
      elif opt in ('--stop'):
         action = 'stop'

   logging.basicConfig(level=logLevel)

   st = URN_AVTransport if compatibleOnly else SSDP_ALL
   allDevices = discover(name=device, ip=ip, timeout=timeout, st=st)
   if not allDevices:
      print('No compatible devices found.')
      sys.exit(1)

   if action in ('', 'list'):
      print('Discovered devices:')
      for d in allDevices:
         print(' {} {}'.format('[a]' if d.has_av_transport else '[x]', d))
      sys.exit(0)

   d = allDevices[0]
   print(d)
   if action == 'play':
      try:
         d.set_current(url=url)
         d.play()
      except Exception as e:
         print('Device is unable to play media.')
         logging.warn('Play exception:\n{}'.format(traceback.format_exc()))
         sys.exit(1)
   elif action == 'pause':
      d.pause()
   elif action == 'stop':
      d.stop()
