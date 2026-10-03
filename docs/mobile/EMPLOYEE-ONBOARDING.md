# Getting employees onto the Tempo app (for customers)

The app is for employees to see their own roster and make simple requests. Managers keep using the Tempo website.

## Before you start
* The person must be loaded in Tempo (staff upload) and **active**.
* You need the *configure* permission (a Tempo administrator).
* The app must be available to your testers (through TestFlight or Google Play internal testing during the pilot).

## Invite someone
1. Tempo website → **Attendance → Badges & PINs**.
2. Find the person, press **Invite** under *Tempo app*.
3. Give the one-time link to them privately (text, in person). Tempo does not email it. It works once and expires after 72 hours. If it expires, press **New link**.

## What the employee does
1. Installs the Tempo app on their phone.
2. Opens the link on that phone. The app asks them to choose a **username and password** (your managers never see the password).
3. Signs in. They see their upcoming published shifts, roster changes, shift offers, leave, availability and clocking history.
4. In **Settings** they can allow notifications and choose which kinds they get and how long before a shift they want a reminder.

## What employees can and cannot see
* Only **published** shifts. A roster that is still a draft, awaiting approval or approved but not yet published is never shown.
* Only their own information. Nobody else's shifts, pay or details.
* Pay is not shown. Payable hours appear against a clocking once a manager approves the timesheet.

## Day to day
* **Roster published or changed:** the employee gets a notification (if allowed) and the change appears in the app.
* **Extra shifts:** Tempo website → *Shift offers*. Choose people on the app, set the shift, send. Whoever accepts first holds it until you confirm. If you change a confirmed shift, the employee must confirm the new details.
* **Leave:** requests arrive under *Leave requests* for a decision. The employee sees the decision in the app.
* **Availability:** employees mark times they cannot work; it shows to planners and counts as a conflict.

## Remove access
Badges & PINs → **Remove**. The person's phone is signed out immediately and notifications stop. They can be invited again later.

## Lost or handed-over phone
Remove access, then invite again with a new link. A phone that was handed to someone else stops getting the previous person's notifications when the new person signs in.

## Problems
* "This sign-in is for employees": managers should use the website.
* "Your account is not linked": ask a manager to invite them again.
* No notifications: check the phone's notification settings, then the app's Settings, then ask your Tempo administrator to check *Administration → Mobile notifications*. Notifications are not sent at all unless your Tempo provider has configured push.
