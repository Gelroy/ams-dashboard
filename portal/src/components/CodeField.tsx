/** Six-digit authenticator code. Digits only; lets password managers and
 *  phones offer the one-time code. */
export function CodeField({
  value,
  onChange,
  autoFocus = true,
}: {
  value: string
  onChange: (v: string) => void
  autoFocus?: boolean
}) {
  return (
    <label>
      6-digit code
      <input
        className="code"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        placeholder="000000"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, 6))}
        required
        autoFocus={autoFocus}
      />
    </label>
  )
}
