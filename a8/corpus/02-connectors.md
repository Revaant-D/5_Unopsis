# Connectors and Integrations

A connector is an authenticated link between Unopsis and one external service. Unopsis
currently ships connectors for Gmail, Outlook, Slack, Discord, GitHub, GitLab, Jira, Linear,
Notion, Trello, Zendesk, PagerDuty, and Google Calendar. Each connector is implemented against
the source service's official API and uses OAuth where the provider supports it, so Unopsis
never stores a user's password for a third party service. Adding a connector takes two steps:
authorise Unopsis in the provider's consent screen, then choose which event categories from
that provider should produce notifications. The second step matters, because most providers
emit far more events than any person wants to read.

Connectors poll on a schedule rather than holding open sockets, with one exception. Most
connectors poll every five minutes on paid plans and every fifteen minutes on the free plan.
PagerDuty is the exception: because paging is time critical, PagerDuty events arrive through an
inbound webhook and are delivered within a few seconds. The polling interval is the single
biggest contributor to perceived latency in Unopsis, and it is the first thing the team adjusts
when a user reports that notifications feel slow. Users on paid plans may request a two minute
interval for a single connector by contacting support.

Each connector exposes its own event categories, and the names follow the source service. The
GitHub connector can emit review requested, mention, assigned, workflow failed, and release
published. The Jira and Linear connectors can emit assigned, mentioned, status changed, comment
added, and due date approaching. The Gmail and Outlook connectors can emit direct message,
thread reply, and label matched, where label matched lets a user forward only mail carrying a
specific label. Calendar connectors emit event starting soon, event changed, and invitation
received. Chat connectors emit direct message, channel mention, and keyword matched.

When a connector's authorisation expires or is revoked, Unopsis marks it as degraded rather
than deleting it, retains its existing notifications, and emails the owner. A degraded
connector is retried on a backoff schedule for seven days. If it has not recovered after seven
days it moves to a disabled state and stops being retried, but its historical notifications
remain readable for as long as the plan's retention window allows. Reauthorising a disabled
connector restores it without losing history, and no notifications are backfilled for the
period during which it was disabled.
