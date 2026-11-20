# Uptime Kuma on the Raspberry Pi

Optional: a dashboard on the Pi that watches the robot, its SSH, Mosquitto, Home
Assistant, the NUC, Cockpit and Kodi, with a history and notifications.

Install it without Docker (Docker rewrites the firewall and would block the Pi's
routing between its Ethernet port and its Wi-Fi access point). It needs Node.js 20.4
or newer (Debian trixie's is enough):

```sh
cd ~ && git clone https://github.com/louislam/uptime-kuma.git
cd uptime-kuma && npm run setup
sudo npm install -g pm2 && pm2 install pm2-logrotate
pm2 start server/server.js --name uptime-kuma
pm2 save && pm2 startup     # then run the "sudo env PATH=…" line it prints
```

`pi/uptime_kuma_monitors.js` (in the repository) then adds the monitors: on a first
run it chooses the SQLite database and creates the admin account (or logs in), asks
for the addresses, and adds the monitors not there yet. Run it on the Pi with
`node uptime_kuma_monitors.js`; it can be run again.

In the plugin, set the Pi's *Web address* to `http://<Pi>:3001`: the Pi's 🌐 button
opens it. You can also add it as a *Web service* to see in the strip whether it
answers.
