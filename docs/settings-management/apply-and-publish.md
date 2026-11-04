# Apply, export, and publish settings

This reference defines how apply writes staged values to the application file and how export and publish write the shared source.
Use the [settings guide](../settings-management.md) for the editing and sharing workflow.

## Apply to the application

Apply consumes the stage without fetching, exporting, or collecting application changes.
It handles the application file as follows:

- **Preservation**: It preserves nonmanaged fields and their comments, preserves existing file permissions and line endings, and avoids rewriting semantically unchanged values.
  Formatting within changed nodes can change.
- **JSON formatting**: JSON edits preserve untouched value tokens and key order, changing only the selected values and necessary punctuation or separators.
  Semantically unchanged JSON targets retain their original bytes, including numeric spelling and string escapes.
  New JSON targets use two-space indentation and a final newline; inserted members in existing objects follow their indentation when available.
- **Missing files**: A missing application file is created; deleting all managed fields leaves a file rather than deleting it.
- **Adoption and replacement**: Initial identical values and already absent deletion targets are adopted automatically.
  Different existing values require `aem apply --item editor --replace`; replacement is limited to managed fields.
  Even explicit replacement cannot remove unmanaged descendants during a table/scalar transition.

## Export and publish

Export writes the shared source locally, and Git publish adds a commit and push to that export.

### Export the shared source

If several selected stages share one source file, identical exports are grouped and differing exports are rejected before any write.
Export merges the stage with the current shared source and writes the source settings plus metadata without network access.
It works for both Git and external folders.
External synchronization remains the responsibility of its existing service; external `publish` remains unsupported.

### Publish to Git

Git publish includes export and then uses AEM's existing whole-repository commit and push semantics.
A message is required if export would change either source file or the checkout already has uncommitted changes.
Publication never implicitly collects actual application settings.
Git behind/diverged history must be reconciled before publication; AEM does not merge Git histories or reset local work.
Failed publication preserves successful local exports and commits for retry.
Unselected settings with unexported stage changes in a published checkout are listed under `unpublished_settings` and are not exported implicitly.
