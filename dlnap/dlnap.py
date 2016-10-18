#!/usr/bin/python

# @file dlnap.py
# @author cherezov.pavel@gmail.com
# @brief Python over the network media player to playback on DLNA UPnP devices.

# Change log:
#   0.1 Initial version.
#   0.2 Device renamed to DlnapDevice; DLNAPlayer is disappeared.
#   0.3 Debug output is added. Extract location url fixed.
#   0.4 Compatible discover mode added.

__version__ = "0.4"

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

def _get_port(location):
   """ Extract port number from url.

   location -- string like http://anyurl:port/whatever/path
   return -- port number
   """
   port = re.findall('http://.*:(\d+)/.*', location)
   return int(port[0]) if port else 80

def xml2dict(xml, path):
   """

   <a>
      <b>value1</b>
      <b>value2</b>
      <c/>
      <d>
         <e>value4</e>
      </d>
   </a>

   { 'a':
     {
         'b': [value1, value2],
         'c': [],
         'd':
         {
           'e': [value4] 
         }
     } 
   }

   """
   result = {}

   tag_ready = False
   curr_tag = ''

def get_tag_value(x, i = 0):
   """
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

   # empty tag like '</tag>'
   if x[i:].startswith('</'):
      i += 1
      while i < len(x) and x[i] != '>': 
         tag += x[i]
         i += 1
      return (tag, '')

   if not x[i:].startswith('<'):
      raise Exception('bad xml:\n {}'.format(x[i:]))

   i += 1 # < 

   # read top open tag      
   while i < len(x) and x[i] != '>': 
      tag += x[i]
      i += 1

   i += 1 # > 

   while i < len(x):
      if x[i] == '>' and value.endswith(tag):
         close_tag_len = len(tag) + 2 # />
         value = value[:-close_tag_len]
         break
      value += x[i]
      i += 1

   return (tag, value)


s =  """
            <d>
               <e>value4</e>
            </d>
"""
t, v = get_tag_value(s)
t1, v1 = get_tag_value(v)
t2, v2 = get_tag_value(v1)
print(t, v)
print(t1, v1)
print(t2, v1)
sys.exit(1)



def _get_control_url(raw):
   """ Extract AVTransport contol url from raw device description xml

   raw -- raw device description xml
   return -- control url or empty string if wasn't found
   """
   url = re.findall('\<serviceType\>{}\</serviceType\>.*\<controlURL\>(.*)\</controlURL\>'.format(re.escape(URN_AVTransport)), raw.replace('\n', ''))
   return url[0] if url else ''

@contextmanager
def _send_udp(to, payload):
   """ Send UDP mesage to group

   to -- (host, port) group to send to payload to
   payload -- message to send
   """
   sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
   sock.sendto(payload.encode(), to)
   yield sock
   sock.close()

def _send_tcp(to, payload):
   """ Send TCP mesage to group

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

def _get_friendly_name(raw):
   """ Extract device name from raw description xml

   raw -- device description xml
   return -- device name
   """
   name = re.findall('\<friendlyName\>(.*)\</friendlyName\>', raw)
   return name[0] if name else 'Unknown'

class DlnapDevice:
   """ Represents DLNA device.
   """

   def __init__(self, raw, ip, debug=False):
      self.__raw = raw.decode()
      self.ip = ip
      self.port = None
      self.control_url = None
      self.name = 'Unknown'
      self.has_av_transport = False
      self.debug = debug

      try:
         self.location = _get_location_url(self.__raw)
         self.port = _get_port(self.location)
         self.__desc_xml = urlopen(self.location).read().decode()
         self.name = _get_friendly_name(self.__desc_xml)
         self.has_av_transport = '<serviceType>{}</serviceType>'.format(URN_AVTransport) in self.__desc_xml
         self.control_url = _get_control_url(self.__desc_xml)

         if self.ip == '192.168.1.35':
            print('==NEW DEVICE')
            print(self.ip)
            print(self.control_url)

      except Exception as e:
         if self.debug:
            print('==EXCEPTION')
            print(e)
            print(self.ip)
            print(self.location)

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
         'User-Agent: dlnap/{}'.format(__version__),
         'Accept: */*',
         'Content-Type: text/xml; charset="utf-8"',
         'HOST: {}:{}'.format(self.ip, self.port),
         'Content-Length: {}'.format(len(payload)),
         'SOAPACTION: "{}#{}"'.format(URN_AVTransport, action),
         'Connection: close',
         '',
         payload,
         ])

      print(header)
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

#def discover(name = '', timeout = 1, st = "ssdp:all", mx = 3, compatibleOnly = False, debug = False):
def discover(name = '', timeout = 1, st = URN_AVTransport, mx = 3, compatibleOnly = False, debug = False):
   """ Discover UPnP devices in the local network.

   name -- name or part of the name to filter devices
   timeout -- timeout to perform discover
   st -- st field of discovery packet
   mx -- mx field of discovery packet
   debug -- True if debug output is required
   return -- list of DlnapDevice
   """
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
   with _send_udp(SSDP_GROUP, payload) as sock:
      start = time.time()
      while True:
         if time.time() - start > timeout:
            # timed out
            break
         r, w, x = select.select([sock], [], [sock], 1)
         if sock in r:
             data, addr = sock.recvfrom(1024)
             d = DlnapDevice(data, addr[0], debug=debug)
             if d not in devices:
                if not name or name is None or name.lower() in d.name.lower():
                   if not compatibleOnly or d.has_av_transport:
                      devices.append(d)
         elif sock in x:
             raise Exception('Getting response failed')
         else:
             # Nothing to read
             pass
   return devices

if __name__ == '__main__':
   import getopt

   def usage():
      print('dlnap.py [--list] [-d[evice] <name>] [--compatible] [-t[imeout] <seconds>] [--play <url>]')

   try:
      opts, args = getopt.getopt(sys.argv[1:], "hvd:t:", ['help', 'version', 'debug', 'play=', 'pause', 'stop', 'list', 'device=', 'timeout=', 'compatible'])
   except getopt.GetoptError:
      usage()
      sys.exit(1)

   device = ''
   url = ''
   timeout = 0.5
   action = ''
   debug = False
   compatibleOnly = False
   for opt, arg in opts:
      if opt in ('-h', '--help'):
         usage()
         sys.exit(0)
      if opt in ('-v', '--version'):
         print(__version__)
         sys.exit(0)
      if opt in ('--debug'):
         debug = True
      if opt in ('--compatible'):
         compatibleOnly = True
      elif opt in ('-d', '--device'):
         device = arg
      elif opt in ('-t', '--timeout'):
         timeout = float(arg)
      if opt in ('--list'):
         action = 'list'
      elif opt in ('--play'):
         action = 'play'
         url = arg
      elif opt in ('--pause'):
         action = 'pause'
      elif opt in ('--stop'):
         action = 'stop'

   allDevices = discover(name=device, timeout=timeout, compatibleOnly=compatibleOnly, debug=debug)
   if not allDevices:
      print('No devices found.')
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
         print('setting url = {}'.format(url))
         d.set_current(url=url, instance_id = 0)
         print('playing')
         d.play(instance_id = 0)
      except Exception as e:
         print('Device is unable to play media.')
         if debug:
            print('Location: {}:{}'.format(d.location, d.port))
            print(e)
         sys.exit(1)
   elif action == 'pause':
      d.pause()
   elif action == 'stop':
      d.stop()
