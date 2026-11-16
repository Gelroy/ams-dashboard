"""The built-in template installed by migration 0002. Staff can edit it or
add others in the dashboard (Config → Report Templates)."""

TICKET_SUMMARY_PLACEHOLDER = "[[Ticket summary: to be written before approval]]"

DEFAULT_TEMPLATE_NAME = "Standard monthly report"

DEFAULT_SECTIONS = [
    {
        "key": "overview",
        "title": "Overview",
        "body": (
            "This report was generated for **{customerName}** on {dateTime}. It covers "
            "{report.period} ({report.periodStart|date} to {report.periodEnd|date}).\n"
            "\n"
            "{customerName} is covered by the **{customer.amsLevel|default:standard}** AMS "
            "service level. If you have questions about anything in this report, contact your "
            "AMS team{#if customer.helpDeskPhone} on {customer.helpDeskPhone}{/if}.\n"
        ),
    },
    {
        "key": "monitoring",
        "title": "Monitoring & Availability",
        "body": (
            "{#if metrics.available}\n"
            "Overall availability for the month was "
            "**{metrics.availability.percent|round:2}%**, with "
            "{metrics.availability.downtimeMinutes} minutes of recorded downtime.\n"
            "\n"
            "| Alert severity | Count |\n"
            "| Disaster | {metrics.alerts.disaster} |\n"
            "| High | {metrics.alerts.high} |\n"
            "| Average | {metrics.alerts.average} |\n"
            "| Warning | {metrics.alerts.warning} |\n"
            "| **Total** | **{metrics.alerts.total}** |\n"
            "\n"
            "## Server health\n"
            "\n"
            "| Server | Environment | Availability % | CPU avg % | CPU peak % "
            "| Memory avg % | Disk used % |\n"
            "{#each metrics.hosts}\n"
            "| {name} | {environment} | {availabilityPercent|round:2} | {cpuAvgPercent|round:1} "
            "| {cpuMaxPercent|round:1} | {memoryAvgPercent|round:1} | {diskUsedPercent|round:1} |\n"
            "{/each}\n"
            "\n"
            "## Most frequent problems\n"
            "\n"
            "{#each metrics.topProblems}\n"
            "- {name}: {count} occurrences, {totalMinutes} minutes in total\n"
            "{#else}\n"
            "No recurring problems were recorded this month.\n"
            "{/each}\n"
            "{#else}\n"
            "Monitoring data for {report.period} has not been received yet.\n"
            "{/if}\n"
        ),
    },
    {
        "key": "tickets",
        "title": "Support Tickets",
        "body": (
            "At the time this report was prepared there were **{tickets.open}** open tickets: "
            "{tickets.manual} raised by your team and {tickets.automated} raised automatically "
            "by monitoring.\n"
            "\n"
            "{tickets.summary}\n"
        ),
    },
    {
        "key": "software",
        "title": "System Software & Patch Planning",
        "body": (
            "{software.summary.upToDate} of {software.summary.total} installed components are "
            "on the latest release and {software.summary.behind} have a newer release available"
            "{#if software.summary.eol}; {software.summary.eol} are running end-of-life "
            "software{/if}.\n"
            "\n"
            "## Installed software\n"
            "\n"
            "| Environment | Server | Software | Installed release | Latest release | Status |\n"
            "{#each software.installed}\n"
            "| {environment} | {server} | {software} | {release} | {latestRelease} | {status} |\n"
            "{#else}\n"
            "| — | — | No software is recorded yet | — | — | — |\n"
            "{/each}\n"
            "\n"
            "## Patches applied in {report.period}\n"
            "\n"
            "{#each patching.applied}\n"
            "- {date|date}: {software} in {environment}, {from|default:initial install} to {to}\n"
            "{#else}\n"
            "No patches were applied this month.\n"
            "{/each}\n"
            "\n"
            "## Planned patching\n"
            "\n"
            "{#each patching.planned}\n"
            "- {plannedDate|date|default:Date to be confirmed}: {software} in {environment}\n"
            "{#else}\n"
            "No patching is currently scheduled.\n"
            "{/each}\n"
            "\n"
            "## Certificates expiring soon\n"
            "\n"
            "{#each certificates.expiring}\n"
            "- {server} ({environment}): expires {expiresOn|date}, {daysLeft} days from the "
            "date of this report\n"
            "{#else}\n"
            "No certificates expire in the next 90 days.\n"
            "{/each}\n"
        ),
    },
]

#: Shown beside the template editor. ``metrics.*`` is whatever the
#: monitoring tool delivered, so only the wrapper flag is listed here.
TAG_REFERENCE = [
    ("customerName", "Customer's display name"),
    ("dateTime", "Date and time the report was generated"),
    ("customer.name", "Customer's display name"),
    ("customer.amsLevel", "Essential, Enhanced or Expert"),
    ("customer.country", "Country code"),
    ("customer.helpDeskPhone", "Help desk phone number"),
    ("report.period", "Month covered, e.g. October 2026"),
    ("report.periodStart", "First day of the month (use |date)"),
    ("report.periodEnd", "Last day of the month (use |date)"),
    ("report.generatedDate", "Date the report was generated (use |date)"),
    ("metrics.available", "True when monitoring data was delivered for the month"),
    ("metrics.…", "Any value in the delivered monitoring JSON, by dotted path"),
    ("tickets.open", "Open tickets"),
    ("tickets.manual", "Open tickets raised by people"),
    ("tickets.automated", "Open tickets raised by monitoring"),
    ("tickets.summary", "Written summary of the month's tickets"),
    ("software.installed", "List: environment, server, software, version, release, "
                           "latestRelease, status"),
    ("software.summary.total", "Number of installed components"),
    ("software.summary.upToDate", "Components on the latest release"),
    ("software.summary.behind", "Components with a newer release available"),
    ("software.summary.eol", "Components running end-of-life software"),
    ("patching.applied", "List for the month: date, environment, software, from, to"),
    ("patching.planned", "List of scheduled patching: plannedDate, environment, software"),
    ("certificates.expiring", "List within 90 days: server, environment, expiresOn, daysLeft"),
]
