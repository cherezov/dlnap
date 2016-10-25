# dlnap
**Development is still in progress..**  
Enjoy your favorite music on your favorite sound system over your local network or send YouTube video to your smart TV.
Simple network player for DLNA/UPnP devices allows you discover devices and playback your favorite media on them.

## Requires
 * Python (whatever you like: python 2.7+ or python3)
 * [youtube-dl](https://github.com/rg3/youtube-dl) to playback YouTube links
 
## TODO
- [ ] Set next media
- [x] Integrate [local download proxy](https://github.com/cherezov/red)
- [x] Stop/Pause playback
- [x] Investigate if it possible to play images/video's on DLNA/UPnP powered TV (possible via [local download proxy](https://github.com/cherezov/red))
 
## Supported devices
 * Yamaha RX577
 * Samsung Smart TV (UE40ES5507) via [proxy](https://github.com/cherezov/red)
 * _please email me if it works or doesn't work with your device_
 
## Usage
### Overview
```
dlnap.py [--ip <device ip>] [-d[evice] <name>] [--play <url>] [--pause] [--stop] [--list] [--all] [--proxy]
```
```--ip <device ip>```  ip address for faster access to the known device  
```--device <device name or part of the name>``` discover devices with this name as substring  
```--all``` flag to discover all upnp devices, not only devices with AVTransport ability  
```--play <url>``` set current url for play and start playback it. In case of empty url - continue playing recent media  
```--pause``` pause current playback  
```--stop``` stop current playback  
```--proxy``` use sync local download proxy, default is ip of current machine
```--proxy-port``` port for local download proxy, default is 8000
```--timeout <seconds>``` discover timeout  

### Discover UPnP devices
**List devices which are able to playback media only**
```
> dlnap.py
Discovered devices:
 [a] Receiver rx577 @ 192.168.1.40
 [a] Samsung TV @ 192.168.1.35
```

**List all UPnP devices**
```
> dlnap.py --all
Discovered devices:
 [x] ZyXEL Keenetic Giga @ 192.168.1.1
 [a] Samsung TV @ 192.168.1.35
 [x] Data @ 192.168.1.50
 [a] Receiver rx577 @ 192.168.1.40
```  
where  
**[a]** means that devices allows media playback  
**[x]** means that device doesn't allow media playback  


### Playback media
**By ip address**
```
dlnap.py --ip 192.168.1.40 --play 'http://somewhere.com/my_favorite_music.mp3'
Receiver rx577 @ 192.168.1.40

dlnap.py --ip 192.168.1.40 --pause 'http://somewhere.com/my_favorite_music.mp3'
Receiver rx577 @ 192.168.1.40

dlnap.py --ip 192.168.1.40 --play ''
Receiver rx577 @ 192.168.1.40
```

**By device name**
```
dlnap.py --device rx577 --play 'http://somewhere.com/my_favorite_music.mp3'
Receiver rx577 @ 192.168.1.40
```
Note: a part of the device name is quite enough: *rx577* instead of *Receiver rx577*

**Any compatible device**
```
dlnap.py --play 'http://somewhere.com/my_favorite_music.mp3'
Receiver rx577 @ 192.168.1.40
```
### Proxy
TODO: add some words about proxy here

### Send YouTube videos to smart TV
**Note:** requires [youtube-dl](https://github.com/rg3/youtube-dl) installed
```
> dlnap.py --device tv --play https://www.youtube.com/watch?v=q0eWOaLxlso
Samsung TV @ 192.168.1.35
```

**Generic way**  
**Note:** Requires a tool to convert url to direct link to video or stream
```
> dlnap.py --device tv --proxy --play `any_conversion_tool https://www.youtube.com/watch?v=q0eWOaLxlso`
Samsung TV @ 192.168.1.35
```

### Send images to smart TV
```
> dlnap.py --device tv --play http://www.somewhere.com/image.jpg
Samsung TV @ 192.168.1.35
```
