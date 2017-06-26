# dlnap
Enjoy music on your favorite sound system or share a picture or YouTube video with your folks and friends on smart TV.
Simple network player for DLNA/UPnP devices allows you discover devices and playback media on them. 

## Requires
 * Python (whatever you like: python 2.7+ or python3)
 * [youtube-dl](https://github.com/rg3/youtube-dl) to playback YouTube links
 
## TODO
- [ ] Fix '&' bug
- [ ] Set next media
- [x] Volume control
- [ ] Position control
- [ ] Add support to play media from local machine, e.g --play /home/username/media/music.mp3 for py3
- [ ] Try it on Windows
- [ ] Add AVTransport:2 and further support
- [ ] Play on multiple devices
- [x] Integrate [local download proxy](https://github.com/cherezov/red)
- [x] Stop/Pause playback
- [x] Investigate if it possible to play images/video's on DLNA/UPnP powered TV (possible via [download proxy](https://github.com/cherezov/dlnap#proxy))
 
## Supported devices/software
 - [x] Yamaha RX577
 - [x] Samsung Smart TV (UE40ES5507) via [proxy](https://github.com/cherezov/dlnap#proxy)
 - [x] Marantz MR611
 - [x] [Kodi](https://kodi.tv/)
 - [ ] [Volumio2](https://github.com/volumio/Volumio2) (?)
 * _please email me if it works or doesn't work with your device_
 
## Usage
### Overview
```
dlnap.py [<selector>] [<command>] [<feature>]
```  
__Selectors:__  
```--ip <device ip>``` ip address for faster access to the known device  
```--device <device name or part of the name>``` discover devices with this name as substring  
__Commands:__  
```--list``` default command. Lists discovered UPnP devices in the network  
```--play <url>``` set current url for play and start playback it. In case of empty url - continue playing recent media  
```--pause``` pause current playback  
```--stop``` stop current playback  
__Features:__  
```--all``` flag to discover all upnp devices, not only devices with AVTransport ability  
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

**List all available UPnP devices**
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
**Playback music**
```
> dlnap.py --ip 192.168.1.40 --play http://somewhere.com/music.mp3
Receiver rx577 @ 192.168.1.40
```  
**Playback video**
```
> dlnap.py --device tv --play http://somewhere.com/video.mp4
Samsung TV @ 192.168.1.35
```
**Show image**
```
> dlnap.py --device tv --play http://somewhere.com/image.jpg
Samsung TV @ 192.168.1.35
```
**Local files**
```
> dlnap.py --device tv --play ~/media/video.mp4 --proxy
Samsung TV @ 192.168.1.35
```

**YouTube links**
```
> dlnap.py --device tv --play https://www.youtube.com/watch?v=q0eWOaLxlso
Samsung TV @ 192.168.1.35
```
**Note:** requires [youtube-dl](https://github.com/rg3/youtube-dl) installed

### Proxy
Some devices doesn not able to play ```https``` links or links pointed outside of the local network.  
For such cases ```dlnap.py``` tool allows to redirect such links to embeded download proxy.  

__Example:__  
The following command will set up a local http server at ```http://<your ip>:8000``` and tells TV to download file ```http://somewhere.com/video.mp4``` from this http server:  
```
> dlnap.py --device tv --play http://somewhere.com/video.mp4 --proxy
```

So behind the scene the command looks like:  
```
> dlnap.py --device tv --play 'http://<your ip>:8000/http://somewhere.com/video.mp4'
```
**Note:** proxy is syncronous which means that ```dlnap.py``` will not exit while device downloading file to playback.

### We need to go deeper :octocat:
**YouTube/Vimeo/etc videos**  
In general device can playback direct links to a video file or a stream url only.  
There are tools to convert (YouTube) url to stream url, e.g [youtube-dl tool](https://github.com/rg3/youtube-dl).  
Assuming you have download proxy up and running at ```http://<proxy ip>:8000``` you can now play a video using command:  
```
> dlnap.py --device tv --play http://<proxy ip>:8000/`youtube-dl -g https://www.youtube.com/watch?v=q0eWOaLxlso`
Samsung TV @ 192.168.1.35
```
