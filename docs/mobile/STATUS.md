# Mobile: verification status and remaining dependencies

Written 4 October 2026. This is evidence, not a claim of store-readiness. **The app is not store-ready.**

## What was actually run
| Area | Evidence | Where |
|---|---|---|
| Backend API (employee, offers, leave, availability, notifications, jobs, kiosk QR/exit) | `tests/test_mobile.py`, `tests/test_kiosk_mobile.py`: real PostgreSQL, real row-level security, real sign-in with an invited employee account; two companies | this host |
| Staff see published shifts only, drafts and approved-but-unpublished hidden; roster change appears with a notification | `test_staff_see_published_shifts_only_and_a_roster_change_appears_with_a_notification`, `test_a_republished_roster_reports_changed_and_cancelled_shifts_to_the_employee` | this host |
| Offer accept / decline / manager confirm; first acceptance wins under concurrency | `test_offer_*`, `test_simultaneous_acceptances_give_the_shift_to_exactly_one_person` | this host |
| What happens to an acceptance when the shift changes | `test_changing_an_accepted_shift_voids_or_reconfirms_the_acceptance` (rules in `app/core/offers.py`) | this host |
| Availability and leave submission, approval, effect on rosters, cancellation | `test_availability_and_leave_submission_approval_and_effect_on_rosters` | this host |
| Kiosk: clock/break cycle by QR, replay, forgery, expiry, other company, revoked device, manager-authorised exit, invalid sequences, duplicate taps | `tests/test_kiosk_mobile.py`, `tests/test_kiosk.py`, `tests/test_attendance.py` | this host |
| Expired / rotated / reused / revoked sessions | `test_refresh_rotation_logout_and_expired_or_replayed_sessions`, `test_unlinking_cuts_off_the_app_immediately` | this host |
| Company isolation | `test_two_companies_cannot_see_each_others_employees_offers_or_shifts` | this host |
| Overnight and daylight-saving display and reminders (Melbourne, clocks forward 4 Oct 2026) | `test_overnight_and_daylight_saving_shifts_are_displayed_and_reminded_correctly`; app `links-time.test.ts` | this host |
| Notification scheduling, duplicates, preferences, generic lock-screen text, retries, expired tokens, provider-disabled behaviour, acknowledgement and receipts kept distinct | `test_push_*`, `test_reminders_*`, `test_expired_tokens_*`, `test_preferences_*` — against a **mock** provider | this host |
| SMS: off by default, urgent only, opt-in, capped, usage tracked | `test_sms_is_urgent_only_opt_in_capped_tracked_and_never_sent_by_default` — **mock** provider | this host |
| App logic: API client, one shared refresh, expiry vs connection loss, secure-store usage, deep-link routing, site-zone times, kiosk state machine ("NOT recorded" on connection loss), loading / empty / error / offline states | 38 jest tests in `services/tempo-mobile/__tests__` | this host |
| App compiles for both platforms | `expo export --platform android` and `--platform ios` (Metro bundles of 1,400+ modules) with `--no-bytecode` | this host (arm64) |
| Native projects generate with the right identifiers, schemes, permissions | `expo prebuild` output inspected (bundle id, URL schemes, camera / notification / location permissions) | this host |
| Manager web controls | `e2e/mobile-manager.spec.ts` (browser + real employee session over the API): invite → join → offer → accept → confirm → change → reconfirm required → leave → approve → remove access | this host |

## What has NOT been verified (do not assume)
* **No installable build was produced.** This host is arm64 Linux with no JDK, Android SDK or Xcode; Hermes bytecode compilation was skipped. An Android debug APK and an iOS simulator build are defined in `.github/workflows/mobile.yml` and `eas.json` but **have never run**.
* **Not run on any simulator, emulator or real iPhone, iPad, Android phone or tablet.** Screens were verified by component tests, not by eye on a device. No screenshots of the app exist.
* **Push delivery is unverified.** Only a mock provider was used. Real delivery needs the Expo / Apple / Google set-up below. "Accepted by provider" is stored separately from provider receipt and from the app's own acknowledgement, and the screens say so.
* **SMS has no real provider.** Only the interface, caps, usage tracking and a mock exist.
* **Camera QR scanning, keep-awake, location, deep links from a tapped notification** use Expo modules that were bundled but never exercised on hardware.
* **Kiosk lockdown:** the app returns to its kiosk screen and requires a manager sign-in to leave it, but that is **not** operating-system lockdown. iOS Guided Access / Single App Mode and Android screen pinning or a managed kiosk policy must be configured on the tablet (`KIOSK-SETUP.md`).
* **Offline clocking is not supported** (online-only, as specified). A lost connection shows NOT recorded.
* No accessibility audit with VoiceOver / TalkBack; no localisation (English, Australian date formats only); no tablet-specific layout tuning.
* The icon is an **upscaled** copy of the supplied 264 px mark. A designer's 1024 px artwork is required before store submission.
* A GitHub Actions run has not been seen (no access from this host).

## Known behaviours to be aware of
* Sign-in attempts are limited per address (120 per 10 minutes) and per account (10). A warehouse shares one address; the first mass sign-in on shift start could hit the address limit. Adjustable (`TEMPO_LOGIN_IP_LIMIT`).
* Notification jobs run in the API process only when `TEMPO_JOBS_ENABLED=true` (off by default; the push provider is also off by default, so nothing is sent until both are configured). `python -m app.cli run-notification-jobs` runs one cycle by hand.
* Availability marked by an employee takes effect immediately (it is a declaration the manager can see and remove); leave needs approval.
* A manager-set instruction or break is part of what a roster approval covers: editing either after approval invalidates the approval, like any edit.

## External dependencies (cannot be done in code)
1. Apple Developer Program membership and an App Store Connect app record.
2. Google Play Console account and an app record.
3. Confirmed bundle identifiers (proposed `au.com.ensemblesolutions.tempo`, `.test`, `.dev`): permanent once uploaded.
4. Expo account (for EAS builds and the Expo push service) and its project id (`EAS_PROJECT_ID`).
5. Push credentials: an Apple APNs auth key (.p8) and a Firebase project with an FCM v1 service account, both uploaded to Expo.
6. Signing: iOS distribution certificate and provisioning, Android upload key (EAS can manage both once the accounts exist).
7. A hosted privacy policy URL and support contact; store listing assets (designer icon 1024 px, real-device screenshots).
8. Real devices (at least one iPhone, one Android phone, one tablet of each platform you will support) and device-management or lockdown settings for kiosks.
9. A text-message provider decision, sender registration and budget, if SMS is wanted.
10. Final API hostname (roadmap M6-ORIGINS); the app reads it from `app.config.ts` / `EXPO_PUBLIC_API_URL`.
