import { useEffect, useRef } from 'react';

/**
 * <img> wrapper that fetches with the JWT bearer token attached.
 *
 * Plain `<img src=...>` can't carry an Authorization header, and the
 * gateway document endpoints are auth-gated, so we fetch the bytes
 * via fetch() + URL.createObjectURL and swap the resolved blob URL
 * onto the underlying img tag. The blob URL is revoked on unmount
 * (and on src change) so we don't leak memory across many docs.
 *
 * Originally inlined inside MukhtarCases.jsx; lifted here so the
 * citizen CaseDetail page can reuse it for inline doc previews.
 */
export default function AuthImage({
  src,
  alt,
  className,
  style,
  onClick,
  onError,
}) {
  const imgRef = useRef(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!src || !token) return;
    let objectUrl;
    let cancelled = false;

    fetch(src, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (r.ok) return r.blob();
        throw new Error(`HTTP ${r.status}`);
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        if (imgRef.current) imgRef.current.src = objectUrl;
      })
      .catch(() => {
        if (cancelled) return;
        if (imgRef.current) imgRef.current.style.display = 'none';
        onError?.();
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, onError]);

  return (
    <img
      ref={imgRef}
      alt={alt}
      className={className}
      style={style}
      onClick={onClick}
    />
  );
}
