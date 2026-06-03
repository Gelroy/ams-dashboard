"""Reserved for future software-domain signals.

The auto-create-PatchExecution-on-new-Latest handler that used to live here
was retired in the 2026-06-03 patching redesign. The team now triggers
PatchExecution creation explicitly via the "Check for Needed Patch
Executions" button on the Patch Execution page, which calls
patching.services.check_for_needed_executions.
"""
