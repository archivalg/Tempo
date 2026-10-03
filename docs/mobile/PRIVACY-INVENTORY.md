# Privacy and data-collection inventory (from what the app actually does)

Draft for the owner and a privacy adviser to review; not legal advice. It describes behaviour as built on 4 October 2026. It must be re-checked whenever the app changes.

## Who collects what
Tempo (Ensemble Solutions) operates the service for each **customer company**; the customer is the employer and decides which employees use it. The app has **no analytics, advertising, tracking or crash-reporting SDK** and shows no ads.

| Data | Purpose | Where it goes | Stored on the phone? |
|---|---|---|---|
| Username and password (typed by the employee) | Sign in | Sent to the Tempo API over HTTPS; stored server-side as a salted Argon2id hash | Password never stored. |
| Session tokens (access and refresh) | Keep the person signed in; sign out on expiry | Issued by the Tempo API | **Yes**, only in iOS Keychain / Android Keystore-backed secure storage (this-device-only); removed at sign-out |
| Name, company, site, employment type | Show who is signed in | From the Tempo API | No (held in memory) |
| Shifts, roster changes, offers, leave requests, availability, clocking history, notifications | The app's purpose | From the Tempo API (the customer's data about that employee) | No (held in memory; nothing is cached to disk) |
| Leave requests, availability entries, offer answers, notification preferences (including an optional mobile number if the employee opts in to text messages) | Operate leave, rostering and notifications | Sent to the Tempo API; visible to the customer's managers | No |
| Push token, platform (iOS/Android), app version, device model name | Deliver push notifications | Sent to the Tempo API; the token is passed to the **Expo push service**, which forwards to **Apple (APNs)** or **Google (FCM)** | Token not kept by the app after sign-out (removed from Tempo on sign-out) |
| Notification content | Tell the employee something changed | Generic text only ("Your roster has changed"); no times, places or names. Details are fetched in the app after sign-in | — |
| Delivery tracking (provider answer, receipt, whether the app acknowledged receipt) | Show managers whether notifications are working | Tempo database | — |
| **Kiosk tablet only:** device credential, site, company | Identify the tablet to Tempo | Issued by Tempo at enrolment | Yes, secure storage; removed when a manager leaves kiosk mode |
| **Kiosk tablet only:** worker number + PIN typed, or a QR code scanned | Identify who is clocking | Sent to the Tempo API; the app keeps nothing after the result screen | No (cleared on return to the start screen) |
| **Kiosk tablet only:** camera frames | Scan a QR code | Decoded on the device; **frames are not stored or sent**, only the decoded code | No |
| **Kiosk tablet only:** position (only if the company turned on site location checks) | Check the tablet is at the site | Latitude, longitude, accuracy sent with the clocking and stored with it | No |
| Clock times (clock in/out, breaks) | Attendance | Tempo database; shown to the employee and managers | No |
| Server logs | Security and audit | IP address, user agent, time and action in the Tempo audit trail | — |

## Not collected
Contacts, photos, microphone, advertising ID, health data, precise location from employee phones (location is only requested on kiosk tablets, and only when the company enables it), browsing history, financial information.

## Employee controls
* Choose which notification kinds to receive and the reminder time; turn push off entirely.
* Text messages are off unless the employee turns them on and gives a number; the company must also enable them and set a monthly limit.
* Remove access: a manager removes the account's access; the phone is signed out and notifications stop.
* Rights to access/correct/delete employee data are exercised through the **customer (employer)**; export and deletion processes are not yet built (roadmap M6-OPS).

## Retention and security (current)
Data is kept in the customer's Tempo tenant under the platform's retention rules, which are not yet agreed or implemented (open roadmap item). Transport is HTTPS; secrets use platform secure storage; every request is authorised on the server and isolated by company with database row-level security.

## Answers to store questionnaires (draft, review before submitting)
* **Apple App Privacy:** data linked to the user: *Contact info (name), Identifiers (user ID, device ID/push token), User content?* no, *Usage data?* no, *Location (kiosk only, when enabled)*, *Other data (shifts and attendance, leave and availability)*. Purpose: *App functionality*. Tracking: **No**. 
* **Google Play Data safety:** collects *Name, User IDs, Device or other IDs (push token), Approximate/Precise location (kiosk only, optional)*, *Other app activity (roster interactions)*; shared with *Expo, Apple, Google for push delivery only*; encrypted in transit: yes; data deletion request: through the employer.
* **Camera permission rationale:** QR scanning on kiosk tablets only.
