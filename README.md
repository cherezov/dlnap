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
dlnap.py [--list] [-d[evice] <name>] [-t[imeout] <seconds>] [--play <url>] [--compatible]
```
#### Discover UPnP devices
```
> dlnap.py --list
Discovered devices:
 [x] ZyXEL Keenetic Giga @ 192.168.1.1
 [x] Data @ 192.168.1.50
 [a] Receiver rx577 @ 192.168.1.40
```
"[a]" means that devices allows media to playback  
"[x]" means that device doesn't allow media to playback  

Compatible mode will show only devices wich allows playback media
```
> dlnap.py --list --compatible
Discovered devices:
 [a] Receiver rx577 @ 192.168.1.40
```

#### Play media
```
dlnap.py --device rx577 --play 'http://somewhere.com/my_favorite_music.mp3'
```
Note: a part of the device name is quite enough: *rx577* instead of *Receiver rx577*
