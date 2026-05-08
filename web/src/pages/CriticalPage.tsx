import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getCriticalCalendar } from '../api'
import type { CriticalCalendar, CriticalEvent } from '../types'

export function CriticalPage() {
  const [data, setData] = useState<CriticalCalendar | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hideWeekends, setHideWeekends] = useState(false)

  useEffect(() => {
    setLoading(true)
    getCriticalCalendar(6)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="state-cell">Loading…</div>
  if (error) return <div className="error-banner">{error}</div>
  if (!data) return null

  const days: { date: string; dow: number; isToday: boolean; events: CriticalEvent[] }[] = []
  const start = new Date(data.start + 'T00:00:00')
  const end = new Date(data.end + 'T00:00:00')
  const todayKey = new Date().toISOString().slice(0, 10)

  const byDate: Record<string, CriticalEvent[]> = {}
  data.events.forEach((e) => {
    if (!byDate[e.date]) byDate[e.date] = []
    byDate[e.date].push(e)
  })

  for (let d = new Date(start); d < end; d.setDate(d.getDate() + 1)) {
    const dateStr = d.toISOString().slice(0, 10)
    days.push({
      date: dateStr,
      dow: d.getDay(),
      isToday: dateStr === todayKey,
      events: byDate[dateStr] ?? [],
    })
  }

  const visibleDays = hideWeekends ? days.filter((d) => d.dow !== 0 && d.dow !== 6) : days

  return (
    <div>
      <div className="panel-header-row">
        <span className="panel-title">Critical — next 6 weeks</span>
        <span className="panel-hint">
          {data.events.length} event{data.events.length === 1 ? '' : 's'}
        </span>
      </div>

      <div className="filter-bar">
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="checkbox"
            checked={hideWeekends}
            onChange={(e) => setHideWeekends(e.target.checked)}
          />
          Hide weekends
        </label>
      </div>

      {data.events.length === 0 && (
        <div className="state-cell">
          Nothing scheduled. Activities, server cert expirations, and patch
          history all surface here.
        </div>
      )}

      {data.events.length > 0 && (
        <div className="critical-list">
          {visibleDays
            .filter((d) => d.events.length > 0)
            .map((d) => (
              <div key={d.date} className="critical-day">
                <div
                  className={d.isToday ? 'critical-date critical-today' : 'critical-date'}
                >
                  {formatDateHeader(d.date)}
                </div>
                {d.events.map((e, i) => (
                  <EventRow key={i} event={e} />
                ))}
              </div>
            ))}
        </div>
      )}
    </div>
  )
}

function EventRow({ event }: { event: CriticalEvent }) {
  const cls = `critical-event critical-event-${event.kind}`
  const inner = (
    <>
      <span className="critical-time">{event.time ?? '—'}</span>
      <span className="critical-kind">
        {event.kind === 'cert' && 'Cert'}
        {event.kind === 'patch' && 'Patch'}
        {event.kind === 'activity' && (event.type ?? 'Activity')}
      </span>
      <span>{event.label}</span>
    </>
  )
  if (event.organization_id) {
    return (
      <Link to={`/customers/${event.organization_id}`} className={cls}>
        {inner}
      </Link>
    )
  }
  return <div className={cls}>{inner}</div>
}

function formatDateHeader(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  return `${days[d.getDay()]} ${months[d.getMonth()]} ${d.getDate()}`
}
