# Technical Architecture

Unopsis is a Django application backed by PostgreSQL. The web tier is stateless and sits behind
a load balancer, which allows it to be scaled horizontally. Connector polling runs in a
separate worker pool driven by Celery with Redis as the broker, so a slow or failing external
API degrades polling without affecting the responsiveness of the web interface. Scheduled work
such as digest assembly and retention pruning runs as periodic Celery tasks. The split between
web and worker tiers is the single most important structural decision in the system, because
external API latency is the dominant source of variance in the product.

Notification deduplication happens at write time. Each incoming event is reduced to a
fingerprint composed of the connector identifier, the source item identifier, and the event
category. If a fingerprint already exists within a twenty four hour window, the incoming event
updates the existing notification's timestamp rather than creating a second row. This matters
because several source APIs re deliver the same event when an item is edited, and without
deduplication a single active pull request could produce dozens of near identical entries in a
user's inbox over the course of a day.

The public API is REST over HTTPS and is available on the Pro and Team plans. Pro accounts are
limited to sixty requests per minute and Team accounts to six hundred requests per minute,
measured per account rather than per token. Exceeding the limit returns HTTP four twenty nine
with a Retry After header. Outbound webhooks are retried up to five times with exponential
backoff starting at ten seconds, and a webhook endpoint that fails all five attempts is marked
unhealthy and skipped for one hour. Webhook payloads are signed with a per endpoint secret
using HMAC SHA two fifty six.

Mobile delivery uses Apple Push Notification service on iOS and Firebase Cloud Messaging on
Android. Push payloads carry only a title and a short preview, never full content, so a lost or
stolen device does not expose notification bodies beyond what is already visible on the lock
screen. Email delivery uses a transactional provider and is rate limited to one message per
minute per user for immediate notifications, which prevents a misconfigured rule from
generating an email storm. Digest emails bypass that limit because they are assembled as a
single message.
