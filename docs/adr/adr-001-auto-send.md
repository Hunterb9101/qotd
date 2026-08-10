# ADR-001: Automated Participant Email Delivery

- Status: Superseded in part by ADR-004
- Date: 2026-07-18

## Context

QOTD sends one automated weekday trivia email to an organizer-managed participant list and scores replies received by email. The consumer Google account used for this workflow was deactivated and later restored on appeal. Google did not report an abuse event in the Google Cloud console, so the precise enforcement trigger is unknown.

The previous delivery pattern sent one scheduled Gmail message to the sender with every participant included as a blind-copy recipient. Although the participants are known to the organizer, this pattern can resemble unsolicited bulk email and does not provide an explicit subscription boundary or built-in opt-out mechanism.

The replacement must preserve the initial PRD as closely as possible: participants receive and answer QOTD by email, the organizer manages Group membership, automated sends yield to a manually sent question, and replies remain correlated to the applicable QOTD.

## Options Considered

### Continue using the restored consumer Gmail account with Bcc delivery

This requires the least implementation work. Clear sender identification, renewed participant consent, list cleanup, and opt-out instructions would improve the sending pattern, but the account would continue performing the same automated multi-recipient operation that preceded its deactivation. A repeat enforcement action could interrupt the entire game.

### Use Google Workspace with a custom domain

A Workspace mailbox would retain the Gmail API, sent-mail detection, Google Contacts, and reply collection while adding organization ownership and domain authentication. This is the closest technical fit, but it requires paid domain registration and a recurring Workspace subscription, which are not justified for this informal game.

### Use a transactional email provider

A transactional provider is designed for application-generated email and would separate delivery from the organizer mailbox. It would require a custom domain for a stable sender identity, a new inbound-reply integration, and a replacement for Gmail sent-mail detection. This is the largest departure from the current MVP.

### Use a private Google Group

The free version of Google Groups provides an invitation-based `@googlegroups.com` distribution address and member subscription controls. The QOTD Gmail account can send one message to the Group instead of blind-copying every participant. Replies can continue returning to the QOTD Gmail account for scoring.

This option requires careful Group configuration because replies must go to the original sender rather than the full Group. The free version does not provide an API for enumerating Group membership, so QOTD cannot use the Group as a runtime roster.

## Decision

QOTD will use a private, invitation-only Google Group for automated participant delivery.

Generated participant messages will:

- be addressed only to the configured Google Group address;
- include the QOTD Gmail account as `Reply-To`;
- never place participant addresses in `To`, `Cc`, or `Bcc`;
- fail closed in production when the Group address is not configured.

The Group will be configured so that:

- membership is invitation-only;
- only the QOTD organizer account can post new questions;
- replies are directed to the original message author, not the Group;
- conversation history and member visibility are private;
- the standard Google Groups subscription footer is enabled.

Google Contacts will not be used. Any reply correlated to the applicable QOTD
is eligible for scoring. The Scoreboard and activity-roster portion of this
decision is superseded by [ADR-004](adr-004-canonical-state-model.md) and the
[QOTD Definitions](../DEFINITIONS.md): the Scoreboard includes every Player
with a Submission or Score Event in the current Series, including zero and
negative Scores, and non-respondent reporting uses that Scoreboard. An
incorrect answer is retained in reply-processing history but does not create an
automated Score Event.

Manual questions will continue to be sent from the QOTD Gmail account with the exact dated subject, preserving existing sent-mail detection.

## Consequences

The participant experience remains email-based and no paid domain or mailbox is required. Automated Gmail sends have one Group recipient instead of a multi-recipient Bcc pattern, and participants gain an explicit invitation and built-in subscription controls.

Group membership is the only Player list the Organizer maintains. QOTD does
not validate an empty Group or enumerate its members. A Player appears in the
current Series Scoreboard and non-respondent reporting after making a
Submission or receiving a Score Event in that Series. The next monthly Series
starts with a new Scoreboard.

Google Groups still enforces its own spam and content policies, so this decision reduces but does not eliminate platform enforcement risk. If Group delivery becomes unreliable or list synchronization becomes burdensome, the decision should be revisited in favor of a provider with first-class outbound and inbound application email support.
