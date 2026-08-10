# Gmail connector — console setup

Do this once, in the Google Cloud console, for project **`textile-ops-prod`**.
None of it can be done from the CLI: OAuth clients and the consent screen are
console-only.

---

## The constraint that shapes everything

`gmail.readonly` is a **restricted scope**. Google requires a third-party
security assessment (CASA) before an app using it can be published to the
public — that costs money, takes weeks, and has to be repeated annually.

We are not doing that yet. Instead the consent screen stays in **Testing**
mode, which allows **up to 100 test users** with no assessment and no review.

What that means in practice:

- Every customer whose Gmail we connect must be **added by email address as a
  test user** before they can authorise. There is no way around this.
- Test users see an "unverified app" warning during consent and must click
  through *Advanced → Go to Textile Ops (unsafe)*. This is expected and worth
  warning the customer about on the phone, because it looks alarming.
- Refresh tokens issued in Testing mode **expire after 7 days**. The connector
  must handle re-authorisation, and customers will need to reconnect weekly
  until we publish.
- The cap is 100 test users total, for the life of the project.

**Upgrade path**, when the cohort outgrows this: complete the OAuth
verification process, commission a CASA assessment from a Google-approved
assessor, and publish the consent screen. Only then do refresh tokens become
long-lived and the test-user list stop mattering. Budget weeks, not days.

An alternative worth weighing before paying for CASA: `gmail.metadata` and
`gmail.addons.current.message.readonly` are less restricted, but neither gives
us attachment bodies, which is the whole point of reading a mailbox here.

---

## 1. OAuth consent screen

**APIs & Services → OAuth consent screen**

| Field | Value |
|---|---|
| User type | **External** |
| App name | `Textile Ops` |
| User support email | `textiles.diri@gmail.com` |
| App logo | optional — skip for now |
| Application home page | `https://textile-web-u2tpkoxzvq-el.a.run.app` |
| Privacy policy link | `https://textile-web-u2tpkoxzvq-el.a.run.app/privacy` |
| Terms of service link | `https://textile-web-u2tpkoxzvq-el.a.run.app/terms` |
| Authorised domain | `run.app` |
| Developer contact | `textiles.diri@gmail.com` |
| Publishing status | **Testing** — do not click "Publish app" |

> The privacy policy and terms links are required fields even in Testing mode.
> Those two pages do not exist yet — tell me and I will add them, or point the
> fields at the home page for now and fix it before any real customer connects.

## 2. Scopes

**Add or remove scopes → Manually add scopes**, then paste:

```
https://www.googleapis.com/auth/gmail.readonly
```

It will be listed under **Restricted**. That is expected. Save.

Do not add `gmail.modify` or `gmail.send`. We only ever read, and asking for
more than we use makes eventual verification harder and is a promise we would
be breaking.

## 3. Test users

**OAuth consent screen → Test users → Add users**

Add, at minimum:

```
textiles.diri@gmail.com
ytnn13@gmail.com
```

Then one line per customer, as we onboard them. **A customer who is not on
this list cannot connect their Gmail** — the consent screen will refuse them
with `access_blocked`, and the error does not explain why.

## 4. OAuth client

**APIs & Services → Credentials → Create credentials → OAuth client ID**

| Field | Value |
|---|---|
| Application type | **Web application** |
| Name | `Textile Ops API` |

**Authorised redirect URIs** — add both:

```
https://textile-api-u2tpkoxzvq-el.a.run.app/api/connect/gmail/callback
http://localhost:8000/api/connect/gmail/callback
```

Authorised JavaScript origins: **leave empty**. The flow is server-side; the
client secret never reaches the browser.

The redirect points at the **API**, not the dashboard, because the callback
exchanges the code for tokens using the client secret. The API then redirects
the owner back to the dashboard.

Copy the **Client ID** and **Client secret** from the dialog. The secret is
shown once.

## 5. Enable the API

**APIs & Services → Library → Gmail API → Enable**

Or from the CLI:

```
gcloud services enable gmail.googleapis.com --project=textile-ops-prod
```

## 6. Store the credentials

Create the secrets and add your values. Nothing is echoed:

```
gcloud secrets create gmail-client-id --replication-policy=automatic --project=textile-ops-prod
gcloud secrets create gmail-client-secret --replication-policy=automatic --project=textile-ops-prod
```

PowerShell, one at a time — `printf`-equivalent handling so no trailing
newline is stored, which would break the token exchange:

```powershell
$v = Read-Host "Gmail client ID"; $t = [IO.Path]::GetTempFileName(); [IO.File]::WriteAllText($t, $v, (New-Object Text.UTF8Encoding($false))); gcloud secrets versions add gmail-client-id --data-file=$t --project=textile-ops-prod; Remove-Item $t -Force
```

```powershell
$s = Read-Host "Gmail client secret" -AsSecureString; $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); $v = [Runtime.InteropServices.Marshal]::PtrToStringAuto($b); [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b); $t = [IO.Path]::GetTempFileName(); [IO.File]::WriteAllText($t, $v, (New-Object Text.UTF8Encoding($false))); gcloud secrets versions add gmail-client-secret --data-file=$t --project=textile-ops-prod; Remove-Item $t -Force; $v = $null
```

Bash equivalent:

```sh
read -rsp "Gmail client ID: " V && printf '%s' "$V" | gcloud secrets versions add gmail-client-id --data-file=- --project=textile-ops-prod
read -rsp "Gmail client secret: " V && printf '%s' "$V" | gcloud secrets versions add gmail-client-secret --data-file=- --project=textile-ops-prod
```

`deploy/deploy.sh` will mount both into the API as `GMAIL_CLIENT_ID` and
`GMAIL_CLIENT_SECRET` when the connector lands.

---

## 7. Push notifications (for continuous sync)

Gmail's `watch` API publishes to Pub/Sub rather than calling a webhook
directly, so two more things are needed. These can wait until the connector is
being built:

```sh
gcloud services enable pubsub.googleapis.com --project=textile-ops-prod
gcloud pubsub topics create gmail-push --project=textile-ops-prod

# Gmail's own service account must be allowed to publish to the topic.
gcloud pubsub topics add-iam-policy-binding gmail-push \
  --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
  --role=roles/pubsub.publisher --project=textile-ops-prod

gcloud pubsub subscriptions create gmail-push-sub \
  --topic=gmail-push \
  --push-endpoint=https://textile-api-u2tpkoxzvq-el.a.run.app/api/connect/gmail/push \
  --project=textile-ops-prod
```

A `watch` registration lasts **7 days** and must be renewed, so the digest
scheduler will pick up a daily re-watch.

---

## Checklist

- [ ] Consent screen created, **External**, left in **Testing**
- [ ] `gmail.readonly` added under Restricted
- [ ] Test users added (yours, plus each customer's address)
- [ ] Web application OAuth client created
- [ ] Both redirect URIs registered exactly as written above
- [ ] Gmail API enabled
- [ ] `gmail-client-id` and `gmail-client-secret` in Secret Manager
- [ ] Pub/Sub topic and subscription (only when continuous sync is built)
