#!/bin/bash
sudo mkdir /opt/wifi-watch
sudo cp -r * /opt/wifi-watch
sudo cp /opt/wifi-watch/wifi-watch.service /etc/systemd/system/wifi-watch.service
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-watch
sudo systemctl status wifi-watch
