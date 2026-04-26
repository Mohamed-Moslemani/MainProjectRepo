import { useEffect, useRef } from 'react';

/**
 * Trap keyboard focus inside a container while it's mounted.
 *
 * Modal dialogs are an a11y trap (no pun intended) for keyboard
 * users — without focus management, Tab walks straight out of the
 * modal back into the page underneath, even though the visual
 * overlay suggests the page is unreachable.
 *
 * This hook:
 *   1. On mount, focuses the first focusable element in the container
 *      (or the container itself if none is found).
 *   2. Intercepts Tab / Shift+Tab and wraps focus around the
 *      container's edges.
 *   3. On unmount, restores focus to whatever element triggered the
 *      modal — so a citizen who opened a modal via keyboard ends
 *      up back on the button they pressed, not at the top of the
 *      page.
 *
 * Usage:
 *   const ref = useFocusTrap(isOpen);
 *   return isOpen && <div ref={ref} role="dialog" ...>...</div>;
 *
 * `enabled` lets the same hook be conditionally active without the
 * caller having to mount/unmount the entire subtree just for focus
 * management.
 */
export function useFocusTrap(enabled = true) {
  const ref = useRef(null);
  const restoreFocusTo = useRef(null);

  useEffect(() => {
    if (!enabled) return undefined;
    const node = ref.current;
    if (!node) return undefined;

    restoreFocusTo.current = document.activeElement;

    const focusables = () =>
      Array.from(
        node.querySelectorAll(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );

    // Initial focus — preserve the caller's autoFocus where possible
    const list = focusables();
    if (!node.contains(document.activeElement)) {
      (list[0] || node).focus?.();
    }

    const onKey = (e) => {
      if (e.key !== 'Tab') return;
      const els = focusables();
      if (els.length === 0) {
        e.preventDefault();
        return;
      }
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    node.addEventListener('keydown', onKey);
    return () => {
      node.removeEventListener('keydown', onKey);
      // Restore focus only if the trigger element is still in the DOM
      const target = restoreFocusTo.current;
      if (target && document.body.contains(target)) {
        try {
          target.focus({ preventScroll: true });
        } catch {
          // ignore
        }
      }
    };
  }, [enabled]);

  return ref;
}
