# Project 5 - HomePulse 2.0: Smart Home Telemetry, Automation, Alerts, and Monitoring

## 1. Purpose and Product Context
HomePulse manages multiple smart homes, per-home membership, device registration/tokens, telemetry ingestion, manual commands, scenes, event-driven automation rules, schedules, alerts/acknowledgements, optional monitoring, outbound webhooks, retention, diagnostics, and reconciliation. The project emphasizes event ordering, replay protection, authorization across tenant boundaries, rule conflicts/cooldowns, timezones, asynchronous retries, secret handling, and nonfunctional reliability/security.

## 2. Intended Users and Roles
- **Home Owner:** Own one or more homes; manage membership, devices, scenes/rules, alerts, and configuration.
- **Home Member:** Operate authorized devices/scenes and view home status according to per-home role.
- **Installer:** Provision/configure devices during an authorized installation workflow but has limited ongoing household-data access.
- **Monitoring Operator:** View and process only alerts for homes enrolled in monitoring according to least-privilege rules.
- **Administrator:** Run maintenance/reconciliation operations and manage system-level support functions.

## 3. Scope
### 3.1 In Scope
- Multiple homes with per-home membership and role authorization.
- Devices with capabilities, external IDs, status, firmware, and device credentials.
- Telemetry ingestion with source event IDs, reported/received time, and device health.
- Manual device commands and multi-action scenes.
- Event-driven rules with conditions, priorities, cooldowns, and ordered actions.
- Time-based schedules with timezone/weekday behavior.
- Alerts, deduplication, acknowledgement, resolution, and optional monitoring integration.
- Outbound webhooks with retry, telemetry retention/archive, export/diagnostics, and reconciliation.
### 3.2 Out of Scope
- Real physical-device protocols such as Zigbee, Z-Wave, Matter, or cloud vendor SDKs.
- Real emergency dispatch or alarm monitoring center integration.
- Real cryptographic hardware/TPM provisioning.
- Audio/video streaming or camera image storage.

## 4. Functional Requirements
| ID | Requirement |
|---|---|
| FR-01 | A user may belong to multiple homes, and authorization shall be evaluated for the specific home being accessed. |
| FR-02 | Each home shall define owner, display name, timezone, and non-precise address label/context. |
| FR-03 | Home owners shall manage membership and per-home roles without granting unintended access to other homes they own. |
| FR-04 | An installer role shall be limited to explicitly authorized installation/provisioning functions and shall not automatically receive ongoing household alert/telemetry access. |
| FR-05 | A device shall belong to exactly one home and shall define external ID, type, supported capabilities, firmware, status, and last-seen time. |
| FR-06 | Device external IDs shall be unique across the system. |
| FR-07 | Device credentials/tokens shall be generated/stored using a secure representation and shall be revocable. |
| FR-08 | A device authentication token shall authorize telemetry only for the device to which the credential is bound. |
| FR-09 | Telemetry ingestion shall include device, source event ID, metric, value/text value, reported time, and receive time. |
| FR-10 | Telemetry replay protection shall be scoped to device plus source event ID so legitimate identical source IDs from different devices do not collide. |
| FR-11 | A duplicate telemetry event for the same device/source event ID shall not create a second telemetry record or execute automations again. |
| FR-12 | Telemetry received outside the configured clock-skew/staleness tolerance shall be handled explicitly and shall not silently replace newer effective device state. |
| FR-13 | Device last-seen/health state shall be derived consistently from accepted telemetry or gateway health events. |
| FR-14 | Home members shall be able to issue only commands supported by the selected device capabilities and allowed by their per-home role. |
| FR-15 | Manual commands to OFFLINE devices shall return a controlled unavailable result unless a documented queued-command behavior is supported. |
| FR-16 | Every manual command shall record device, actor, command, payload, status, and timestamps. |
| FR-17 | A scene shall belong to one home and contain an ordered list of device actions within that home. |
| FR-18 | Scene execution shall validate all actions and report partial/failure outcomes without incorrectly reporting full success. |
| FR-19 | An automation rule shall define home, trigger device/metric/operator/value, priority, cooldown, enabled state, and one or more actions. |
| FR-20 | Supported trigger/condition operators shall include equality, inequality, and numeric comparisons with documented type behavior. |
| FR-21 | Rule actions shall target devices within the same home unless an explicitly supported cross-home automation capability exists. |
| FR-22 | When multiple rules trigger from one event, the system shall apply documented priority ordering consistently. |
| FR-23 | When triggered rules issue conflicting commands to the same device, the documented conflict-resolution policy shall determine the effective action. |
| FR-24 | Rule cooldown shall be tracked per rule rather than globally across all rules in a home. |
| FR-25 | Automation execution shall create a rule-run record containing trigger event, start, result, and completion/error detail. |
| FR-26 | A telemetry retry shall not cause duplicate rule runs for an event that has already been processed. |
| FR-27 | Schedules shall run in the configured home/schedule timezone and respect weekday selections. |
| FR-28 | Schedule execution shall handle daylight-saving transitions according to a documented policy for skipped or repeated local times. |
| FR-29 | A scheduled action shall execute at most once for a given intended local schedule occurrence unless explicitly manually replayed. |
| FR-30 | Alerts shall contain home, source device when applicable, kind, severity, message, status, and creation time. |
| FR-31 | Alert deduplication shall be scoped at least by home, source, alert kind, and configured deduplication window. |
| FR-32 | A user shall be able to acknowledge an alert only if authorized for that home or monitoring workflow. |
| FR-33 | Acknowledgement shall preserve actor, time, and note while changing alert workflow status without deleting the original alert. |
| FR-34 | Only enrolled monitoring homes and alert categories configured for monitoring shall appear to monitoring operators. |
| FR-35 | Monitoring operators shall receive only the minimum home/contact information required for the monitored event. |
| FR-36 | The home-status API shall enforce home membership/role authorization before returning device and alert information. |
| FR-37 | Telemetry APIs and administrative diagnostics shall not return device authentication tokens or webhook secrets. |
| FR-38 | Webhook configuration shall include home, target URL, secret/signing material, event types, and active status. |
| FR-39 | Outbound webhook deliveries shall be signed using the configured secret and shall not disclose the raw secret in payload or logs. |
| FR-40 | Webhook retries shall preserve the original event identity and shall not create a new logical event for each retry. |
| FR-41 | Webhook delivery history shall record attempt, response code, status, and next retry information. |
| FR-42 | Retention processing shall archive/delete telemetry older than the configured retention threshold while preserving newer data. |
| FR-43 | Retention shall not remove records still required to preserve referential or audit evidence for active rule runs/alerts without a documented archival relationship. |
| FR-44 | A rule dry-run/evaluation feature shall evaluate trigger/conditions/actions without issuing real device commands or modifying rule cooldown/state. |
| FR-45 | An administrative home export shall omit or securely redact passwords, device tokens, webhook secrets, and other credentials. |
| FR-46 | A reconciliation operation shall identify inconsistent device last-seen state, orphan actions, cross-home references, duplicate logical events, and invalid alert/monitoring combinations without modifying data. |

## 5. Business and State Rules
| ID | Rule |
|---|---|
| BR-01 | Home authorization is tenant-specific: membership in Home A grants no implicit access to Home B. |
| BR-02 | An installer is not a standing household member unless a separate membership grants that access. |
| BR-03 | Telemetry idempotency key is the tuple (device_id, source_event_id). |
| BR-04 | Rule priority uses a documented direction, with higher numeric priority executing before lower numeric priority unless requirements are formally changed. |
| BR-05 | Rule cooldown is maintained per rule and is measured from the last completed/accepted run according to policy. |
| BR-06 | Alert deduplication includes home so identical devices/alert types in different homes cannot suppress each other. |
| BR-07 | Schedules evaluate in the schedule/home timezone, not server UTC, unless the schedule explicitly uses UTC. |
| BR-08 | Webhook retries preserve the same logical event ID and increase attempt count for that delivery lineage. |
| BR-09 | Retention removes data older than the cutoff, not newer than the cutoff. |
| BR-10 | Dry-run is side-effect free with respect to device commands, persistent rule-run/cooldown state, alerts, and webhooks. |

## 6. Nonfunctional and Quality Requirements
| ID | Requirement |
|---|---|
| NFR-01 | under the supplied reference workload, 95% of normal interactive requests shall complete within 2.0 seconds excluding intentionally simulated third-party latency. |
| NFR-02 | simultaneous operations against the same scarce or stateful resource shall preserve business invariants and shall not create duplicate or impossible records. |
| NFR-03 | authorization shall be enforced on the server for every protected web route and API operation; hiding navigation controls is not sufficient. |
| NFR-04 | stored user passwords shall use an adaptive password-hashing scheme and inactive accounts shall be unable to authenticate. |
| NFR-05 | SQL statements shall be parameterized and externally supplied identifiers shall be validated before they are used. |
| NFR-06 | expected validation, conflict, and integration failures shall produce controlled responses and shall not expose raw stack traces or database details. |
| NFR-07 | state-changing browser operations shall be protected against cross-site request forgery and session cookies shall use secure production settings. |
| NFR-08 | JSON endpoints shall use documented status codes and a consistent error object containing a machine-readable code and human-readable message. |
| NFR-09 | security- and business-significant changes shall record actor, action, object, timestamp, and correlation information sufficient to reconstruct the event. |
| NFR-10 | validation errors shall identify the invalid field and, where practical, preserve other valid user input rather than silently discarding the request. |
| NFR-11 | primary workflows shall be keyboard-operable, form controls shall have programmatically associated labels, and status shall not be communicated by color alone. |
| NFR-12 | retryable integration failures shall not cause duplicate business effects; retries shall be safe or protected by an idempotency mechanism. |
| NFR-13 | operational failures shall be logged with enough context to diagnose them without logging passwords, authentication tokens, payment tokens, or other secrets. |
| NFR-14 | database backup and restore procedures shall be documented and a restored environment shall preserve core records and referential integrity. |
| NFR-15 | membership, device telemetry, automation execution, schedule, alert, webhook, retention, and device-health reconciliation or health checks shall identify internally inconsistent records without silently modifying them. |

## 7. External Interfaces
- Browser interfaces for homes, devices, telemetry views, scenes, rules, alerts, monitoring, and administration.
- JSON POST device-telemetry ingestion with device-token authentication.
- JSON home-status endpoint with tenant authorization.
- DeviceGateway command interface simulating external device control.
- WebhookGateway outbound delivery/retry interface.
- Administrative schedule, retention, export, dry-run, and reconciliation operations.

## 8. Core Data Entities
- **Home / Membership:** Tenant boundary and per-home authorization.
- **Device / Device Token:** Physical/logical endpoint and credential.
- **Telemetry:** Idempotent time-stamped device event stream.
- **Device Command:** Manual/automated actuator history.
- **Scene / Scene Action:** Ordered multi-device action set.
- **Rule / Condition / Action / Run:** Event automation definition and execution evidence.
- **Schedule / Schedule Run:** Timezone-aware scheduled automation.
- **Alert / Acknowledgement:** Operational/safety notification workflow.
- **Monitoring Enrollment / Event:** Optional least-privilege monitoring integration.
- **Webhook / Delivery:** Outbound event integration and retry history.
- **Archive:** Retention/archive operation evidence.
- **Audit Log:** Security and configuration history.

## 9. Primary Use Cases
### UC-01 Ingest Telemetry and Trigger Rule
1. Device authenticates with a device-bound credential and posts unique event.
2. System validates device/event identity, time, and replay status.
3. Accepted telemetry updates health state.
4. Matching rules are evaluated in priority order with per-rule cooldown/conflict handling.
5. System records rule runs and device commands; duplicate telemetry does not repeat effects.
### UC-02 Run a Scene
1. Authorized home member selects a scene.
2. System confirms scene/actions are within the same home and commands are supported.
3. Actions execute in order and individual outcomes are recorded.
4. UI reports complete, partial, or failed result accurately.
### UC-03 Acknowledge Monitored Alert
1. System creates/deduplicates alert for an enrolled home.
2. Authorized home member or monitoring operator views minimum required information.
3. Authorized actor acknowledges with a note.
4. System preserves alert plus acknowledgement history and sends configured integrations if applicable.
### UC-04 Execute Schedule Across Time Change
1. Scheduler resolves intended local occurrence using schedule timezone/weekday policy.
2. System prevents duplicate execution for repeated local time.
3. Scene/rule action executes once and schedule-run evidence is recorded.
### UC-05 Webhook Retry
1. A business event creates signed outbound delivery.
2. First external request fails transiently.
3. Retry preserves event identity, increments attempt, and records response.
4. No duplicate business event is generated by the retry itself.

## 10. Acceptance and Verification Expectations
- Tenant isolation tests cover multiple homes owned by the same user plus unrelated/installer/monitor users.
- Event tests cover duplicate source IDs across different devices, exact replay, out-of-order events, stale timestamps, and concurrent ingestion.
- Automation tests cover rule priority, conflicting actions, per-rule cooldown, dry-run side effects, scenes, and schedule DST behavior.
- Security tests explicitly inspect credentials/tokens/secrets in APIs, exports, logs, and monitoring views; final release recommendation addresses the impact of any exposure.

## 11. Student QA Deliverables
The supplied implementation is an existing system under test. Teams are responsible for independently assessing the requirements and implementation; the package does not assert that either is defect-free.
- Requirements review and issue log, including ambiguity, inconsistency, incompleteness, and testability findings.
- Requirements-to-test traceability matrix covering all testable FR, BR, and NFR items.
- Risk-based test strategy and environment/configuration description.
- Manual and automated tests using black-box and white-box techniques as appropriate.
- API and integration tests where the system exposes or consumes interfaces.
- Nonfunctional testing selected from security, performance, reliability, accessibility, usability, compatibility, and data integrity based on project risk.
- Defect reports containing reproducible steps, expected/actual results, evidence, severity, priority, and requirements linkage.
- Regression evidence and a final Go / Conditional Go / No-Go recommendation supported by objective quality evidence.