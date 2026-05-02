import { Component } from 'react';
import * as Sentry from '@sentry/react';

/**
 * Catch-all React error boundary.
 *
 * Without this, any uncaught render-time error (a bad API response
 * shape, a throw in an effect) blanks the whole SPA — the citizen sees
 * a white page with no clue what went wrong. This wraps the router and
 * shows a recoverable fallback with a "Reload" button + the technical
 * details collapsed for support to copy.
 *
 * Errors here are also a natural Sentry hook point — if/when we add
 * Sentry, componentDidCatch is where we'd call Sentry.captureException.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Surface to the browser console so devs can see the stack during
    // development; in prod the same info appears in the collapsible
    // <details> block below for the user to copy.
    console.error('Unhandled UI error:', error, info);
    this.setState({ info });

    // Ship to Sentry / GlitchTip if a DSN is configured. Sentry.init()
    // is a no-op when the DSN is unset, so captureException is safe
    // to call unconditionally.
    Sentry.captureException(error, { extra: { componentStack: info?.componentStack } });
  }

  handleReload = () => {
    window.location.reload();
  };

  handleHome = () => {
    window.location.href = '/dashboard';
  };

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '2rem',
          background: '#fafafa',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        <div
          style={{
            maxWidth: 560,
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: 12,
            padding: '2rem',
            boxShadow: '0 8px 24px rgba(0,0,0,0.06)',
          }}
        >
          <h1 style={{ fontSize: '1.4rem', marginTop: 0 }}>
            <span lang="ar" style={{ display: 'block' }}>
              حدث خطأ غير متوقع
            </span>
            <span lang="en" style={{ fontSize: '1rem', color: '#6b7280' }}>
              Something went wrong
            </span>
          </h1>
          <p style={{ color: '#374151', lineHeight: 1.6 }}>
            <span lang="ar" style={{ display: 'block' }}>
              يمكنك إعادة تحميل الصفحة أو العودة للرئيسية. لم يتم فقدان بياناتك.
            </span>
            <span lang="en">
              You can reload the page or go back to the dashboard. Your data
              hasn't been lost.
            </span>
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.25rem' }}>
            <button
              type="button"
              onClick={this.handleReload}
              style={{
                padding: '0.6rem 1.1rem',
                background: '#16a34a',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              <span lang="ar">إعادة التحميل</span>{' '}<span lang="en">Reload</span>
            </button>
            <button
              type="button"
              onClick={this.handleHome}
              style={{
                padding: '0.6rem 1.1rem',
                background: '#fff',
                color: '#374151',
                border: '1px solid #d1d5db',
                borderRadius: 6,
                cursor: 'pointer',
              }}
            >
              <span lang="ar">العودة للرئيسية</span>{' '}<span lang="en">Go to dashboard</span>
            </button>
          </div>
          <details style={{ marginTop: '1.5rem', fontSize: '0.85rem', color: '#6b7280' }}>
            <summary style={{ cursor: 'pointer' }}>
              <span lang="ar">تفاصيل تقنية</span>{' / '}<span lang="en">Technical details</span>
            </summary>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                background: '#f9fafb',
                padding: '0.75rem',
                borderRadius: 6,
                marginTop: '0.5rem',
                overflow: 'auto',
                maxHeight: 240,
              }}
            >
              {error?.message || String(error)}
              {info?.componentStack || ''}
            </pre>
          </details>
        </div>
      </div>
    );
  }
}
