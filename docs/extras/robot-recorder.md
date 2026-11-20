# The Wi-Fi recorder on the robot

*Advanced tools.* A small shell script on the robot records its Wi-Fi signal and
position whenever it moves, so that QGIS does not have to stay open. Its readings
also give the [history](../robot/history.md) the outings made while QGIS was closed.

In the Wi-Fi tab, *Recorder on the robot* says whether it is installed and where:

- **Record Wi-Fi on the robot…** installs the script over SSH (same login as the
  reboot) and starts it. From then on, whenever the robot moves (cleaning,
  returning, moving, manual control), it records the Wi-Fi signal (read from
  `/proc/net/wireless`, so always fresh) and its position from Valetudo's map, at the
  interval and minimum distance of the *Wi-Fi survey* settings. Docked or idle, it
  only checks the robot's state every 10 s.
- **Import Wi-Fi from the robot** brings the readings into the *Wi-Fi survey* layer
  (readings already imported are skipped) and builds the Wi-Fi map.
- **Remove Wi-Fi recorder from robot…** stops it and deletes it with its readings.

## Good to know

- The script and its readings go to the first writable folder among `/data`,
  `/mnt/UDISK`, `/mnt/data`, `/userdata` and `/tmp` (the install message says which).
  In `/tmp` they are lost at each reboot.
- The robot does not start it at boot by itself: the plugin starts it again each
  time it connects. To have it start with the robot, add this line to the robot's own
  boot script, the one that starts Valetudo (with the folder given at install):

    ```sh
    sh /data/valetudo_wifi_survey.sh /data/valetudo_wifi_survey.csv 2 20 &
    ```

- It needs `wget` or `curl` on the robot. It reads Valetudo locally without a
  password: it does not work if Valetudo's HTTP authentication is on.
- The file keeps the last 50,000 readings (about 2.5 MB).
