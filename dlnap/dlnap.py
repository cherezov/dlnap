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
#   0.12 local files can be played as well now via proxy
#   0.13 ssdp protocol version argument added
#   0.14 fixed bug with receiving responses from device
#   0.15 Lot's of fixes and features added thanks @ttopholm and @NicoPy
#
#   1.0  moved from idea version

__version__ = "0.15"

import re
import sys
import time
import signal
import socket
import select
import logging
import traceback
import mimetypes
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
URN_AVTransport_Fmt = "urn:schemas-upnp-org:service:AVTransport:{}"

URN_RenderingControl = "urn:schemas-upnp-org:service:RenderingControl:1"
URN_RenderingControl_Fmt = "urn:schemas-upnp-org:service:RenderingControl:{}"

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
   
   # replace self-closing <tag/> by <tag>None</tag> 
   empty_elmt = '<' + tag + ' />'
   closed_elmt = '<' + tag + '>None</'+tag+'>'
   if x.startswith(empty_elmt):
      x = x.replace(empty_elmt, closed_elmt)

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

      if os.path.exists(url):
         f = open(url)
         content_type = mimetypes.guess_type(url)[0]
      else:
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

      content_type = ''
      if os.path.exists(url):
         f = open(url)
         content_type = mimetypes.guess_type(url)[0]
         size = os.path.getsize(url)
      elif not url or not url.startswith('http'):
         self.response_success()
         return
      else:
         f = urlopen(url=url)

      try:
         if not content_type:
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


def _get_control_url(xml, urn):
   """ Extract AVTransport contol url from device description xml

   xml -- device description xml
   return -- control url or empty string if wasn't found
   """
   return _xpath(xml, 'root/device/serviceList/service@serviceType={}/controlURL'.format(urn))

@contextmanager
def _send_udp(to, packet):
   """ Send UDP message to group

   to -- (host, port) group to send the packet to
   packet -- message to send
   """
   sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
   sock.sendto(packet.encode(), to)
   yield sock
   sock.close()

def _unescape_xml(xml):
   """ Replace escaped xml symbols with real ones.
   """
   return xml.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')

def _send_tcp(to, payload):
   """ Send TCP message to group

   to -- (host, port) group to send to payload to
   payload -- message to send
   """
   try:
      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      sock.settimeout(5)
      sock.connect(to)
      sock.sendall(payload.encode('utf-8'))

      data = sock.recv(2048)
      if py3:
         data = data.decode('utf-8')
      data = _xml2dict(_unescape_xml(data), True)

      errorDescription = _xpath(data, 's:Envelope/s:Body/s:Fault/detail/UPnPError/errorDescription')
      if errorDescription is not None:
         logging.error(errorDescription)
   except Exception as e:
      data = ''
   finally:
      sock.close()
   return data


def _get_location_url(raw):
    """ Extract device description url from discovery response

    raw -- raw discovery response
    return -- location url string
    """
    t = re.findall('\n(?i)location:\s*(.*)\r\s*', raw, re.M)
    if len(t) > 0:
        return t[0]
    return ''

def _get_friendly_name(xml):
   """ Extract device name from description xml

   xml -- device description xml
   return -- device name
   """
   name = _xpath(xml, 'root/device/friendlyName')
   return name if name is not None else 'Unknown'

def _get_serve_ip(target_ip, target_port=80):
    """ Find ip address of network interface used to communicate with target
    
    target-ip -- ip address of target
    return -- ip address of interface connected to target
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((target_ip, target_port))
    my_ip = s.getsockname()[0]
    s.close()
    return my_ip

class DlnapDevice:
   """ Represents DLNA/UPnP device.
   """

   def __init__(self, raw, ip):
      self.__logger = logging.getLogger(self.__class__.__name__)
      self.__logger.info('=> New DlnapDevice (ip = {}) initialization..'.format(ip))

      self.ip = ip
      self.ssdp_version = 1

      self.port = None
      self.name = 'Unknown'
      self.control_url = None
      self.rendering_control_url = None
      self.has_av_transport = False

      try:
         self.__raw = raw.decode()
         self.location = _get_location_url(self.__raw)
         self.__logger.info('location: {}'.format(self.location))

         self.port = _get_port(self.location)
         self.__logger.info('port: {}'.format(self.port))

         raw_desc_xml = urlopen(self.location).read().decode()

         self.__desc_xml = _xml2dict(raw_desc_xml)
         self.__logger.debug('description xml: {}'.format(self.__desc_xml))

         self.name = _get_friendly_name(self.__desc_xml)
         self.__logger.info('friendlyName: {}'.format(self.name))

         self.control_url = _get_control_url(self.__desc_xml, URN_AVTransport)
         self.__logger.info('control_url: {}'.format(self.control_url))

         self.rendering_control_url = _get_control_url(self.__desc_xml, URN_RenderingControl)
         self.__logger.info('rendering_control_url: {}'.format(self.rendering_control_url))

         self.has_av_transport = self.control_url is not None
         self.__logger.info('=> Initialization completed'.format(ip))
      except Exception as e:
         self.__logger.warning('DlnapDevice (ip = {}) init exception:\n{}'.format(ip, traceback.format_exc()))

   def __repr__(self):
      return '{} @ {}'.format(self.name, self.ip)

   def __eq__(self, d):
      return self.name == d.name and self.ip == d.ip

   def _payload_from_template(self, action, data, urn):
      """ Assembly payload from template.
      """
      fields = ''
      for tag, value in data.items():
        fields += '<{tag}>{value}</{tag}>'.format(tag=tag, value=value)

      payload = """<?xml version="1.0" encoding="utf-8"?>
         <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
               <u:{action} xmlns:u="{urn}">
                  {fields}
               </u:{action}>
            </s:Body>
         </s:Envelope>""".format(action=action, urn=urn, fields=fields)
      return payload

   def _create_packet(self, action, data):
      """ Create packet to send to device control url.

      action -- control action
      data -- dictionary with XML fields value
      """
      if action in ["SetVolume", "SetMute", "GetVolume"]:
          url = self.rendering_control_url
          urn = URN_RenderingControl_Fmt.format(self.ssdp_version)
      else:
          url = self.control_url
          urn = URN_AVTransport_Fmt.format(self.ssdp_version)
      payload = self._payload_from_template(action=action, data=data, urn=urn)

      packet = "\r\n".join([
         'POST {} HTTP/1.1'.format(url),
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

      self.__logger.debug(packet)
      return packet

   def set_current_media(self, url, instance_id = 0):
      """ Set media to playback.

      url -- media url
      instance_id -- device instance id
      """
      packet = self._create_packet('SetAVTransportURI', {'InstanceID':instance_id, 'CurrentURI':url, 'CurrentURIMetaData':'' })
      _send_tcp((self.ip, self.port), packet)

   def play(self, instance_id = 0):
      """ Play media that was already set as current.

      instance_id -- device instance id
      """
      packet = self._create_packet('Play', {'InstanceID': instance_id, 'Speed': 1})
      _send_tcp((self.ip, self.port), packet)

   def pause(self, instance_id = 0):
      """ Pause media that is currently playing back.

      instance_id -- device instance id
      """
      packet = self._create_packet('Pause', {'InstanceID': instance_id, 'Speed':1})
      _send_tcp((self.ip, self.port), packet)

   def stop(self, instance_id = 0):
      """ Stop media that is currently playing back.

      instance_id -- device instance id
      """
      packet = self._create_packet('Stop', {'InstanceID': instance_id, 'Speed': 1})
      _send_tcp((self.ip, self.port), packet)


   def seek(self, position, instance_id = 0):
      """
      Seek position
      """
      packet = self._create_packet('Seek', {'InstanceID':instance_id, 'Unit':'REL_TIME', 'Target': position })
      _send_tcp((self.ip, self.port), packet)


   def volume(self, volume=10, instance_id = 0):
      """ Stop media that is currently playing back.

      instance_id -- device instance id
      """
      packet = self._create_packet('SetVolume', {'InstanceID': instance_id, 'DesiredVolume': volume, 'Channel': 'Master'})

      _send_tcp((self.ip, self.port), packet)
      
      
   def get_volume(self, instance_id = 0):
      """
      get volume
      """
      packet = self._create_packet('GetVolume', {'InstanceID':instance_id, 'Channel': 'Master'})
      _send_tcp((self.ip, self.port), packet)


   def mute(self, instance_id = 0):
      """ Stop media that is currently playing back.

      instance_id -- device instance id
      """
      packet = self._create_packet('SetMute', {'InstanceID': instance_id, 'DesiredMute': '1', 'Channel': 'Master'})
      _send_tcp((self.ip, self.port), packet)

   def unmute(self, instance_id = 0):
      """ Stop media that is currently playing back.

      instance_id -- device instance id
      """
      packet = self._create_packet('SetMute', {'InstanceID': instance_id, 'DesiredMute': '0', 'Channel': 'Master'})
      _send_tcp((self.ip, self.port), packet)

   def info(self, instance_id=0):
      """ Transport info.

      instance_id -- device instance id
      """
      packet = self._create_packet('GetTransportInfo', {'InstanceID': instance_id})
      return _send_tcp((self.ip, self.port), packet)

   def media_info(self, instance_id=0):
      """ Media info.

      instance_id -- device instance id
      """
      packet = self._create_packet('GetMediaInfo', {'InstanceID': instance_id})
      return _send_tcp((self.ip, self.port), packet)


   def position_info(self, instance_id=0):
      """ Position info.
      instance_id -- device instance id
      """
      packet = self._create_packet('GetPositionInfo', {'InstanceID': instance_id})
      return _send_tcp((self.ip, self.port), packet)


   def set_next(self, url):
      pass

   def next(self):
      pass


def discover(name = '', ip = '', timeout = 1, st = SSDP_ALL, mx = 3, ssdp_version = 1):
   """ Discover UPnP devices in the local network.

   name -- name or part of the name to filter devices
   timeout -- timeout to perform discover
   st -- st field of discovery packet
   mx -- mx field of discovery packet
   return -- list of DlnapDevice
   """
   st = st.format(ssdp_version)
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
             d.ssdp_version = ssdp_version
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

#
# Signal of Ctrl+C
# =================================================================================================
def signal_handler(signal, frame):
   print(' Got Ctrl + C, exit now!')
   sys.exit(1)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
   import getopt

   def usage():
      print('{} [--ip <device ip>] [-d[evice] <name>] [--all] [-t[imeout] <seconds>] [--play <url>] [--pause] [--stop] [--proxy]'.format(__file__))
      print(' --ip <device ip> - ip address for faster access to the known device')
      print(' --device <device name or part of the name> - discover devices with this name as substring')
      print(' --all - flag to discover all upnp devices, not only devices with AVTransport ability')
      print(' --play <url> - set current url for play and start playback it. In case of url is empty - continue playing recent media.')
      print(' --pause - pause current playback')
      print(' --stop - stop current playback')
      print(' --mute - mute playback')
      print(' --unmute - unmute playback')
      print(' --volume <vol> - set current volume for playback')
      print(' --seek <position in HH:MM:SS> - set current position for playback')
      print(' --timeout <seconds> - discover timeout')
      print(' --ssdp-version <version> - discover devices by protocol version, default 1')
      print(' --proxy - use local proxy on proxy port')
      print(' --proxy-port <port number> - proxy port to listen incomming connections from devices, default 8000')
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
                                                               'volume=',
                                                               'mute',
                                                               'unmute',
                                                               'seek=',


                                                               # discover arguments
                                                               'list',
                                                               'all',
                                                               'timeout=',
                                                               'ssdp-version=',

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
   vol = 10
   position = '00:00:00'
   timeout = 1
   action = ''
   logLevel = logging.WARN
   compatibleOnly = True
   ip = ''
   proxy = False
   proxy_port = 8000
   ssdp_version = 1
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
      elif opt in ('--ssdp-version'):
         ssdp_version = int(arg)
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
      elif opt in ('--volume'):
         action = 'volume'
         vol = arg
      elif opt in ('--seek'):
         action = 'seek'
         position = arg
      elif opt in ('--mute'):
         action = 'mute'
      elif opt in ('--unmute'):
         action = 'unmute'
      elif opt in ('--info'):
         action = 'info'
      elif opt in ('--media-info'):
         action = 'media-info'
      elif opt in ('--proxy'):
         proxy = True
      elif opt in ('--proxy-port'):
         proxy_port = int(arg)

   logging.basicConfig(level=logLevel)

   st = URN_AVTransport_Fmt if compatibleOnly else SSDP_ALL
   allDevices = discover(name=device, ip=ip, timeout=timeout, st=st, ssdp_version=ssdp_version)
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
      ip = _get_serve_ip(d.ip)
      t = threading.Thread(target=runProxy, kwargs={'ip' : ip, 'port' : proxy_port})
      t.daemon = True
      t.start()
      time.sleep(2)

   if action == 'play':
      try:
         d.stop()
         url = 'http://{}:{}/{}'.format(ip, proxy_port, url) if proxy else url
         d.set_current_media(url=url)
         d.play()
      except Exception as e:
         print('Device is unable to play media.')
         logging.warn('Play exception:\n{}'.format(traceback.format_exc()))
         sys.exit(1)
   elif action == 'pause':
      d.pause()
   elif action == 'stop':
      d.stop()
   elif action == 'volume':
      d.volume(vol)
   elif action == 'seek':
      d.seek(position)
   elif action == 'mute':
      d.mute()
   elif action == 'unmute':
      d.unmute()
   elif action == 'info':
      print(d.info())
   elif action == 'media-info':
      print(d.media_info())

   if proxy:
      while running:
         time.sleep(30)
