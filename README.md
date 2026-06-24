# Wifi Watch
Simple repository to watch for new hosts that join the network. Uses ICMP ping messages to detect new hosts and displays them in a slick web interface.

## Motivations
I created this project as part of my home network monitoring suite. Literally the entire thing was coded by ChatGPT, this saved me days and possibly weeks of creating a decent solution that would be good enough to do some wifi device monitoring.

## Notes
This applicaiton runs on flask and is only designed for small to medium networks and home networks. It relies on arp tables which are only accurate for the hosts on the local network. Devices are identified by MAC address only. If mac randomization is used by devices that join the network this can be misleading, for example if a new device joins the network that uses mac randomization over time it may appear that a new device joins the network every couple days when it is not the case.

Using DHCP leases to determine what new devices have joined the network recently is a good idea however it would require that either the device running the server be given access to the DHCP server logs, DHCP servers vary in how they can be accessed, if they have api's, and their logging features, I have decided that is not a suitable approach for this particular project but it is good to keep in mind.

By default the application will scan the network every 15 seconds which should catch a majority of the wireless devices that connect.

## Future Development
- Using NMAP to scan currently connected devices to determine what kind of device it is would be interesting and good for IoT device monitoring and fingerprinting.
- Pulling hostnames from devices and adding them to the database for better host identification

## Running the Application
Simply download the git repository, change the variubles in the `run.sh` file to fit the local network you are on and then run it. This will not install the applicaiton and is just for demonstration purposes.

## Installation of the Application
Installation of this application should be done with care, as it scans the network that was configured in its service, this could lead to at the minimum a less than friendly exchange of words with an administrator. Where should this be installed? Maybe a rasbperry pi with an attached screen, maybe an old laptop, really anything that has a wifi card and a screen.
