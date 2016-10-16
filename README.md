# dlnap
Enjoy your favorite music on your favorite sound system over your local network.  
Simple network player for DLNA UPnP devices allows you discover devices and playback your favorite media on them.

## Requires
 * Nothing but python (whatever you like: python 2.7+ or python3)
 
## Supported devices
 * Yamaha RX577
 * _please email me if it works or doesn't work with your device_
 
## Usage
### As console app
#### Overview
```
dlna.py [--list] [-d[evice] <name>] [-t[imeout] <seconds>] [--play <url>]
```
#### Discover UPnP devices
```
> dlnap.py --list
Discovered devices:
 - ZyXEL Keenetic Giga @ 192.168.1.1
 - Data @ 192.168.1.50
 + Receiver rx577 @ 192.168.1.40
```
"+" means that devices allows media to play  
"-" means that device doesn't allow media to play

#### Play media
```
dlnap.py --device rx577 --play 'http://somewhere.com/my_favorite_music.mp3'
```
Note: a part of the device name is quite enough: *rx577* instead of *Receiver rx577*
