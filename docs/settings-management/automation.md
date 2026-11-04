# Receive and automate settings changes

Use explicit updates to receive shared settings without applying them, or opt into automatic reception and application.
Collection, export, publication, and reattachment remain explicit in every mode.

Apply and publication are independent: apply before publishing to try a change locally, or publish without applying here.
`update editor` receives shared changes into the stage but does not apply them.
`sync --item editor` updates sources and applies selected content only after successful delivery.
Settings have a separate per-item automatic policy, independent of skill policies:

```toml
[settings.editor.update]
trigger = ["agent-start", "interval"]
min_interval = 600
timeout = 30
```

In `policies` mode the omitted trigger defaults to `[]`; configure events to opt in.
Settings always receive and then apply as one sync workflow; there is no check-only or receive-only automatic action.
The policy accepts only `trigger`, `min_interval`, and `timeout`, and does not inherit skill defaults or named policies.
Automatic policy runs require a prepared stage, persist attempts before delivery, and throttle failures as well as successes.
Previews remain offline and do not write stages, actual files, or attempt records.
Full automation prepares, receives, and applies settings by default, using its shared schedule; explicit `trigger = []` and detached items remain excluded.
Git and external settings use the same workflow, while synchronization of an external folder remains outside AEM.
A shared reception failure or conflict stops application; actual-file conflicts preserve the actual file and require explicit resolution or replacement.
Successful reception remains in the stage if application fails; this workflow does not promise rollback across reception and application.
Collection, export, publication, and reattachment are never automatic.
Another item sharing the same Git checkout can advance its source files without receiving or applying an unselected setting.
