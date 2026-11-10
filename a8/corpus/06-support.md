# Support and Service Levels

Support is delivered by email and by an in application contact form. The Free plan receives
best effort support with no committed response time, and in practice most free tier questions
are answered within three business days. The Pro plan commits to a first response within one
business day. The Team plan commits to a first response within four business hours during the
business week, which the team defines as nine in the morning to six in the evening Central
Time, Monday through Friday. None of the plans offer telephone support, and there is no live
chat.

The Team plan carries a ninety nine point nine percent monthly uptime commitment. Uptime is
measured against the notification ingestion and delivery path, not against the marketing site
or the public documentation. If monthly uptime falls below the commitment, affected Team
customers receive a service credit of ten percent of that month's fee for each full tenth of a
percent below the target, capped at fifty percent of the monthly fee. Credits are applied to
the following invoice and must be requested within thirty days of the end of the affected
month. The Free and Pro plans carry no uptime commitment.

Scheduled maintenance is announced at least seventy two hours in advance on the status page and
is performed between two and five in the morning Central Time on Sundays wherever possible.
Maintenance windows during which ingestion is paused do not count against the uptime
commitment, provided the announcement requirement was met. Notifications generated during a
paused ingestion window are collected when ingestion resumes, so a maintenance window delays
notifications rather than losing them, with the exception of source services whose APIs expose
only a short event history.

Incidents are classified into three severities. Severity one means notification delivery is
failing for most users, and the team commits to posting an initial status update within thirty
minutes and subsequent updates every hour until resolution. Severity two means a single
connector or a single region is affected, with updates every four hours. Severity three covers
degraded performance and cosmetic faults, which are noted in the changelog rather than on the
status page. A public post incident review is published within five business days for every
severity one incident.
