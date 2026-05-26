import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Catches render-time errors in any child component subtree and renders a
 * friendly fallback instead of blanking the whole page.
 *
 * What it catches:
 *   - Render-time exceptions (e.g. `someValue.map` when someValue is not an
 *     array, accessing properties of undefined, etc.)
 *   - Errors in lifecycle methods + child constructors.
 *
 * What it does NOT catch (use try/catch in the caller for these):
 *   - Errors inside event handlers
 *   - Promise rejections from fetch/async code (those go to window.onunhandledrejection)
 *   - Errors during server-side rendering (we don't SSR)
 *
 * Usage pattern: wrap each routed page so a bug in /patch-execution doesn't
 * break /customers. Use `key={location.pathname}` on the boundary so a fresh
 * instance mounts per route — that way navigating away and back resets the
 * error state without needing a full reload.
 */

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface to the browser console for now. If we wire up a server-side
    // logging endpoint later (e.g. POST /api/errors/), this is where it
    // would go.
    // eslint-disable-next-line no-console
    console.error('ErrorBoundary caught a render error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-boundary">
          <h2>Something went wrong on this page.</h2>
          <p>
            The error has been logged to your browser console. You can try
            another page using the sidebar, or reload the app.
          </p>
          <details>
            <summary>Error details (for debugging)</summary>
            <pre>{this.state.error.message}</pre>
            {this.state.error.stack && <pre>{this.state.error.stack}</pre>}
          </details>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="error-reload"
          >
            Reload the app
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
