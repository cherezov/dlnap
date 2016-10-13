# dlnap
Simple network player for DLNA UPnP devices.  
It allows discover devices in the local network which are able to play media.

## Requires
 * Python (tested on CentOS with python 2.7 and python 3.4)
 
## Usage
### As console app
#### Overview
```
dlnap.py [-d <device name>] [-u <url to play>] [-t <timeout>] [-l]
```
#### Discover UPnP devices
```
> dlnap.py -l
Discovered devices:
 - ZyXEL Keenetic Giga @ 192.168.1.1
 - Data @ 192.168.1.50
 + Receiver rx577 @ 192.168.1.40
```
"+" means that devices allows playing media  
"-" means that device can not play media

#### Play media
```
dlnap.py -d rx577 -u 'http://somewhere.com/my_favorite_music.mp3'
```
