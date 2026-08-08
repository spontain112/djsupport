# DJ Support documentation

Use this map to find the canonical document for the question you are trying to
answer.

| Question | Canonical document |
| --- | --- |
| What does DJ Support do and how do I start? | [README](../README.md) |
| What do the product terms mean? | [Domain language](../CONTEXT.md) |
| How is the system divided into modules and adapters? | [Architecture](architecture.md) |
| How do the domain entities relate? | [Domain model](domain-model.md) |
| Which states and authority transitions exist? | [Lifecycles](lifecycles.md) |
| What private files exist and who owns their schemas? | [Private storage](storage.md) |
| How do I develop and test it? | [Contributing](../CONTRIBUTING.md) |
| How do Agent Clients inspect and execute bounded work? | [Agent use](../README.md#ai-agent-use) and [ADR-0002](adr/0002-make-transfer-agent-native.md) |
| What must Release maintainers validate? | [Release checks](../CONTRIBUTING.md#release-checks), [upgrade guidance](upgrading.md), and [release notes](release-notes-0.5.0.md) |
| How do I back up or upgrade retained data? | [Backup and restore](backup-and-restore.md) and [upgrades](upgrading.md) |
| Why were durable architecture choices made? | [Architecture decisions](adr/) |

Historical plans and research explain how decisions were reached. They do not
override the documents above, the public Transfer interface, or executable
tests.
