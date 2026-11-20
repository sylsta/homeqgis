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
- **Save snapshot** (or **Ctrl+Shift+S** in the tab) saves the image as PNG.
- **Full screen** shows the video in its own window (Esc or a double-click closes
  it).
- **Record** saves the video to an MP4 file (H.264) until **Stop recording**; the
  status shows the elapsed time. It records the images already decoded for the live
  view, at their size (*Video width* in the settings) and real speed, so the robot
  gets no second connection. Recording goes on after leaving the tab. The file is a
  fragmented MP4: if QGIS is killed, it stays readable up to its last seconds. Needs
  ffmpeg 5.1 or newer, with libx264.
