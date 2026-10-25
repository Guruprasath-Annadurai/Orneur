# Browser engine

Python substrate: `orca.browser_engine`. This is not an HTTP product route and it is not the read-only retriever in `orca/core_runtime/browser.py` on PR #115. That file is unchanged.

A caller must already have authenticated the user. This module does not trust page text, a model, or a caller-supplied principal.

## Grant

`issue_grant(user_id, mission_id, allow_loopback, actions, ttl_seconds, now)`

- `user_id` and `mission_id` are single path segments.
- `ttl_seconds` is 1 to 120.
- Actions are a subset of `navigate`, `click`, `fill`, `scroll`, `screenshot`, `read`, `download`.
- `allow_loopback` accepts only loopback IP literals. `127.0.0.1:9` allows that port only. `127.0.0.1` allows every port on that address. `localhost` is refused.
- An expired grant fails with `grant_expired`. A new grant is required. The old grant is not reused.

## What one engine may do

`BrowserEngine(root, grant).start()` launches `/opt/google/chrome/chrome` (or `ORNEUR_CHROME_BINARY`) with its own user-data directory, a filtering proxy, and no `--no-sandbox`. A symlink, a script, or a command line that contains `--no-sandbox` is refused. The `google-chrome` wrapper on this host injects `--no-sandbox` and must not be used.

The proxy is the network boundary. Loopback HTTP is allowed only when the grant names that address. Every other destination must be HTTPS and must resolve twice to the same public address set. Metadata names, `169.254.0.0/16`, and `fd00:ec2::254` are refused. Private, link-local, multicast, and reserved addresses are refused. The proxy connects to the pinned address, not to a later DNS answer.

Page text is returned with `untrusted: true` and `authority: page_content_not_authority`. `refuse_unsupported("captcha")` and `refuse_unsupported("authentication_challenge")` always refuse.

Screenshots are refused when a password field has a value. Downloads through `accept_download` must be a single basename, at most 1_000_000 bytes, created with `O_EXCL|O_NOFOLLOW` inside the mission quarantine.

`resume()` starts Chrome again only when `state.json` names the same user and mission. A mismatched or missing state is `resume_refused`. The grant used to resume must still be unexpired.

`cancel()` records the request and then closes the process. The record is not a claim that a side effect was rolled back.

## Evidence record

One JSON object per line in `evidence.jsonl` (mode 0600):

- `action`
- `subject_sha256` of the URL, selector, or filename. The raw subject is not stored.
- `content_sha256` of read text when present. The text is not stored.
- `completion`: `performed_unverified`, `verified`, `refused`, or `failed`
- `detail`: a stable code, not page text
- `user_id`, `mission_id`
- `untrusted_page`: true

`verified` is used only for bytes this process wrote (a PNG screenshot, a quarantine file) and for the cancellation record. Navigation, click, fill, scroll, and tabs stay `performed_unverified` when the browser observed the effect. A hash does not say who authored the record. There is no hardware-backed or external witness.

## Error codes

`grant_refused`, `grant_ttl_refused`, `grant_expired`, `action_not_granted`, `naive_clock`, `chrome_binary_refused`, `sandbox_refused`, `browser_already_started`, `browser_exited`, `browser_dead`, `browser_closed`, `navigation_failed`, `final_url_mismatch`, `fill_refused`, `fill_failed`, `scroll_refused`, `scroll_failed`, `screenshot_refused`, `screenshot_failed`, `download_refused`, `selector_refused`, `element_absent`, `tab_limit`, `resume_refused`, `unsupported_challenge`, `url_refused`, `credentials_in_url_refused`, `scheme_refused`, `metadata_refused`, `loopback_refused`, `private_network_refused`, `dns_rebinding_refused`, `name_resolution_refused`, `allowlist_refused`, `connect_refused`.

## Local run

```bash
python3 -m pytest tests/test_browser_engine.py
```

Live tests skip when `/opt/google/chrome/chrome` is missing. A skip is not a pass. This host ran them against Google Chrome 156.0.8078.47. GitHub Actions does not gain a browser pass unless that binary is already on the runner. Do not install Chrome in CI and do not add `--no-sandbox` to make the job green.

## Residuals

- This is not a production browser qualification.
- Public HTTPS was not exercised against an external site. The CONNECT path is policy-checked and covered by refusal tests, not by a live public page.
- Chrome-initiated downloads were not demonstrated. The quarantine writer was.
- `RLIMIT_CPU` is 30 seconds and `RLIMIT_NOFILE` is 1024. There is no memory cap that still allows Chrome to start.
- Headless Chrome on this host ignores `mouseWheel`. Scroll uses `Input.synthesizeScrollGesture`, which did move the viewport in the live test.
- A compromised Chrome process can still be a same-user process. The proxy and the sandbox flag are not a proof against every browser exploit.
- No mission HTTP route calls this engine yet.
