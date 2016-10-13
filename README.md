# dlnap
Enjoy your favorite music on your favorite sound system over WiFi.  
Simple network player for DLNA UPnP devices allows you discover devices on your local network and send your favorite media to play on them.

## Requires
 * Nothing but python (whatever you like: python 2.7+ or python3)
 
## Supported devices
 * Yamaha RX
 * _please email me if it works or doesn't work with your device_
 
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
