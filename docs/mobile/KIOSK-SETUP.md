# Tablet kiosk setup (for customers)

The Tempo app can turn an iPad or Android tablet into a shared clock-in kiosk for one site. Clocking is **online only**: if the tablet cannot reach Tempo it says **NOT recorded**; supervisors record the time afterwards (Attendance → Timesheets → Add a missing timesheet).

## 1. Create the device
Tempo website → **Administration → Kiosk devices** → name it, choose the site, create. You get a one-time code valid for 15 minutes.

## 2. Enrol the tablet
Install the Tempo app. On the sign-in screen choose **Set up this device as a kiosk** and enter the code. From then on the tablet opens straight to the kiosk. Revoke or disable the device at any time in Administration: it stops working at once and shows "This kiosk has been disabled".

## 3. Give workers a way to identify
* **Number + PIN:** each worker's badge number comes from your staff upload; set PINs in **Attendance → Badges & PINs**.
* **QR code:** a worker who uses the Tempo app can show a code that changes every minute and works once; the kiosk scans it with the front camera. (A photo of it is useless a minute later.)

## 4. What workers see
Identify → the screen shows a masked identity and only the actions that make sense (Clock in; Start break and Clock out; End break and Clock out) → a large result: **✓ recorded** (with the time Tempo recorded it) or **✕ NOT recorded** (with why). It returns to the start screen by itself after a few seconds and clears everything about the person. A repeated tap shows "Already recorded" and records nothing twice.

## 5. Leaving or changing kiosk mode
Press and hold the logo for 1.5 seconds. A **manager sign-in** is required (a manager for this company and site; administrators also need their authenticator code). Managers may tick *Also disable this kiosk device in Tempo*.

## 6. Lock the tablet to the app (required: the app alone is not a lockdown)
The app brings itself back to the kiosk screen and asks a manager before leaving, but it **cannot stop the operating system being used**. Configure the tablet itself:
* **iPad:** *Guided Access* (Settings → Accessibility → Guided Access; start with a triple-click of the side/home button; set a passcode) or, for managed fleets, *Single App Mode* via mobile device management.
* **Android tablet:** *Screen pinning* (Settings → Security → App pinning) or a managed kiosk/dedicated-device policy through your device management.
Also: keep the tablet plugged in, turn off auto-lock for the kiosk, mount it securely, and allow camera (QR) and, if your company turns on site location checks, location.

## 7. Site location checks (optional)
Attendance → Rules lets an administrator set a site geofence and choose *Off*, *Record* or *Require*. The kiosk then sends the tablet's position at each tap. A refusal says **NOT recorded**. It is the tablet's position, not the worker's, and phone/tablet location can be wrong.

## 8. If something goes wrong
* **Cannot reach Tempo:** nothing is recorded; supervisors add the time later.
* **Worker locked out:** Badges & PINs → Unlock or reset the PIN.
* **Tablet lost or stolen:** disable the device in Administration immediately.
