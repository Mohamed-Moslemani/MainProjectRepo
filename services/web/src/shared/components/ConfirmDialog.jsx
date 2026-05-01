import { createContext, useCallback, useContext, useState } from 'react';
import L from '@shared/components/L';

// Promise-based, in-app confirmation dialog. Replaces window.confirm
// which can't be styled, can't be bilingual, and looks like a 1990s
// browser alert.
//
// Two ways to use:
//
//   1) The hook (most common — destructive actions inside event
//      handlers):
//
//        const confirm = useConfirm();
//        const ok = await confirm({
//          ar: { title: '…', message: '…', confirm: 'حذف' },
//          en: { title: '…', message: '…', confirm: 'Delete' },
//          destructive: true,
//        });
//        if (!ok) return;
//
//   2) The provider (mount once at the app root, exposes the hook
//      to descendants).

const ConfirmContext = createContext(null);

export function ConfirmProvider({ children }) {
  // request = { ar, en, destructive, resolve } | null
  const [request, setRequest] = useState(null);

  const confirm = useCallback((opts) => {
    return new Promise((resolve) => {
      setRequest({ ...opts, resolve });
    });
  }, []);

  const close = (result) => {
    if (!request) return;
    request.resolve(result);
    setRequest(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {request && <Dialog request={request} onClose={close} />}
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm must be used inside <ConfirmProvider>');
  return ctx;
}

function Dialog({ request, onClose }) {
  const ar = request.ar || {};
  const en = request.en || {};
  const destructive = !!request.destructive;

  return (
    <div
      className="modal-overlay"
      onClick={() => onClose(false)}
      role="dialog"
      aria-modal="true"
      style={{ zIndex: 10000 }}
    >
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 480 }}
      >
        <div className="modal__header">
          <h2>
            <L ar={ar.title || 'تأكيد'} en={en.title || 'Confirm'} />
          </h2>
        </div>
        <div className="modal__body" style={{ padding: '1.25rem 1.5rem' }}>
          <p style={{ margin: 0, lineHeight: 1.6 }}>
            <L ar={ar.message || ''} en={en.message || ''} />
          </p>
        </div>
        <div
          style={{
            display: 'flex',
            gap: '0.5rem',
            justifyContent: 'flex-end',
            padding: '0.75rem 1.5rem 1.25rem',
          }}
        >
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => onClose(false)}
            autoFocus
          >
            <L ar={ar.cancel || 'إلغاء'} en={en.cancel || 'Cancel'} />
          </button>
          <button
            type="button"
            className={`btn ${destructive ? 'btn--danger' : 'btn--primary'}`}
            style={destructive ? { background: '#b91c1c', borderColor: '#b91c1c', color: '#fff' } : undefined}
            onClick={() => onClose(true)}
          >
            <L ar={ar.confirm || 'تأكيد'} en={en.confirm || 'Confirm'} />
          </button>
        </div>
      </div>
    </div>
  );
}
