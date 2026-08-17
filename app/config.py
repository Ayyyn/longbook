from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/textileops"
    gemini_api_key: str = ""

    # Model ids are configuration, not constants: Google retires aliases (the
    # pinned gemini-2.5-flash became 404 for new keys), and a free-tier key has
    # no pro quota at all. Overridable so a deployment can move without a
    # code change.
    model_fast: str = "gemini-3.5-flash-lite"    # per-message extraction
    # Onboarding runs this once per tenant, so the pro tier would be affordable
    # — but flash is the deliberate default and pro is one env var away if a
    # profile ever disappoints.
    model_deep: str = "gemini-3.5-flash-lite"
    # Free-tier keys 429 on the pro models; fall back rather than fail onboarding.
    model_deep_fallback: str = "gemini-3.5-flash-lite"
    # The chat is the one place a customer watches the model think, and the
    # only place a weak answer is visible rather than merely queued for review.
    # Extraction runs thousands of times and stays on the cheap tier; this runs
    # a handful of times a day per business, so the better model costs pennies
    # and buys the difference between "useful" and "why is it like this".
    model_chat: str = "gemini-3.5-flash"

    # Requests per minute to stay under. Free tier is ~10-15 RPM; a backfill
    # that ignores this gets 429s halfway through a customer's history.
    llm_rpm: int = 10

    # Conversation windowing. A window is the extraction unit; these decide
    # where one conversation ends and the next begins. Overridable per tenant
    # through BusinessProfile.rules.
    window_gap_minutes: int = 120
    window_max_messages: int = 40
    window_max_chars: int = 6000

    # Where the backfill actually runs.
    #
    # "inline" keeps it in the API process as a FastAPI background task,
    # which is right for a dev machine and for the verify_*.py scripts.
    # It is wrong for Cloud Run: a deploy, a crash or an instance recycle
    # replaces the container and the backfill dies mid-run with nothing
    # logged, halfway through a new customer's first ten minutes.
    #
    # "cloudrun" executes the textile-backfill Cloud Run job instead, which
    # has its own lifecycle and outlives anything that happens to the API.
    backfill_mode: str = "inline"          # inline | cloudrun
    backfill_job_name: str = "textile-backfill"
    gcp_project: str = ""
    gcp_region: str = "asia-south1"

    # How many files one upload action may carry. Chosen so an owner can
    # select every chat that matters in one go without a mis-tap queueing
    # their whole gallery.
    max_upload_files: int = 20

    # Concurrent windows during a backfill. Higher than the RPM allows
    # simply queues on the pacer, so this is about hiding network latency,
    # not about outrunning the quota.
    backfill_workers: int = 8
    gcs_bucket: str = ""
    bq_dataset: str = "textile_ops"

    # Where uploaded media lands until gcs_bucket is configured. Local disk is
    # fine for the launch cohort; on Cloud Run it is per-instance and ephemeral.
    upload_dir: str = "var/uploads"

    # Gates tenant creation by an operator. Required outside dev — without
    # it, anyone who can reach the service can mint a tenant and its token.
    admin_token: str = ""

    # Inbound mail. Owners forward invoices and POs to a plus-addressed alias
    # on this mailbox, which is read over IMAP. Deliberately separate from the
    # SMTP settings above even though it is usually the same account: sending
    # the digest and reading customer mail are different jobs and should be
    # able to move apart without one breaking the other.
    inbound_address: str = ""
    inbound_password: str = ""      # a Gmail app password, not the login one
    inbound_host: str = "imap.gmail.com"
    inbound_port: int = 993

    # Gmail OAuth. Empty until the console client exists, which is what
    # the connect screen keys "not available yet" off.
    gmail_client_id: str = ""
    gmail_client_secret: str = ""

    # Nylas. The reason we can offer a connected mailbox at all: Google's
    # restricted-scope review sits behind a CASA assessment, and Nylas has
    # already passed it, so the owner grants access to Nylas and we read
    # through them rather than holding a Google refresh token that expires
    # every seven days in Testing mode.
    #
    # The API key is the server credential — it authenticates every call and
    # doubles as the client secret in the code exchange. Treat it like the
    # admin token: Secret Manager only, never a default here.
    nylas_client_id: str = ""
    nylas_api_key: str = ""
    # Region-pinned. Data stays in whichever region the Nylas app was created
    # in, and calling the wrong host returns a 404 for a grant that exists,
    # which reads like a bug in our code and is not one.
    nylas_api_uri: str = "https://api.us.nylas.com"
    # How far back a newly connected mailbox is read on first connect. A year
    # is the useful default: it covers a full cycle of seasonal ordering, so
    # the party history and rate history have something real in them on day
    # one. 0 means everything the mailbox holds.
    nylas_initial_days: int = 365

    # The stop on the first pull, counted in messages. Without one, connecting
    # a mailbox that has been open since 2014 means tens of thousands of
    # newsletters and OTPs going through extraction — a large model bill and a
    # review queue nobody can face. The watermark makes this a pause, not a
    # loss: raise it and the next sync carries on where this one stopped.
    nylas_max_messages: int = 5000

    # This service's own public URL. Needed because an OAuth redirect_uri has
    # to be absolute and has to match what is registered with the provider
    # exactly — deriving it from the incoming request would mean trusting
    # forwarded host headers to build a URL a provider redirects to, which is
    # a redirect somebody else gets to choose. Set at deploy time.
    api_url: str = "http://localhost:8000"

    # Gates self-serve signup. An owner signing themselves up cannot be asked
    # for the admin token — that token mints tenants for every business, so
    # handing it to a customer would be handing over the whole system. But
    # signup cannot be open either: an unauthenticated endpoint that creates
    # a tenant and returns a working token is an open door.
    #
    # So signup takes a shared invite code, given to a prospect along with
    # the link. It is rotatable, carries no privileges beyond creating one
    # business, and is worthless without also completing onboarding. Empty
    # means self-serve signup is closed.
    # One invite code per plan, so the code an owner is given decides what they
    # get. Handing out the right code is the whole of the billing flow: there is
    # no plan picker in the app and no card to enter, because payment happens
    # between two people before the code is sent.
    signup_code_monthly: str = ""
    signup_code_annual: str = ""
    # The original single code. Still honoured so codes already handed out keep
    # working; treated as monthly.
    signup_code: str = ""

    # A crude ceiling on how many businesses one code can create per hour.
    # A leaked code should cost a cleanup, not a bill.
    signup_max_per_hour: int = 10

    auto_commit_floor: float = 0.85
    default_overdue_days: int = 45
    env: str = "dev"

    # Close-of-business digest. Delivery is stdlib SMTP; if smtp_host is empty
    # the digest is still composed and stored, just not sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_ssl: bool = False
    smtp_starttls: bool = True
    digest_from: str = ""
    dashboard_url: str = "http://localhost:3000"

    # Browser origins allowed to call the API. Comma separated. Empty means
    # dashboard_url plus localhost, which is what a dev machine needs and
    # what a single-frontend deployment needs. Never widen this to '*' once
    # a real tenant's data is in the database.
    cors_origins: str = ""

    # Cloud Scheduler hits the digest endpoint with this; it is not a tenant
    # token because the run is cross-tenant.
    scheduler_token: str = ""

    class Config:
        env_file = ".env"


@lru_cache
def settings() -> Settings:
    return Settings()
