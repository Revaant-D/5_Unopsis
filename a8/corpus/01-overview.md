# What Unopsis Is

Unopsis is a notification aggregation service for students and small teams. It connects to the
tools a person already uses and collects their notifications into one reviewable inbox, instead
of leaving them scattered across a dozen separate applications. The core idea came from a
simple observation: most people do not suffer from too few notifications, they suffer from
having no single place to triage them. Unopsis provides that single place. A user links their
accounts once, chooses which categories of event matter to them, and then reads everything in
a unified timeline that can be filtered, searched, snoozed, or exported.

Unopsis is organised around the idea of a space. A space is a container that owns a set of
connectors, a set of filtering rules, and the notifications those connectors produce. A
personal account begins with one space called Personal. Team accounts may create additional
spaces, so that a user can keep coursework separate from an internship, or keep one client's
alerts away from another's. Every notification belongs to exactly one space, and filtering
rules never apply across space boundaries. This is deliberate: it means a noisy project cannot
drown out a quiet but important one, and it means permissions can be granted per space rather
than per account.

The service does not attempt to replace the applications it connects to. Unopsis has no reply
feature, no issue editor, and no chat interface. When a user decides a notification matters,
Unopsis links them straight back to the original item in its source application. This keeps the
product small and keeps its promise narrow: Unopsis decides what deserves attention, and the
source tool remains the place where work actually happens. Users consistently describe this as
the feature they would miss most, because it means adopting Unopsis does not require abandoning
any existing workflow or retraining a team on a new system.

Unopsis began as a course project and is operated by a team of five students. It is not a
venture funded company and it does not sell advertising. Revenue comes entirely from paid
subscriptions, which is the reason the free plan is limited rather than unlimited. The team
publishes a public changelog and a status page, and commits to announcing any breaking change
to the connector API at least thirty days before it takes effect. Because the team is small,
support is handled by the engineers who build the product rather than by a separate support
organisation, and response times reflect that.
