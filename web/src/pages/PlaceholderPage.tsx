interface Props {
  title: string
}

export function PlaceholderPage({ title }: Props) {
  return (
    <div>
      <div className="panel-title">{title}</div>
      <div className="panel-hint">Coming soon — this panel hasn’t been ported from the prototype yet.</div>
    </div>
  )
}
