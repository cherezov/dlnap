#!/usr/bin/python

# @file dlnap.py
# @author cherezov.pavel@gmail.com
# @brief Python over the network media player to playback on DLNA UPnP devices.

# Change log:
#   0.1  initial version.
#   0.2  device renamed to DlnapDevice; DLNAPlayer is disappeared.
#   0.3  debug output is added. Extract location url fixed.
#   0.4  compatible discover mode added.
#   0.5  xml parser introduced for device descriptions
#   0.6  xpath introduced to navigate over xml dictionary
#   0.7  device ip argument introduced
#   0.8  debug output is replaced with standard logging
#   0.9  pause/stop added. Video playback tested on Samsung TV
#   0.10 proxy (draft) is introduced.
#   0.11 sync proxy for py2 and py3 implemented, --proxy-port added

__version__ = "0.11"

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
   from http.server import HTTPServer
   from http.server import BaseHTTPRequestHandler
else:
   from urllib2 import urlopen
   from BaseHTTPServer import BaseHTTPRequestHandler
   from BaseHTTPServer import HTTPServer

import shutil
import threading


SSDP_GROUP = ("239.255.255.250", 1900)
URN_AVTransport = "urn:schemas-upnp-org:service:AVTransport:1"
SSDP_ALL = "ssdp:all"

# =================================================================================================
# XML to DICT
#
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
      return (tag.strip(), '', x[i+1:])

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
   return (tag.strip(), value[:-1], x[i+1:])

def _xml2dict(s, ignoreUntilXML = False):
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
   if ignoreUntilXML:
      s = ''.join(re.findall(".*?(<.*)", s, re.M))

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
   hello 
   this is a bad
   strings

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
#
# XML to DICT
# =================================================================================================
# PROXY
#
running = False
class DownloadProxy(BaseHTTPRequestHandler):

   def log_message(self, format, *args):
      pass

   def log_request(self, code='-', size='-'):
      pass

   def response_success(self):
      url = self.path[1:] # replace '/'
      f = urlopen(url=url)
      if py3:
         content_type = f.getheader("Content-Type")
      else:
         content_type = f.info().getheaders("Content-Type")[0]

      self.send_response(200, "ok")
      self.send_header('Access-Control-Allow-Origin', '*')
      self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
      self.send_header("Access-Control-Allow-Headers", "X-Requested-With")
      self.send_header("Access-Control-Allow-Headers", "Content-Type")
      self.send_header("Content-Type", content_type)
      self.end_headers()

   def do_OPTIONS(self):
      self.response_success()

   def do_HEAD(self):
      self.response_success()

   def do_GET(self):
      global running
      url = self.path[1:] # replace '/'

      if not url or not url.startswith('http'):
         self.response_success()
         return

      f = urlopen(url=url)
      try:
         if py3:
            content_type = f.getheader("Content-Type")
            size = f.getheader("Content-Length")
         else:
            content_type = f.info().getheaders("Content-Type")[0]
            size = f.info().getheaders("Content-Length")[0]

         self.send_response(200)
         self.send_header('Access-Control-Allow-Origin', '*')
         self.send_header("Content-Type", content_type)
         self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(os.path.basename(url)))
         self.send_header("Content-Length", str(size))
         self.end_headers()
         shutil.copyfileobj(f, self.wfile)
      finally:
         running = False
         f.close()

def runProxy(ip = '', port = 8000):
   global running
   running = True
   DownloadProxy.protocol_version = "HTTP/1.0"
   httpd = HTTPServer((ip, port), DownloadProxy)
   while running:
      httpd.handle_request()

#
# PROXY
# =================================================================================================

def _get_port(location):
   """ Extract port number from url.

   location -- string like http://anyurl:port/whatever/path
   return -- port number
   """
   port = re.findall('http://.*?:(\d+).*', location)
   return int(port[0]) if port else 80


def _get_control_url(xml, urn = URN_AVTransport):
   """ Extract AVTransport contol url from device description xml

   xml -- device description xml
   return -- control url or empty string if wasn't found
   """
   return _xpath(xml, 'root/device/serviceList/service@serviceType={}/controlURL'.format(urn))

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
      sock.settimeout(5)
      sock.connect(to)
      sock.sendall(payload.encode())

      data = sock.recv(2048)
      if py3:
         data = data.decode()
      data = _xml2dict(data.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'), True)
      errorDescription = _xpath(data, 's:Envelope/s:Body/s:Fault/detail/UPnPError/errorDescription')
      if errorDescription is not None:
         logging.error(errorDescription)
      return data
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
         if self.name is None:
            self.name = 'Unknown'
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

   def _create_packet(self, action, payload, control_url, urn = URN_AVTransport):
      """ Create packet to send to device control url.

      action -- control action
      payload -- xml to send to device
      """
      header = "\r\n".join([
         'POST {} HTTP/1.1'.format(control_url),
         'User-Agent: {}/{}'.format(__file__, __version__),
         'Accept: */*',
         'Content-Type: text/xml; charset="utf-8"',
         'HOST: {}:{}'.format(self.ip, self.port),
         'Content-Length: {}'.format(len(payload)),
         'SOAPACTION: "{}#{}"'.format(urn, action),
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

      packet = self._create_packet('SetAVTransportURI', payload, self.control_url)
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

      packet = self._create_packet('Play', payload, self.control_url)
      _send_tcp((self.ip, self.port), packet)

   def pause(self, instance_id = 0):
      """ Pause media that is currently playing back.

      instance_id -- device instance id
      """
      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:Pause xmlns:u="{}">
                  <InstanceID>{}</InstanceID>
                  <Speed>1</Speed>
               </u:Pause>
            </s:Body>
         </s:Envelope>""".format(URN_AVTransport, instance_id)

      packet = self._create_packet('Pause', payload, self.control_url)
      _send_tcp((self.ip, self.port), packet)

   def stop(self, instance_id = 0):
      """ Stop media that is currently playing back.

      instance_id -- device instance id
      """
      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:Stop xmlns:u="{}">
                  <InstanceID>{}</InstanceID>
                  <Speed>1</Speed>
               </u:Stop>
            </s:Body>
         </s:Envelope>""".format(URN_AVTransport, instance_id)

      packet = self._create_packet('Stop', payload, self.control_url)
      _send_tcp((self.ip, self.port), packet)

   def set_next(self, url):
      pass

   def next(self):
      pass

   def info(self, instance_id=0):
      """ Transport info.

      instance_id -- device instance id
      """
      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:GetTransportInfo xmlns:u="{}">
                  <InstanceID>{}</InstanceID>
               </u:GetTransportInfo>
            </s:Body>
         </s:Envelope>""".format(URN_AVTransport, instance_id)

      packet = self._create_packet('GetTransportInfo', payload, self.control_url)
      data = _send_tcp((self.ip, self.port), packet)
      print(data)

   def media_info(self, instance_id=0):
      """ Transport info.

      instance_id -- device instance id
      """
      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:GetMediaInfo xmlns:u="{}">
                  <InstanceID>{}</InstanceID>
               </u:GetMediaInfo>
            </s:Body>
         </s:Envelope>""".format(URN_AVTransport, instance_id)

      packet = self._create_packet('GetMediaInfo', payload, self.control_url)
      data = _send_tcp((self.ip, self.port), packet)
      print(data)

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
                if not name or name is None or name.lower() in d.name.lower():
                   if not ip:
                      devices.append(d)
                   elif d.has_av_transport:
                      # no need in further searching by ip
                      devices.append(d)
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
      print(' --ip <device ip> - ip address for faster access to the known device')
      print(' --device <device name or part of the name> - discover devices with this name as substring')
      print(' --all - flag to discover all upnp devices, not only devices with AVTransport ability')
      print(' --play <url> - set current url for play and start playback it. In case of url is empty - continue playing recent media.')
      print(' --pause - pause current playback')
      print(' --stop - stop current playback')
      print(' --timeout <seconds> - discover timeout')
      print(' --help - this help')

   def version():
      print(__version__)

   try:
      opts, args = getopt.getopt(sys.argv[1:], "hvd:t:i:", [   # information arguments
                                                               'help',
                                                               'version',
                                                               'log=',

                                                               # device arguments
                                                               'device=',
                                                               'ip=',

                                                               # action arguments
                                                               'play=',
                                                               'pause',
                                                               'stop',

                                                               # discover arguments
                                                               'list',
                                                               'all',
                                                               'timeout=',

                                                               # transport info
                                                               'info',
                                                               'media-info',

                                                               # download proxy
                                                               'proxy',
                                                               'proxy-port='])
   except getopt.GetoptError:
      usage()
      sys.exit(1)

   device = ''
   url = ''
   timeout = 1
   action = ''
   logLevel = logging.WARN
   compatibleOnly = True
   ip = ''
   proxy = False
   proxy_port = 8000
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
      elif opt in ('--info'):
         action = 'info'
      elif opt in ('--media-info'):
         action = 'media-info'
      elif opt in ('--proxy'):
         proxy = True
      elif opt in ('--proxy-port'):
         proxy_port = int(arg)

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

   if url.lower().replace('https://', '').replace('www.', '').startswith('youtube.'):
      import subprocess
      process = subprocess.Popen(['youtube-dl', '-g', url], stdout = subprocess.PIPE)
      url, err = process.communicate()

   if url.lower().startswith('https://'):
      proxy = True

   if proxy:
      ip = socket.gethostbyname(socket.gethostname())
      t = threading.Thread(target=runProxy, kwargs={'ip' : ip, 'port' : proxy_port})
      t.start()
      time.sleep(2)

   if action == 'play':
      try:
         d.stop()
         url = 'http://{}:{}/{}'.format(ip, proxy_port, url) if proxy else url
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
   elif action == 'info':
      d.info()
   elif action == 'media-info':
      d.media_info()

   if proxy:
      t.join()
