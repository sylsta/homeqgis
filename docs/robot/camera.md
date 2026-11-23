# Camera

For robots that expose a raw H.264 stream over TCP (by default
`tcp://<robot>:8555`). **📷** in the status strip opens this tab from anywhere.

![The Camera tab](../images/camera.png)

- It needs **ffmpeg**, found in the `PATH` or set in the settings (*Robot* tab,
  *Camera*).
- The image starts at the robot's next full image (key frame): the first one can
  take a few seconds; the status shows how long.
- After leaving the tab, the stream keeps running for a minute, so that coming back
  is instant. It reconnects by itself if it drops.
- **Camera light**: the robot's light, when it has one.
- **Save snapshot** (or **Ctrl+Shift+S** in the tab) saves the image as PNG, by
  default into `photos/` next to the project (else the folder of the last one).
- **Full screen** shows the video in its own window (Esc or a double-click closes
  it).
- **Record** saves the video to an MP4 file (H.264) until **Stop recording**; the
  status shows the elapsed time. It records the images already decoded for the live
  view, at their size (*Video width* in the settings) and real speed, so the robot
  gets no second connection. Recording goes on after leaving the tab. The file is a
  fragmented MP4: if QGIS is killed, it stays readable up to its last seconds. Needs
  ffmpeg 5.1 or newer, with libx264.
- **The robot is recorded whenever it runs**: cleaning, going somewhere,
  returning to its dock or driven by hand — a scheduled job, one sent from the
  plugin, Valetudo or the app, or one already under way when QGIS starts. The
  camera starts if needed and records into `videos/` next to the project
  (`valetudo_job_<date>_<time>.mp4`; while the project has never been saved: the
  folder of the last recording, else your videos folder).
- The recording **stops when the robot is back on its dock at the end of its job**.
  A return in the middle of the job (washing the mops, clean water…; Valetudo says
  *Docked (Resumable)*) does not stop it. Paused or idle away from the dock for 10
  minutes, it stops too, and a new one starts when the robot runs again.
- A recording you stop by hand is not started again before the robot has docked;
  one you start yourself with the robot on its dock stops once it has left and come
  back for good.
- Untick *Record the camera whenever the robot runs* in the settings (*Robot* tab, camera)
  to stop all this. QGIS must be running with the plugin, and ffmpeg installed.

## Recordings

The **Recordings** group under the video (folded by default) shows what has been
saved, newest first, as thumbnails with their date and size:

- **Videos**: `videos/` next to the project and the folder of your last recording
  made by hand. A video's thumbnail is an image taken by ffmpeg one second in, kept
  in a cache of the QGIS profile.
- **Snapshots**: `photos/` next to the project and the folder of your last one.
- **Camera views**: the frames taken along the way (`views/<date>/`).
- **Obstacle photos**: the photos of the obstacle diary (`map/obstacles/`).

A double-click opens one in your system's player or image viewer. Its right-click
menu opens its folder or deletes it (after asking). **Folder** opens the folder of
the newest one; the list refreshes by itself when a video or snapshot is saved and
when you come back to the tab, or with **Refresh**. Only the newest 300 of each kind
are shown.
